from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from collections.abc import Mapping

import numpy as np
import pyvista as pv
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from crystal_viewer.analysis.morphology import Hkl
from crystal_viewer.analysis.morphology_geometry import MorphologyModel
from crystal_viewer.analysis.twin_geometry import TwinAggregate
from crystal_viewer.ui.morphology_colors import allocate_family_colors, rgb_tuple


@dataclass(frozen=True, slots=True)
class MorphologyMesh:
    mesh: pv.PolyData
    family_by_id: dict[int, Hkl]
    id_by_family: dict[Hkl, int]


def build_morphology_mesh(
    model: MorphologyModel,
    color_by_family: Mapping[Hkl, str] | None = None,
) -> MorphologyMesh:
    colors_by_family = color_by_family or allocate_family_colors(
        plane.family.hkl for plane in model.planes
    )
    return _build_facets_mesh(model.facets, colors_by_family)


def _build_facets_mesh(
    facets,
    colors_by_family: Mapping[Hkl, str],
    *,
    id_by_family: Mapping[Hkl, int] | None = None,
) -> MorphologyMesh:
    families = sorted({facet.family_hkl for facet in facets})
    if id_by_family is None:
        id_by_family = {family: index for index, family in enumerate(families)}
    else:
        id_by_family = dict(id_by_family)
    family_by_id = {index: family for family, index in id_by_family.items()}
    points: list[tuple[float, float, float]] = []
    faces: list[int] = []
    family_ids: list[int] = []
    colors: list[tuple[int, int, int]] = []
    for facet in facets:
        start = len(points)
        points.extend(facet.vertices)
        faces.extend((len(facet.vertices), *(start + offset for offset in range(len(facet.vertices)))))
        family_id = id_by_family[facet.family_hkl]
        family_ids.append(family_id)
        colors.append(rgb_tuple(colors_by_family[facet.family_hkl]))
    mesh = pv.PolyData(np.asarray(points, dtype=float), faces=np.asarray(faces, dtype=np.int64))
    mesh.cell_data["family_id"] = np.asarray(family_ids, dtype=np.int32)
    mesh.cell_data["family_rgb"] = np.asarray(colors, dtype=np.uint8)
    return MorphologyMesh(mesh, family_by_id, id_by_family)


def _polyline_mesh(polylines, *, closed: bool = False) -> pv.PolyData | None:
    points: list[tuple[float, float, float]] = []
    lines: list[int] = []
    for raw in polylines:
        values = tuple(tuple(float(value) for value in point) for point in raw)
        if len(values) < 2:
            continue
        start = len(points)
        points.extend(values)
        indices = list(range(start, start + len(values)))
        if closed and indices[0] != indices[-1]:
            indices.append(indices[0])
        lines.extend((len(indices), *indices))
    if not lines:
        return None
    return pv.PolyData(
        np.asarray(points, dtype=float),
        lines=np.asarray(lines, dtype=np.int64),
    )


class MorphologyViewer(QWidget):
    family_picked = Signal(tuple)
    cif_files_dropped = Signal(tuple)

    def __init__(self, parent=None, *, plotter_factory: Callable[[QWidget], object] = QtInteractor) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = plotter_factory(self)
        layout.addWidget(self.plotter.interactor)
        self.model: MorphologyModel | None = None
        self.mesh_data: MorphologyMesh | None = None
        self.selected_family: Hkl | None = None
        self.surface_actor = None
        self.surface_actors = []
        self.selection_actor = None
        self.domain_selection_actor = None
        self._domain_meshes = {}
        self.structure_name = "Morphology"
        self._picking_active = False

    def set_structure_name(self, name: str) -> None:
        self.structure_name = str(name).strip() or "Morphology"

    def set_model(
        self,
        model: MorphologyModel,
        *,
        aggregate: TwinAggregate | None = None,
        induction_contours=(),
        twin_segments=(),
        markings=(),
        color_by_family: Mapping[Hkl, str] | None = None,
        reset_camera: bool = False,
    ) -> None:
        camera = None if reset_camera else self.plotter.camera_position
        if self._picking_active:
            disable_picking = getattr(self.plotter, "disable_picking", None)
            if disable_picking is not None:
                disable_picking()
            self._picking_active = False
        self.plotter.clear()
        self.model = model
        colors_by_family = color_by_family or allocate_family_colors(
            plane.family.hkl for plane in model.planes
        )
        visible_facets = model.facets if aggregate is None else aggregate.external_facets
        global_families = sorted({facet.family_hkl for facet in visible_facets})
        global_ids = {family: index for index, family in enumerate(global_families)}
        self.mesh_data = _build_facets_mesh(
            visible_facets,
            colors_by_family,
            id_by_family=global_ids,
        )
        self.selected_family = None
        self.selection_actor = None
        self.domain_selection_actor = None
        self.surface_actors = []
        self._domain_meshes = {}
        if aggregate is None:
            display_groups = (("I", visible_facets, "#26384a", 1.2),)
        else:
            display_groups = tuple(
                (
                    domain.domain_id,
                    domain.facets,
                    "#26384a" if domain.orientation_state == "I" else "#8a3158",
                    1.2 if domain.orientation_state == "I" else 2.2,
                )
                for domain in aggregate.domains
            )
        for domain_id, facets, edge_color, line_width in display_groups:
            domain_mesh = _build_facets_mesh(
                facets,
                colors_by_family,
                id_by_family=global_ids,
            )
            self._domain_meshes[domain_id] = domain_mesh.mesh
            actor = self.plotter.add_mesh(
                domain_mesh.mesh,
                scalars="family_rgb",
                rgb=True,
                opacity=1.0,
                show_edges=True,
                edge_color=edge_color,
                line_width=line_width,
                smooth_shading=False,
                name=f"morphology-domain-{domain_id}",
            )
            self.surface_actors.append(actor)
        self.surface_actor = self.surface_actors[0] if self.surface_actors else None
        label_points = [np.mean(np.asarray(facet.vertices, dtype=float), axis=0) for facet in visible_facets]
        facet_labels = []
        for facet in visible_facets:
            hkl = facet.display_hkl if hasattr(facet, "display_hkl") else facet.plane_hkl
            label = f"({hkl[0]} {hkl[1]} {hkl[2]})"
            domain_id = getattr(facet, "domain_id", "I")
            if aggregate is not None and domain_id != "I":
                label = f"{domain_id} · {label}"
            facet_labels.append(label)
        if label_points:
            self.plotter.add_point_labels(
                np.asarray(label_points),
                facet_labels,
                show_points=False,
                shape=None,
                font_size=10,
                text_color="#172033",
                always_visible=False,
                name="morphology-facet-labels",
            )

        if aggregate is not None:
            composition_mesh = _polyline_mesh(
                (plane.polygon for plane in aggregate.composition_planes),
                closed=True,
            )
            if composition_mesh is not None:
                self.plotter.add_mesh(
                    composition_mesh,
                    color="#26384a",
                    line_width=3.0,
                    name="morphology-composition-planes",
                    pickable=False,
                )
                self.plotter.add_point_labels(
                    np.asarray(
                        [np.mean(np.asarray(plane.polygon, dtype=float), axis=0) for plane in aggregate.composition_planes]
                    ),
                    [
                        f"Composition ({plane.hkl[0]} {plane.hkl[1]} {plane.hkl[2]})"
                        for plane in aggregate.composition_planes
                    ],
                    show_points=False,
                    shape=None,
                    font_size=10,
                    text_color="#172033",
                    always_visible=False,
                    name="morphology-composition-labels",
                )
            self._add_orientation_triads(aggregate)

        induction_mesh = _polyline_mesh(
            (contour.points for contour in induction_contours),
        )
        if induction_mesh is not None:
            induction_width = max(
                (
                    marking.line_width
                    for marking in markings
                    if getattr(marking, "kind", None).value == "induction"
                ),
                default=2.0,
            )
            self.plotter.add_mesh(
                induction_mesh,
                color="#f59e0b",
                line_width=induction_width,
                name="morphology-induction-lines",
                pickable=False,
            )
        twin_mesh = _polyline_mesh(
            ((segment.start, segment.end) for segment in twin_segments),
        )
        if twin_mesh is not None:
            twin_width = max(
                (
                    marking.line_width
                    for marking in markings
                    if getattr(marking, "kind", None).value == "twin"
                ),
                default=2.4,
            )
            self.plotter.add_mesh(
                twin_mesh,
                color="#e11d48",
                line_width=twin_width,
                name="morphology-twin-lines",
                pickable=False,
            )
        self.plotter.add_axes(xlabel="a", ylabel="b", zlabel="c")
        self.plotter.add_text(
            self.structure_name,
            position="upper_edge",
            font_size=11,
            color="#172033",
            name="morphology-structure-name",
        )
        legend_entries = [
            (f"{{{family[0]} {family[1]} {family[2]}}}", colors_by_family[family])
            for family in sorted(self.mesh_data.id_by_family)
        ]
        if legend_entries:
            self.plotter.add_legend(legend_entries, bcolor="#ffffff", border=True, size=(0.16, 0.16))
        self.plotter.enable_cell_picking(
            callback=self._cells_picked,
            through=False,
            show=False,
            start=False,
            show_message=False,
        )
        self._picking_active = True
        if camera is not None:
            self.plotter.camera_position = camera
        else:
            self.plotter.reset_camera()
        self.plotter.render()

    def _add_orientation_triads(self, aggregate: TwinAggregate) -> None:
        all_vertices = np.asarray(
            [point for domain in aggregate.domains for point in domain.vertices],
            dtype=float,
        )
        if len(all_vertices):
            extent = float(np.max(np.ptp(all_vertices, axis=0)))
        else:
            extent = 1.0
        scale = max(extent, 1.0) * 0.14
        for domain in aggregate.domains:
            orientation = np.asarray(domain.orientation, dtype=float)
            origin = np.asarray(domain.translation, dtype=float)
            endpoints = tuple(origin + scale * orientation[:, index] for index in range(3))
            mesh = _polyline_mesh(((origin, endpoint) for endpoint in endpoints))
            if mesh is not None:
                self.plotter.add_mesh(
                    mesh,
                    color="#34495e" if domain.orientation_state == "I" else "#8a3158",
                    line_width=2.2,
                    name=f"morphology-triad-{domain.domain_id}",
                    pickable=False,
                )
            self.plotter.add_point_labels(
                np.asarray(endpoints),
                tuple(f"{domain.domain_id} {axis}" for axis in ("a", "b", "c")),
                show_points=False,
                shape=None,
                font_size=9,
                text_color="#172033",
                always_visible=False,
                name=f"morphology-triad-labels-{domain.domain_id}",
            )

    def _cells_picked(self, cells) -> None:
        if cells is None or "family_id" not in cells.cell_data or len(cells.cell_data["family_id"]) == 0:
            return
        family_id = int(np.asarray(cells.cell_data["family_id"])[0])
        if self.mesh_data is None or family_id not in self.mesh_data.family_by_id:
            return
        family = self.mesh_data.family_by_id[family_id]
        self.select_family(family)
        self.family_picked.emit(family)

    def select_family(self, family: Hkl | None) -> None:
        self.selected_family = family
        if self.selection_actor is not None:
            self.plotter.remove_actor(self.selection_actor)
            self.selection_actor = None
        self.plotter.remove_actor("morphology-family-label")
        if family is None or self.mesh_data is None or family not in self.mesh_data.id_by_family:
            self.plotter.render()
            return
        family_id = self.mesh_data.id_by_family[family]
        mask = np.flatnonzero(np.asarray(self.mesh_data.mesh.cell_data["family_id"]) == family_id)
        if len(mask):
            selected = self.mesh_data.mesh.extract_cells(mask).extract_surface(
                algorithm="dataset_surface"
            )
            self.selection_actor = self.plotter.add_mesh(
                selected,
                style="wireframe",
                color="#ffcf33",
                line_width=5.0,
            )
        self.plotter.add_text(
            f"{{{family[0]} {family[1]} {family[2]}}}",
            position="upper_left",
            font_size=11,
            color="#172033",
            name="morphology-family-label",
        )
        self.plotter.render()

    def select_domain(self, domain_id: str | None) -> None:
        if self.domain_selection_actor is not None:
            self.plotter.remove_actor(self.domain_selection_actor)
            self.domain_selection_actor = None
        mesh = self._domain_meshes.get(str(domain_id)) if domain_id is not None else None
        if mesh is not None:
            self.domain_selection_actor = self.plotter.add_mesh(
                mesh,
                style="wireframe",
                color="#ffcf33",
                line_width=4.0,
                name="morphology-domain-selection",
                pickable=False,
            )
        self.plotter.render()

    def clear(self) -> None:
        if self._picking_active:
            disable_picking = getattr(self.plotter, "disable_picking", None)
            if disable_picking is not None:
                disable_picking()
            self._picking_active = False
        self.plotter.clear()
        self.model = None
        self.mesh_data = None
        self.selected_family = None
        self.surface_actor = None
        self.selection_actor = None
        self.domain_selection_actor = None
        self._domain_meshes = {}

    def export_png(self, path: str | Path) -> None:
        self.plotter.screenshot(str(path))

    def dragEnterEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if any(Path(path).suffix.lower() in {".cif", ".xpff"} for path in paths):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = tuple(
            path
            for path in (url.toLocalFile() for url in event.mimeData().urls())
            if Path(path).suffix.lower() in {".cif", ".xpff"}
        )
        if paths:
            self.cif_files_dropped.emit(paths)
            event.acceptProposedAction()


__all__ = ["MorphologyMesh", "MorphologyViewer", "build_morphology_mesh"]
