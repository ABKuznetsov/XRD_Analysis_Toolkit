from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkAssembly,
    vtkPolyDataMapper,
    vtkTextActor,
)

from crystal_viewer.analysis.hierarchy import (
    HierarchyLevel,
    HierarchyReport,
    normalized_rigidity,
    polyhedron_rigidity_index,
)
from crystal_viewer.core.chemistry import (
    COVALENT_RADII,
    ELEMENT_COLORS,
    SiteRole,
    site_colour,
    site_radius,
    site_role,
)
from crystal_viewer.core.model import AtomSite, CrystalStructure
from crystal_viewer.core.document import StructureDocument, VisualizationState
from crystal_viewer.core.scene import SceneData
from crystal_viewer.core.structure_io import is_supported_structure_path
from crystal_viewer.core.site_orbits import bond_families, site_orbit_key
from crystal_viewer.ui.comparison_highlight import (
    MUTED_COLOR,
    OUTLINE_RED,
    ComparisonHighlight,
)


_TOPOLOGY_COLORS = (
    "#0072b2",
    "#009e73",
    "#d55e00",
    "#cc79a7",
    "#e69f00",
    "#56b4e9",
    "#6f42c1",
    "#8c564b",
)

from crystal_viewer.ui.legend import atom_legend_labels
from crystal_viewer.ui.render_batches import (
    CylinderInstance,
    GradientCylinderInstance,
    OccupancySphereInstance,
    SphereInstance,
    SurfaceInstance,
    build_cylinder_batch,
    build_gradient_cylinder_batch,
    build_occupancy_sphere_batch,
    build_sphere_batch,
    build_surface_batch,
    detail_level_for_atom_count,
    group_spheres_by_material,
)

PICK_POLYHEDRON = 1
PICK_ATOM = 2
PICK_BOND = 3
PICK_UNIT = 4
PICK_BLOCK = 5


def _picked_source_index(picked, primitive_kind: int) -> int | None:
    if picked is None:
        return None
    cell_data = getattr(picked, "cell_data", {})
    kinds = np.asarray(cell_data.get("pick_kind", ())).reshape(-1)
    indices = np.asarray(cell_data.get("source_index", ())).reshape(-1)
    matching = np.flatnonzero(kinds == primitive_kind)
    if not len(matching) or not len(indices):
        return None
    offset = int(matching[0])
    if offset >= len(indices):
        return None
    try:
        return int(indices[offset])
    except (TypeError, ValueError, OverflowError):
        return None


def _tag_pick_kind(mesh, primitive_kind: int) -> None:
    """Attach picking metadata to real PyVista batches; tolerate test doubles."""
    if not hasattr(mesh, "cell_data") or not hasattr(mesh, "n_cells"):
        return
    mesh.cell_data["pick_kind"] = np.full(
        mesh.n_cells, primitive_kind, dtype=np.uint8
    )


def picked_scene_object(picked, hierarchy, scene, requested_kind: str):
    """Resolve a picked display primitive to one stable scientific object."""
    requested = str(requested_kind).strip().lower()
    if requested == "atom":
        index = _picked_source_index(picked, PICK_ATOM)
        if index is None or scene is None or not 0 <= index < len(scene.atoms):
            return None
        return "atom", int(scene.atoms[index].site_index)
    if requested == "bond":
        index = _picked_source_index(picked, PICK_BOND)
        if index is None or scene is None or not 0 <= index < len(scene.bonds):
            return None
        bond = scene.bonds[index]
        try:
            elements = (
                scene.atoms[bond.first].site.element,
                scene.atoms[bond.second].site.element,
            )
        except (AttributeError, IndexError, TypeError):
            return None
        return "bond", tuple(sorted(elements))

    direct_collection = {
        "unit": (PICK_UNIT, "structural_units"),
        "block": (PICK_BLOCK, "blocks"),
    }.get(requested)
    if direct_collection is not None and hierarchy is not None:
        primitive_kind, collection_name = direct_collection
        direct_index = _picked_source_index(picked, primitive_kind)
        collection = getattr(hierarchy, collection_name, ())
        if direct_index is not None and 0 <= direct_index < len(collection):
            return requested, collection[direct_index].id

    index = _picked_source_index(picked, PICK_POLYHEDRON)
    polyhedra = getattr(hierarchy, "polyhedra", ()) if hierarchy is not None else ()
    if index is None or not 0 <= index < len(polyhedra):
        return None
    polyhedron_id = polyhedra[index].id
    if requested == "polyhedron":
        return "polyhedron", polyhedron_id
    collection_name = {
        "unit": "structural_units",
        "block": "blocks",
    }.get(requested)
    if collection_name is None:
        return None
    for aggregate in getattr(hierarchy, collection_name, ()):
        if polyhedron_id in aggregate.polyhedron_ids:
            return requested, aggregate.id
    return None


def rotate_camera_about_axis(
    position, focal_point, view_up, axis, angle_degrees: float
) -> tuple[np.ndarray, np.ndarray]:
    """Rotate camera position and up-vector about a crystallographic axis."""
    direction = np.asarray(axis, dtype=float)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-12:
        return np.asarray(position, dtype=float), np.asarray(view_up, dtype=float)
    direction /= norm
    angle = np.deg2rad(float(angle_degrees))
    x, y, z = direction
    cross = np.asarray(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))
    rotation = (
        np.eye(3) * np.cos(angle)
        + (1.0 - np.cos(angle)) * np.outer(direction, direction)
        + np.sin(angle) * cross
    )
    focal = np.asarray(focal_point, dtype=float)
    rotated_position = focal + rotation @ (np.asarray(position, dtype=float) - focal)
    rotated_up = rotation @ np.asarray(view_up, dtype=float)
    return rotated_position, rotated_up


def picked_polyhedron_id(picked, hierarchy: HierarchyReport | None) -> str | None:
    """Resolve a batched picked cell to its source polyhedron."""
    if picked is None or hierarchy is None:
        return None
    source_index = _picked_source_index(picked, PICK_POLYHEDRON)
    if source_index is None:
        return None
    if not 0 <= source_index < len(hierarchy.polyhedra):
        return None
    return hierarchy.polyhedra[source_index].id

VACANCY_COLOR = "#eef1f5"

IONIC_RADII = {
    ("Li", 4): 0.59,
    ("Li", 6): 0.76,
    ("Li", 8): 0.92,
    ("B", 3): 0.15,
    ("Si", 4): 0.26,
    ("Al", 4): 0.39,
    ("Al", 6): 0.535,
    ("Mg", 6): 0.72,
    ("Ti", 6): 0.605,
    ("Zr", 6): 0.72,
    ("Na", 6): 1.02,
    ("Na", 8): 1.18,
    ("Ca", 6): 1.00,
    ("Ca", 8): 1.12,
    ("K", 8): 1.51,
    ("K", 9): 1.55,
    ("Sr", 8): 1.26,
    ("Sr", 9): 1.31,
    ("Y", 6): 0.90,
    ("Tb", 6): 0.923,
    ("Dy", 6): 0.912,
}

BLOCK_COLORS = ("#45a3ff", "#3ccf91", "#ffad5c", "#b983ff", "#ff6f91", "#4dd6d2", "#e5c14f")
BLOCK_TYPE_COLORS = {
    "framework fragment": "#35ad58",
    "layer": "#8f45c7",
    "chain fragment": "#35a4d4",
    "ribbon": "#4f83d1",
    "cluster": "#ed8a38",
    "ring": "#d85c9e",
    "dimer": "#5d8ed4",
    "trimer": "#6f78d8",
    "isolated polyhedron": "#9b6bc2",
}
STRUCTURAL_UNIT_TYPE_COLORS = {
    "island": "#8f5ac8",
    "pyro group": "#397ed1",
    "linking tetrahedron": "#7d63bd",
    "tetrahedral unit": "#397ed1",
    "interlayer polyhedron": "#3aa879",
    "isolated polyhedron": "#8f5ac8",
    "dimer": "#397ed1",
    "trimer": "#6269cf",
    "chain fragment": "#159fba",
    "ribbon": "#397bc0",
    "ring": "#cc5798",
    "layer": "#2b9b67",
    "framework fragment": "#22945f",
    "cluster": "#dd8730",
}
POLYHEDRON_COLORS = {
    "B": "#35b839",
    "Si": "#326fd1",
    "Al": "#8f45c7",
    "Al/Si": "#9c6aae",
    "Ca": "#35ad58",
    "Mg": "#21a65f",
    "Na": "#d49a22",
    "K": "#6337df",
    "Sr": "#57d92f",
    "Y": "#ee612e",
    "Tb": "#ef5b2a",
    "Dy": "#ef5b2a",
    "Ti": "#459fa7",
    "Zr": "#3c99a8",
}


def _shade(hex_color: str, factor: float) -> str:
    values = [int(hex_color[index : index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{max(0, min(255, round(value * factor))):02x}" for value in values)


def _tone(hex_color: str, amount: float) -> str:
    """Lighten (positive) or darken (negative) while preserving hue."""
    rgb = np.asarray([int(hex_color[index : index + 2], 16) for index in (1, 3, 5)], dtype=float)
    target = np.full(3, 255.0) if amount >= 0.0 else np.zeros(3)
    mixed = rgb * (1.0 - abs(amount)) + target * abs(amount)
    return "#" + "".join(f"{int(round(value)):02x}" for value in np.clip(mixed, 0, 255))


def _rgb_tuple(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[index : index + 2], 16) for index in (1, 3, 5))


def _comparison_atom_color(
    highlight: ComparisonHighlight | None,
    site_index: int,
) -> str | None:
    if highlight is None:
        return None
    if f"I{site_index}" in highlight.muted_ids:
        return MUTED_COLOR
    return highlight.atom_colors.get(site_index)


def _comparison_atom_outlined(
    highlight: ComparisonHighlight | None,
    site_index: int,
) -> bool:
    return highlight is not None and f"I{site_index}" in highlight.outline_ids


def _comparison_polyhedron_color(
    highlight: ComparisonHighlight | None,
    polyhedron_id: str,
) -> str | None:
    if highlight is None:
        return None
    if polyhedron_id in highlight.muted_ids:
        return MUTED_COLOR
    return highlight.polyhedron_colors.get(polyhedron_id)


def _comparison_outlined(
    highlight: ComparisonHighlight | None,
    polyhedron_id: str,
) -> bool:
    return highlight is not None and polyhedron_id in highlight.outline_ids


def _covalent_display_radius(element: str) -> float:
    """Ball-and-stick radius in Å, derived from the element's covalent radius."""
    return float(np.clip(COVALENT_RADII.get(element, 0.90) * 0.46, 0.22, 0.86))


def _site_display_radius(site) -> float:
    return float(np.clip(site_radius(site).value * 0.46, 0.22, 0.86))


def _polyhedron_center_site(structure, polyhedron) -> AtomSite:
    sites = getattr(structure, "sites", ())
    if 0 <= polyhedron.center_index < len(sites):
        return sites[polyhedron.center_index]
    return AtomSite(
        f"{polyhedron.center_element}{polyhedron.center_index + 1}",
        polyhedron.center_element,
        (0.0, 0.0, 0.0),
    )


def _coordination_ionic_radius(element: str, coordination: int) -> float:
    candidates = [(abs(cn - coordination), radius) for (symbol, cn), radius in IONIC_RADII.items() if symbol == element]
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]
    return _covalent_display_radius(element)


@dataclass(frozen=True, slots=True)
class CameraState:
    position: tuple[float, float, float]
    focal_offset: tuple[float, float, float]
    view_up: tuple[float, float, float]
    parallel_scale: float
    view_angle: float
    parallel_projection: bool


class CrystalInteractor(QtInteractor):
    """QtInteractor with smooth, explicit wheel/trackpad camera zoom."""

    cif_files_dropped = Signal(object)

    @staticmethod
    def _dropped_cif_paths(event) -> tuple[str, ...]:
        return tuple(
            path
            for url in event.mimeData().urls()
            if (path := url.toLocalFile()) and is_supported_structure_path(path)
        )

    def dragEnterEvent(self, event) -> None:
        if CrystalInteractor._dropped_cif_paths(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        paths = CrystalInteractor._dropped_cif_paths(event)
        if paths:
            self.cif_files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def wheelEvent(self, event) -> None:
        angle = event.angleDelta().y()
        pixel = event.pixelDelta().y()
        delta = pixel if pixel else angle
        if delta:
            # Trackpads often send deltas far below Qt's traditional 120-unit step.
            strength = min(abs(delta) / (55.0 if pixel else 120.0), 2.5)
            factor = 1.0 + 0.16 * max(strength, 0.18)
            self.camera.zoom(factor if delta > 0 else 1.0 / factor)
            self.render()
            event.accept()
            return
        super().wheelEvent(event)


class StructureViewer(QWidget):
    object_picked = Signal(str)
    scene_object_picked = Signal(str, object)
    scene_selection_cleared = Signal()
    edit_mode_changed = Signal(bool)
    edit_context_menu_requested = Signal(object)
    cif_files_dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = CrystalInteractor(self)
        self.plotter.cif_files_dropped.connect(self.cif_files_dropped)
        self.plotter.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.plotter.installEventFilter(self)
        layout.addWidget(self.plotter)
        self.structure: CrystalStructure | None = None
        self.scene: SceneData | None = None
        self.hierarchy: HierarchyReport | None = None
        self.level = HierarchyLevel.SITES
        self.atom_scale = 1.0
        self.polyhedron_opacity = 0.36
        self.show_cell = True
        self.show_periodic_cell_grid = False
        self.show_axes = True
        self.show_centers = True
        self.show_connectors = True
        self.show_polyhedra = True
        self.show_atoms = True
        self.show_bonds = True
        self.show_labels = False
        self.split_mixed_occupancies = True
        self.show_vacancy_sectors = True
        self.show_connector_labels = False
        self.show_legend = False
        self.show_polyhedron_spokes = True
        self.show_polyhedron_edges = True
        self.bond_style = "bicolor"
        self.cell_line_width = 1.8
        self.show_cell_dimensions = False
        self.axes_size = 0.30
        self.bond_radius = 0.05
        self.polyhedron_edge_radius = 0.020
        self.color_by = "automatic"
        self.adaptive_rigidity_scale = True
        self.radius_model = "coordination_ionic"
        self._polyhedron_legend_widgets: list[vtkOrientationMarkerWidget] = []
        self._polyhedron_legend_labels: list[vtkTextActor] = []
        self._polyhedron_surface_cache: dict[str, pv.PolyData | None] = {}
        self.hidden_atom_indices: set[int] = set()
        self.hidden_bond_orbits: set[str] = set()
        self.hidden_bond_families: set[tuple[str, str]] = set()
        self.hidden_polyhedron_ids: set[str] = set()
        self.hidden_unit_ids: set[str] = set()
        self.hidden_block_ids: set[str] = set()
        self.hidden_connector_ids: set[str] = set()
        self.hidden_topology_family_ids: set[str] = set()
        self.selected_polyhedron_id: str | None = None
        self.selected_scene_object: tuple[str, object] | None = None
        self.edit_mode = False
        self.edit_target_kind: str | None = None
        self.edit_default_kind = "atom"
        self._held_edit_key: int | None = None
        self._held_axis_key: int | None = None
        self._axis_drag_position = None
        self.atom_orbit_colors: dict[str, str] = {}
        self.polyhedron_orbit_colors: dict[str, str] = {}
        self.shown_unit_ids: set[str] = set()
        self.shown_block_ids: set[str] = set()
        self.unit_colors: dict[str, str] = {}
        self.block_colors: dict[str, str] = {}
        self.comparison_highlight: ComparisonHighlight | None = None
        self._document: StructureDocument | None = None
        self.render_style = "publication"
        self.plotter.set_background("#ffffff")
        self.plotter.enable_parallel_projection()
        self.plotter.enable_anti_aliasing("ssaa")
        self.plotter.enable_depth_peeling(number_of_peels=8, occlusion_ratio=0.0)

    def set_render_style(self, style: str) -> None:
        self.render_style = style.lower()
        if self.render_style == "publication":
            self.plotter.set_background("#ffffff")
            self.plotter.enable_parallel_projection()
        elif self.render_style == "technical":
            self.plotter.set_background("#f4f6f8")
            self.plotter.enable_parallel_projection()
        else:
            self.plotter.set_background("#f7f9fc", top="#e9f0f7")
            self.plotter.disable_parallel_projection()

    def set_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = bool(enabled)
        if not self.edit_mode:
            self.edit_target_kind = None
            self._held_edit_key = None
        if hasattr(self, "edit_mode_changed"):
            self.edit_mode_changed.emit(self.edit_mode)

    def set_edit_target(self, kind: str | None) -> None:
        self.edit_target_kind = kind

    def clear_scene_selection(self) -> None:
        self.selected_scene_object = None
        self.selected_polyhedron_id = None
        if hasattr(self, "scene_selection_cleared"):
            self.scene_selection_cleared.emit()
        self.redraw(reset_camera=False)

    def eventFilter(self, watched, event) -> bool:
        if watched is not self.plotter:
            return super().eventFilter(watched, event)
        event_type = event.type()
        target_keys = {
            Qt.Key.Key_A: "atom",
            Qt.Key.Key_B: "bond",
            Qt.Key.Key_P: "polyhedron",
            Qt.Key.Key_U: "unit",
            Qt.Key.Key_R: "block",
        }
        axis_keys = {
            Qt.Key.Key_X: 0,
            Qt.Key.Key_Y: 1,
            Qt.Key.Key_Z: 2,
        }
        if event_type == QEvent.Type.KeyPress and not event.isAutoRepeat():
            if self.edit_mode and event.key() in target_keys:
                self._held_edit_key = int(event.key())
                self.set_edit_target(target_keys[event.key()])
                return True
            if event.key() in axis_keys:
                self._held_axis_key = int(event.key())
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.clear_scene_selection()
                return True
        if event_type == QEvent.Type.KeyRelease and not event.isAutoRepeat():
            handled = False
            if self.edit_mode and int(event.key()) == self._held_edit_key:
                self._held_edit_key = None
                self.set_edit_target(None)
                handled = True
            if int(event.key()) == self._held_axis_key:
                self._held_axis_key = None
                self._axis_drag_position = None
                handled = True
            if handled:
                return True
        if event_type == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.RightButton and self.edit_mode:
                self.edit_context_menu_requested.emit(event.globalPosition().toPoint())
                return True
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._held_axis_key in axis_keys
            ):
                self._axis_drag_position = event.position()
                return True
        if (
            event_type == QEvent.Type.MouseMove
            and self._axis_drag_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and self.structure is not None
        ):
            delta = event.position() - self._axis_drag_position
            self._axis_drag_position = event.position()
            axis_index = axis_keys.get(self._held_axis_key)
            if axis_index is None:
                return False
            camera = self.plotter.camera
            position, up = rotate_camera_about_axis(
                camera.position,
                camera.focal_point,
                camera.up,
                self.structure.cell.matrix[axis_index],
                (delta.x() - delta.y()) * 0.45,
            )
            camera.position = tuple(float(value) for value in position)
            camera.up = tuple(float(value) for value in up)
            self.plotter.render()
            return True
        if event_type == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self._axis_drag_position = None
        return super().eventFilter(watched, event)

    def set_data(
        self,
        structure: CrystalStructure,
        scene: SceneData,
        hierarchy: HierarchyReport,
        reset_camera: bool = True,
    ) -> None:
        if self.structure is not structure:
            self.reset_visibility(redraw=False)
            self.comparison_highlight = None
        if self.hierarchy is not hierarchy:
            self._polyhedron_surface_cache.clear()
        self.structure = structure
        self.scene = scene
        self.hierarchy = hierarchy
        self.redraw(reset_camera=reset_camera)

    def set_document(
        self,
        document: StructureDocument,
        reset_camera: bool = True,
        scene: SceneData | None = None,
    ) -> None:
        if getattr(self, "_document", None) is not document:
            self.comparison_highlight = None
        self._document = document
        scene = scene if scene is not None else document.scene_data()
        self.set_data(document.structure, scene, document.hierarchy, reset_camera)
        self.apply_visual_state(document.visual, redraw=True)

    def apply_visual_state(
        self,
        state: VisualizationState,
        redraw: bool = True,
    ) -> None:
        self.level = HierarchyLevel(state.level)
        self.hidden_atom_indices = set(state.hidden_atom_indices)
        self.hidden_bond_orbits = set(state.hidden_bond_orbits)
        self.hidden_bond_families = set(state.hidden_bond_families)
        self.hidden_polyhedron_ids = set(state.hidden_polyhedron_ids)
        self.hidden_unit_ids = set(state.hidden_unit_ids)
        self.hidden_block_ids = set(state.hidden_block_ids)
        self.hidden_connector_ids = set(state.hidden_connector_ids)
        self.hidden_topology_family_ids = set(state.hidden_topology_family_ids)
        self.atom_orbit_colors = dict(state.atom_orbit_colors)
        self.polyhedron_orbit_colors = dict(state.polyhedron_orbit_colors)
        self.shown_unit_ids = set(state.shown_unit_ids)
        self.shown_block_ids = set(state.shown_block_ids)
        self.unit_colors = dict(state.unit_colors)
        self.block_colors = dict(state.block_colors)
        if redraw:
            self.redraw(reset_camera=False)

    def set_comparison_highlight(
        self,
        highlight: ComparisonHighlight | None,
    ) -> None:
        """Apply temporary comparison colors without changing visual state."""
        self.comparison_highlight = highlight
        self.redraw(reset_camera=False)

    def _structure_center(self) -> np.ndarray:
        if self.structure is None or not len(self.structure.cartesian_positions):
            return np.zeros(3, dtype=float)
        return np.mean(np.asarray(self.structure.cartesian_positions, dtype=float), axis=0)

    def camera_state(self) -> CameraState:
        center = self._structure_center()
        camera = self.plotter.camera
        return CameraState(
            position=tuple(float(value) for value in np.asarray(camera.position) - center),
            focal_offset=tuple(float(value) for value in np.asarray(camera.focal_point) - center),
            view_up=tuple(float(value) for value in camera.up),
            parallel_scale=float(camera.parallel_scale),
            view_angle=float(camera.view_angle),
            parallel_projection=bool(camera.parallel_projection),
        )

    def apply_camera_state(self, state: CameraState) -> None:
        center = self._structure_center()
        camera = self.plotter.camera
        camera.position = tuple(float(value) for value in center + np.asarray(state.position))
        camera.focal_point = tuple(float(value) for value in center + np.asarray(state.focal_offset))
        camera.up = state.view_up
        camera.parallel_scale = state.parallel_scale
        camera.view_angle = state.view_angle
        camera.parallel_projection = state.parallel_projection
        self.plotter.render()

    def reset_visibility(self, redraw: bool = True) -> None:
        self.hidden_atom_indices.clear()
        self.hidden_bond_orbits.clear()
        self.hidden_bond_families.clear()
        self.hidden_polyhedron_ids.clear()
        self.hidden_unit_ids.clear()
        self.hidden_block_ids.clear()
        self.hidden_connector_ids.clear()
        self.hidden_topology_family_ids.clear()
        self.shown_unit_ids.clear()
        self.shown_block_ids.clear()
        if redraw:
            self.redraw(reset_camera=False)

    def hide_object(self, kind: str, object_id, redraw: bool = True) -> None:
        if kind == "atom":
            self.hidden_atom_indices.add(int(object_id))
        elif kind == "bond":
            self.hidden_bond_families.add(tuple(object_id))
        elif kind == "polyhedron":
            self.hidden_polyhedron_ids.add(str(object_id))
            if self.selected_polyhedron_id == str(object_id):
                self.selected_polyhedron_id = None
        elif kind == "unit":
            self.hidden_unit_ids.add(str(object_id))
        elif kind == "block":
            self.hidden_block_ids.add(str(object_id))
        elif kind == "connector":
            self.hidden_connector_ids.add(str(object_id))
        if self.selected_scene_object == (kind, object_id):
            self.selected_scene_object = None
        if redraw:
            self.redraw(reset_camera=False)

    def isolate_object(self, kind: str, object_id) -> None:
        self.reset_visibility(redraw=False)
        if kind == "atom":
            keep = {int(object_id)}
            self.hidden_atom_indices = set(range(len(self.structure.sites))) - keep
            self.hidden_polyhedron_ids = {item.id for item in self.hierarchy.polyhedra}
        elif kind == "polyhedron":
            item = next(value for value in self.hierarchy.polyhedra if value.id == object_id)
            keep_atoms = {item.center_index, *(ligand.site_index for ligand in item.ligands)}
            self.hidden_atom_indices = set(range(len(self.structure.sites))) - keep_atoms
            self.hidden_polyhedron_ids = {value.id for value in self.hierarchy.polyhedra if value.id != object_id}
        elif kind == "bond":
            selected_family = tuple(sorted(str(value) for value in object_id))
            if self._document is not None:
                families = set(bond_families(self._document))
            else:
                families = {
                    tuple(
                        sorted(
                            (
                                self.scene.atoms[bond.first].site.element,
                                self.scene.atoms[bond.second].site.element,
                            )
                        )
                    )
                    for bond in self.scene.bonds
                }
            self.hidden_bond_families = families - {selected_family}
        elif kind == "unit":
            item = next(value for value in self.hierarchy.structural_units if value.id == object_id)
            self.hidden_atom_indices = set(range(len(self.structure.sites))) - set(item.atom_indices)
            self.hidden_polyhedron_ids = {
                value.id for value in self.hierarchy.polyhedra if value.id not in item.polyhedron_ids
            }
            self.hidden_unit_ids = {
                value.id for value in self.hierarchy.structural_units if value.id != object_id
            }
            self.shown_unit_ids = {str(object_id)}
        elif kind == "block":
            item = next(value for value in self.hierarchy.blocks if value.id == object_id)
            self.hidden_atom_indices = set(range(len(self.structure.sites))) - set(item.atom_indices)
            self.hidden_block_ids = {value.id for value in self.hierarchy.blocks if value.id != object_id}
            self.hidden_polyhedron_ids = {
                value.id for value in self.hierarchy.polyhedra if value.id not in item.polyhedron_ids
            }
            self.shown_block_ids = {str(object_id)}
        elif kind == "connector":
            item = next(value for value in self.hierarchy.connectors if value.id == object_id)
            self.hidden_connector_ids = {
                value.id for value in self.hierarchy.connectors if value.id != object_id
            }
            self.hidden_block_ids = {
                value.id
                for value in self.hierarchy.blocks
                if value.id not in {item.first_block, item.second_block}
            }
        self.redraw(reset_camera=True)

    def _polyhedron_visible(self, polyhedron) -> bool:
        if polyhedron.id in self.hidden_polyhedron_ids:
            return False
        block_id = self._polyhedron_block_map().get(polyhedron.id)
        unit_id = self._polyhedron_unit_map().get(polyhedron.id)
        return block_id not in self.hidden_block_ids and unit_id not in self.hidden_unit_ids

    def set_level(self, level: HierarchyLevel) -> None:
        previous = self.level
        self.level = HierarchyLevel(level)
        crosses_topology = (previous == HierarchyLevel.TOPOLOGY) != (
            self.level == HierarchyLevel.TOPOLOGY
        )
        self.redraw(reset_camera=crosses_topology)

    def redraw(self, reset_camera: bool = False) -> None:
        self._remove_polyhedron_legend()
        self.plotter.clear()
        if not self.structure or not self.scene or not self.hierarchy:
            self.plotter.add_text("Open a CIF to begin", position="upper_left", color="#93a4b7", font_size=11)
            return
        if self.show_cell:
            self._draw_cell()
        if self.level == HierarchyLevel.SITES:
            self._draw_mixed_structure()
        elif self.level == HierarchyLevel.ATOMS:
            if self.show_bonds:
                self._draw_bonds()
            if self.show_atoms:
                self._draw_atoms()
        elif self.level == HierarchyLevel.BONDS:
            if self.show_bonds:
                self._draw_bonds()
            if self.show_atoms:
                self._draw_atoms(radius_factor=0.58)
        elif self.level == HierarchyLevel.POLYHEDRA:
            if self.show_polyhedra:
                self._draw_polyhedra(color_mode=self._resolved_color_mode("element"))
                if self.show_polyhedron_spokes:
                    self._draw_polyhedron_spokes()
            if self.show_centers:
                self._draw_polyhedron_centers()
            if self.show_atoms:
                self._draw_polyhedron_vertices()
        elif self.level == HierarchyLevel.STRUCTURAL_UNITS:
            if self.show_polyhedra:
                self._draw_structural_units()
        elif self.level == HierarchyLevel.RIGID_BLOCKS:
            if self.show_polyhedra:
                self._draw_rigid_blocks()
            # In the mechanical representation only ligand oxygens remain:
            # they are the candidate shared vertices/pivots between blocks.
            self._draw_polyhedron_vertices(radius=0.125)
            if self.show_connectors:
                self._draw_connectors()
            if self._resolved_color_mode("rigidity") == "rigidity":
                self._draw_rigidity_scale()
        elif self.level == HierarchyLevel.FRAMEWORK:
            self._draw_skeleton()
        else:
            self._draw_topology()
        if self.show_labels and self.level in {
            HierarchyLevel.ATOMS,
            HierarchyLevel.SITES,
            HierarchyLevel.BONDS,
            HierarchyLevel.POLYHEDRA,
            HierarchyLevel.STRUCTURAL_UNITS,
        }:
            self._draw_atom_labels()
        if self.show_legend:
            self._draw_legend()
        if self.show_axes:
            axes_actor = self.plotter.add_axes(
                line_width=5,
                x_color="#e74c3c",
                y_color="#20b96b",
                z_color="#315bd6",
                xlabel="a",
                ylabel="b",
                zlabel="c",
                cone_radius=0.46,
                shaft_length=0.72,
                tip_length=0.28,
                label_size=(0.18, 0.08),
                ambient=0.72,
                viewport=(0.01, 0.01, self.axes_size, self.axes_size),
            )
            # The labels remain attached to the rotating triad.  Different
            # radial offsets keep projected labels apart in near-axial views.
            axes_actor.SetNormalizedLabelPosition(1.36, 1.50, 1.64)
        else:
            self.plotter.hide_axes()
        self._enable_polyhedron_picking()
        if reset_camera:
            self.plotter.reset_camera()
            if self.level == HierarchyLevel.TOPOLOGY:
                self.plotter.view_xy()
            else:
                self.plotter.camera.zoom(1.22)
        self.plotter.render()

    def _enable_polyhedron_picking(self) -> None:
        if not hasattr(self.plotter, "enable_element_picking"):
            return
        try:
            if hasattr(self.plotter, "disable_picking"):
                self.plotter.disable_picking()
            self.plotter.enable_element_picking(
                callback=self._scene_cells_picked,
                mode="cell",
                left_clicking=True,
                show=False,
                show_message=False,
            )
        except Exception:
            # Picking is an optional interaction; rendering must remain usable
            # on backends that do not expose hardware cell selection.
            return

    def _polyhedron_cells_picked(self, picked) -> None:
        identifier = picked_polyhedron_id(picked, self.hierarchy)
        if identifier is None or identifier == self.selected_polyhedron_id:
            return
        self.selected_polyhedron_id = identifier
        self.object_picked.emit(identifier)
        self.redraw(reset_camera=False)

    def _scene_cells_picked(self, picked) -> None:
        if hasattr(self, "edit_mode") and not self.edit_mode:
            return
        requested = self.edit_target_kind or getattr(self, "edit_default_kind", None) or {
            HierarchyLevel.ATOMS: "atom",
            HierarchyLevel.BONDS: "bond",
            HierarchyLevel.POLYHEDRA: "polyhedron",
            HierarchyLevel.STRUCTURAL_UNITS: "unit",
            HierarchyLevel.RIGID_BLOCKS: "block",
        }.get(self.level, "polyhedron")
        resolved = picked_scene_object(
            picked, self.hierarchy, self.scene, requested
        )
        if resolved is None:
            return
        self.selected_scene_object = resolved
        kind, identifier = resolved
        if kind == "polyhedron":
            self.selected_polyhedron_id = str(identifier)
            self.object_picked.emit(str(identifier))
        self.scene_object_picked.emit(kind, identifier)
        self.redraw(reset_camera=False)

    def _draw_legend(self) -> None:
        if self.level == HierarchyLevel.SITES:
            (
                selected_units,
                selected_blocks,
                aggregate_polyhedra,
                aggregate_atoms,
                boundary_atoms,
                visible_polyhedra,
            ) = StructureViewer._mixed_structure_state(self)
            entries_by_name: dict[str, str] = {}
            if self.show_atoms:
                excluded_atoms = aggregate_atoms - boundary_atoms
                visible_sites = (
                    atom.site
                    for atom in self.scene.atoms
                    if atom.site_index not in self.hidden_atom_indices
                    and atom.site_index not in excluded_atoms
                )
                for label in atom_legend_labels(
                    visible_sites,
                    split_occupancies=self.split_mixed_occupancies,
                    show_vacancies=self.show_vacancy_sectors,
                ):
                    entries_by_name[label] = (
                        VACANCY_COLOR
                        if label == "Vacancy"
                        else ELEMENT_COLORS.get(label, "#aab4c0")
                    )
            if self.show_polyhedra:
                custom_colors = getattr(self, "polyhedron_orbit_colors", {})
                for polyhedron in visible_polyhedra:
                    center_site = self.structure.sites[polyhedron.center_index]
                    orbit = site_orbit_key(center_site.label)
                    coordination = str(polyhedron.coordination_number).translate(
                        str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
                    )
                    name = (
                        f"{polyhedron.center_element}{polyhedron.ligand_element}"
                        f"{coordination} polyhedron"
                    )
                    entries_by_name[name] = custom_colors.get(
                        orbit,
                        POLYHEDRON_COLORS.get(
                            polyhedron.center_element,
                            site_colour(center_site),
                        ),
                    )
                unit_colors = StructureViewer._unit_colors(self)
                for unit in selected_units:
                    entries_by_name[
                        StructureViewer._aggregate_position_name(self, unit)
                    ] = unit_colors[unit.id]
                block_colors = StructureViewer._block_colors(self)
                for block in selected_blocks:
                    entries_by_name[
                        StructureViewer._aggregate_position_name(self, block)
                    ] = block_colors[block.id]
            entries = sorted(entries_by_name.items())
        elif self.level in {HierarchyLevel.ATOMS, HierarchyLevel.BONDS}:
            visible_sites = (
                atom.site
                for atom in self.scene.atoms
                if atom.site_index not in self.hidden_atom_indices
            )
            labels = atom_legend_labels(
                visible_sites,
                split_occupancies=self.split_mixed_occupancies,
                show_vacancies=self.show_vacancy_sectors,
            )
            entries = [
                (
                    label,
                    VACANCY_COLOR if label == "Vacancy" else ELEMENT_COLORS.get(label, "#aab4c0"),
                )
                for label in labels
            ]
        elif self.level == HierarchyLevel.POLYHEDRA:
            self._draw_polyhedron_3d_legend()
            return
        elif self.level == HierarchyLevel.STRUCTURAL_UNITS:
            colors = self._unit_colors()
            entries_by_type = {
                self._unit_name(unit): colors[unit.id]
                for unit in self.hierarchy.structural_units
                if unit.id not in self.hidden_unit_ids
            }
            entries = sorted(entries_by_type.items())
        elif self.level in {HierarchyLevel.RIGID_BLOCKS, HierarchyLevel.FRAMEWORK}:
            if self.level == HierarchyLevel.RIGID_BLOCKS and self._resolved_color_mode("rigidity") == "rigidity":
                # The scalar bar already is the legend in rigidity mode.
                return
            colors = self._block_colors()
            entries_by_name = {
                block.classification: colors[block.id]
                for block in self.hierarchy.blocks
                if block.id not in self.hidden_block_ids
            }
            entries = sorted(entries_by_name.items())
        else:
            entries = [("Rigid block", "#20242a"), ("Shared-site connection", "#697586")]
        if not entries:
            return
        self.plotter.add_legend(
            entries,
            bcolor="#ffffff",
            border=False,
            face="circle",
            loc="lower right",
            size=(0.16, min(0.038 * len(entries) + 0.025, 0.20)),
            background_opacity=0.76,
        )

    @staticmethod
    def _subscript_formula(text: str) -> str:
        return text.translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))

    @staticmethod
    def _polyhedron_legend_face(coordination: int) -> pv.PolyData:
        sides = 3 if coordination <= 4 else 4 if coordination <= 6 else min(coordination, 8)
        return pv.Polygon(n_sides=sides, radius=1.0, fill=True)

    @staticmethod
    def _actor_for_mesh(
        mesh: pv.PolyData,
        color: str,
        opacity: float = 1.0,
        edges: bool = False,
    ) -> vtkActor:
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(mesh)
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(pv.Color(color).float_rgb)
        actor.GetProperty().SetOpacity(opacity)
        actor.GetProperty().SetInterpolationToPhong()
        if edges:
            actor.GetProperty().EdgeVisibilityOn()
            actor.GetProperty().SetEdgeColor(pv.Color(_shade(color, 0.35)).float_rgb)
            actor.GetProperty().SetLineWidth(2.0)
        return actor

    @staticmethod
    def _canonical_polyhedron(coordination: int) -> np.ndarray:
        if coordination <= 4:
            return np.asarray(((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)), dtype=float)
        if coordination <= 6:
            return np.asarray(((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)), dtype=float)
        return np.asarray(
            [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)],
            dtype=float,
        )

    def _draw_polyhedron_3d_legend(self) -> None:
        entries = {}
        for polyhedron in self.hierarchy.polyhedra:
            if self._polyhedron_visible(polyhedron):
                center_site = _polyhedron_center_site(self.structure, polyhedron)
                entries[polyhedron.type_name] = (
                    POLYHEDRON_COLORS.get(
                        polyhedron.center_element,
                        site_colour(center_site),
                    ),
                    polyhedron.coordination_number,
                    polyhedron.ligand_element,
                )
        if not entries or self.plotter.iren is None:
            return
        ordered_entries = sorted(entries.items())
        row_height = min(0.085, 0.25 / max(len(ordered_entries), 1))
        for row, (name, (color, coordination, ligand)) in enumerate(ordered_entries):
            assembly = vtkAssembly()
            vertices = self._canonical_polyhedron(coordination)
            surface = (
                pv.PolyData(vertices)
                .delaunay_3d()
                .extract_surface(algorithm="dataset_surface")
                .triangulate()
            )
            face_actor = self._actor_for_mesh(surface, color, opacity=0.48, edges=True)
            face_actor.SetScale(0.72)
            assembly.AddPart(face_actor)
            center_actor = self._actor_for_mesh(pv.Sphere(radius=0.30), color)
            assembly.AddPart(center_actor)
            ligand_color = ELEMENT_COLORS.get(ligand, "#f52218")
            for vertex in vertices:
                vertex_actor = self._actor_for_mesh(pv.Sphere(radius=0.115), ligand_color)
                vertex_actor.SetPosition(*(vertex * 0.72))
                assembly.AddPart(vertex_actor)

            bottom = 0.035 + row * row_height
            widget = vtkOrientationMarkerWidget()
            widget.SetOrientationMarker(assembly)
            widget.SetInteractor(self.plotter.iren.interactor)
            widget.SetCurrentRenderer(self.plotter.renderer)
            widget.SetViewport(0.745, bottom, 0.805, bottom + row_height * 0.92)
            widget.SetEnabled(1)
            widget.SetInteractive(0)
            self._polyhedron_legend_widgets.append(widget)

            # A fixed 2-D caption cannot rotate away from its icon.  Only the
            # actual miniature polyhedron follows the main camera.
            label = vtkTextActor()
            label.SetInput(self._subscript_formula(name))
            label.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            label.SetPosition(0.812, bottom + row_height * 0.30)
            label.GetTextProperty().SetColor(pv.Color(_shade(color, 0.72)).float_rgb)
            label.GetTextProperty().SetFontSize(13)
            label.GetTextProperty().BoldOn()
            label.GetTextProperty().SetBackgroundColor(1.0, 1.0, 1.0)
            label.GetTextProperty().SetBackgroundOpacity(0.68)
            self.plotter.renderer.AddActor2D(label)
            self._polyhedron_legend_labels.append(label)

    def _remove_polyhedron_legend(self) -> None:
        for widget in self._polyhedron_legend_widgets:
            widget.SetEnabled(0)
            widget.SetInteractor(None)
        self._polyhedron_legend_widgets.clear()
        for label in self._polyhedron_legend_labels:
            self.plotter.renderer.RemoveActor2D(label)
        self._polyhedron_legend_labels.clear()

    def _draw_rigidity_scale(self) -> None:
        lower, upper = self._rigidity_limits()
        mapper = pv.DataSetMapper()
        lookup_table = pv.LookupTable(scalar_range=(lower, upper))
        lookup_table.apply_cmap("RdYlGn", n_values=256)
        mapper.lookup_table = lookup_table
        self.plotter.add_scalar_bar(
            "Relative rigidity prior" if self.adaptive_rigidity_scale else "Rigidity prior",
            mapper=mapper,
            n_labels=4,
            fmt="%.3f",
            color="#263342",
            position_x=0.62,
            position_y=0.045,
            width=0.24,
            height=0.035,
            vertical=False,
            background_color="#ffffff",
            fill=True,
            title_font_size=11,
            label_font_size=9,
            outline=False,
        )

    def _resolved_color_mode(self, default: str) -> str:
        return {
            "automatic": default,
            "element": "element",
            "structural_unit": "unit",
            "block": "block",
            "rigidity": "rigidity",
            "distortion": "distortion",
        }.get(self.color_by, default)

    def _draw_cell(self) -> None:
        color = "#4b5563" if self.render_style == "publication" else "#8d99a8"
        opacity = 0.56 if self.render_style == "publication" else 0.64
        a, b, c = self.structure.cell.matrix
        base_corners = np.asarray(
            ([0, 0, 0], a, a + b, b, c, a + c, a + b + c, b + c),
            dtype=float,
        )
        drawn_edges: set[tuple[tuple[float, ...], tuple[float, ...]]] = set()
        translations = (
            self._translations()
            if getattr(self, "show_periodic_cell_grid", False)
            else (np.zeros(3, dtype=float),)
        )
        for translation in translations:
            corners = base_corners + translation
            for first, second in self.scene.cell_edges:
                start = corners[first]
                end = corners[second]
                key = tuple(sorted((tuple(np.round(start, 6)), tuple(np.round(end, 6)))))
                if key in drawn_edges:
                    continue
                drawn_edges.add(key)
                self.plotter.add_mesh(
                    pv.Line(start, end),
                    color=color,
                    line_width=self.cell_line_width,
                    opacity=opacity,
                )
        if self.show_cell_dimensions:
            self.plotter.add_point_labels(
                [a / 2.0, b / 2.0, c / 2.0],
                [
                    f"a = {self.structure.cell.a:.3f} Å",
                    f"b = {self.structure.cell.b:.3f} Å",
                    f"c = {self.structure.cell.c:.3f} Å",
                ],
                point_size=0,
                font_size=9,
                text_color="#5b6675",
                shape_opacity=0.0,
                always_visible=True,
            )

    def _draw_atoms(
        self,
        radius_factor: float = 1.0,
        show_bonds: bool = False,
        ligands_only: bool = False,
        *,
        comparison_only: bool = False,
        excluded_site_indices: Collection[int] = (),
    ) -> None:
        if show_bonds:
            self._draw_bonds()
        items: list[tuple[str, SphereInstance]] = []
        occupancy_items: list[OccupancySphereInstance] = []
        outline_items: list[SphereInstance] = []
        selected_items: list[SphereInstance] = []
        for display_index, atom in enumerate(self.scene.atoms):
            if (
                atom.site_index in self.hidden_atom_indices
                or atom.site_index in excluded_site_indices
            ):
                continue
            if ligands_only and site_role(atom.site) is not SiteRole.ANION:
                continue
            radius = _site_display_radius(atom.site) * radius_factor * self.atom_scale
            comparison_color = _comparison_atom_color(
                self.comparison_highlight,
                atom.site_index,
            )
            outlined = _comparison_atom_outlined(
                self.comparison_highlight,
                atom.site_index,
            )
            if comparison_only and comparison_color is None and not outlined:
                continue
            manual_color = getattr(self, "atom_orbit_colors", {}).get(
                site_orbit_key(atom.site.label)
            )
            color = comparison_color or manual_color or site_colour(atom.site)
            if outlined:
                outline_items.append(
                    SphereInstance(
                        atom.cartesian,
                        radius * 1.12,
                        display_index,
                    )
                )
            if getattr(self, "selected_scene_object", None) == (
                "atom",
                atom.site_index,
            ):
                selected_items.append(
                    SphereInstance(atom.cartesian, radius * 1.16, display_index)
                )
            if (
                comparison_color is None
                and manual_color is None
                and self.split_mixed_occupancies
                and atom.site.is_disordered
            ):
                sectors = [
                    (
                        _rgb_tuple(ELEMENT_COLORS.get(component.element, "#aab4c0")),
                        component.occupancy,
                    )
                    for component in atom.site.components
                    if component.occupancy > 1e-8
                ]
                if self.show_vacancy_sectors and atom.site.vacancy_fraction > 1e-8:
                    sectors.append((_rgb_tuple(VACANCY_COLOR), atom.site.vacancy_fraction))
                occupancy_items.append(
                    OccupancySphereInstance(
                        atom.cartesian,
                        radius,
                        display_index,
                        tuple(sectors),
                    )
                )
                continue
            items.append(
                (
                    color,
                    SphereInstance(atom.cartesian, radius, display_index),
                )
            )
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        for color, instances in group_spheres_by_material(items).items():
            batch = build_sphere_batch(instances, detail)
            if batch is None:
                continue
            _tag_pick_kind(batch, PICK_ATOM)
            self.plotter.add_mesh(
                batch,
                color=color,
                smooth_shading=True,
                interpolation="phong",
                ambient=0.08,
                diffuse=0.80,
                specular=0.58,
                specular_power=30,
            )
        occupancy_batch = build_occupancy_sphere_batch(occupancy_items, detail)
        if occupancy_batch is not None:
            _tag_pick_kind(occupancy_batch, PICK_ATOM)
            self.plotter.add_mesh(
                occupancy_batch,
                scalars="occupancy_rgb",
                rgb=True,
                preference="cell",
                smooth_shading=True,
                interpolation="phong",
                ambient=0.08,
                diffuse=0.80,
                specular=0.58,
                specular_power=30,
            )
        if outline_items:
            outline_batch = build_sphere_batch(outline_items, detail)
            if outline_batch is not None:
                self.plotter.add_mesh(
                    outline_batch,
                    color=OUTLINE_RED,
                    style="wireframe",
                    line_width=2.0,
                    opacity=1.0,
                    render_lines_as_tubes=True,
                    ambient=0.34,
                    specular=0.12,
                )
        if selected_items:
            selected_batch = build_sphere_batch(selected_items, detail)
            if selected_batch is not None:
                _tag_pick_kind(selected_batch, PICK_ATOM)
                self.plotter.add_mesh(
                    selected_batch,
                    color="#087dca",
                    style="wireframe",
                    line_width=2.5,
                    opacity=1.0,
                    render_lines_as_tubes=True,
                )

    def _mixed_structure_state(self):
        selected_blocks = tuple(
            block for block in self.hierarchy.blocks if block.id in self.shown_block_ids
        )
        block_polyhedra = {
            polyhedron_id
            for block in selected_blocks
            for polyhedron_id in block.polyhedron_ids
        }
        selected_units = tuple(
            unit
            for unit in self.hierarchy.structural_units
            if unit.id in self.shown_unit_ids
            and not block_polyhedra.intersection(unit.polyhedron_ids)
        )
        aggregate_polyhedra = block_polyhedra | {
            polyhedron_id
            for unit in selected_units
            for polyhedron_id in unit.polyhedron_ids
        }
        aggregate_atoms = {
            atom_index
            for aggregate in (*selected_units, *selected_blocks)
            for atom_index in aggregate.atom_indices
        }
        aggregate_polyhedra.update(
            polyhedron.id
            for polyhedron in self.hierarchy.polyhedra
            if polyhedron.center_index in aggregate_atoms
        )
        hidden_by_parent = {
            polyhedron_id
            for block in self.hierarchy.blocks
            if block.id in self.hidden_block_ids
            for polyhedron_id in block.polyhedron_ids
        } | {
            polyhedron_id
            for unit in self.hierarchy.structural_units
            if unit.id in self.hidden_unit_ids
            for polyhedron_id in unit.polyhedron_ids
        }
        visible_polyhedra = tuple(
            polyhedron
            for polyhedron in self.hierarchy.polyhedra
            if polyhedron.id not in aggregate_polyhedra
            and polyhedron.id not in self.hidden_polyhedron_ids
            and polyhedron.id not in hidden_by_parent
        )
        boundary_atoms = aggregate_atoms.intersection(
            ligand.site_index
            for polyhedron in visible_polyhedra
            for ligand in getattr(polyhedron, "ligands", ())
        )
        return (
            selected_units,
            selected_blocks,
            aggregate_polyhedra,
            aggregate_atoms,
            boundary_atoms,
            visible_polyhedra,
        )

    def _aggregate_position_name(self, aggregate) -> str:
        polyhedra = {item.id: item for item in self.hierarchy.polyhedra}
        labels = tuple(
            dict.fromkeys(
                site_orbit_key(
                    self.structure.sites[polyhedra[identifier].center_index].label
                )
                for identifier in aggregate.polyhedron_ids
                if identifier in polyhedra
            )
        )
        return (
            f"{aggregate.classification} · {'/'.join(labels)}"
            if labels
            else aggregate.classification
        )

    def _draw_mixed_structure(self) -> None:
        """Compose atoms, polyhedra, units and blocks in one non-overlapping scene."""
        (
            selected_units,
            selected_blocks,
            aggregate_polyhedra,
            aggregate_atoms,
            boundary_atoms,
            _visible_polyhedra,
        ) = StructureViewer._mixed_structure_state(self)
        original_polyhedra = set(self.hidden_polyhedron_ids)
        original_units = set(self.hidden_unit_ids)
        original_blocks = set(self.hidden_block_ids)
        try:
            if self.show_bonds:
                self._draw_bonds(excluded_site_indices=aggregate_atoms)
            if self.show_polyhedra:
                self.hidden_polyhedron_ids = original_polyhedra | aggregate_polyhedra
                self._draw_polyhedra(color_mode=self._resolved_color_mode("element"))
            if self.show_atoms:
                self._draw_atoms(excluded_site_indices=aggregate_atoms)
                if boundary_atoms:
                    self._draw_polyhedron_vertices(
                        site_indices=boundary_atoms,
                        polyhedron_ids={
                            polyhedron.id for polyhedron in _visible_polyhedra
                        },
                    )
            if selected_units and self.show_polyhedra:
                self.hidden_polyhedron_ids = original_polyhedra
                self.hidden_unit_ids = {
                    unit.id
                    for unit in self.hierarchy.structural_units
                    if unit not in selected_units
                }
                self.hidden_block_ids = set()
                self._draw_structural_units()
            if selected_blocks and self.show_polyhedra:
                self.hidden_polyhedron_ids = original_polyhedra
                self.hidden_unit_ids = set()
                self.hidden_block_ids = {
                    block.id
                    for block in self.hierarchy.blocks
                    if block not in selected_blocks
                }
                self._draw_rigid_blocks()
        finally:
            self.hidden_polyhedron_ids = original_polyhedra
            self.hidden_unit_ids = original_units
            self.hidden_block_ids = original_blocks

    def _draw_bonds(self, *, excluded_site_indices: Collection[int] = ()) -> None:
        gradient_instances: list[GradientCylinderInstance] = []
        groups: dict[str, list[CylinderInstance]] = {}
        selected_instances: list[CylinderInstance] = []
        for bond_index, bond in enumerate(self.scene.bonds):
            first_atom = self.scene.atoms[bond.first]
            second_atom = self.scene.atoms[bond.second]
            first_key = site_orbit_key(first_atom.site.label)
            second_key = site_orbit_key(second_atom.site.label)
            if (
                first_atom.site_index in excluded_site_indices
                or second_atom.site_index in excluded_site_indices
            ):
                continue
            hidden_bond_orbits = getattr(self, "hidden_bond_orbits", set())
            if first_key in hidden_bond_orbits or second_key in hidden_bond_orbits:
                continue
            family = tuple(sorted((first_atom.site.element, second_atom.site.element)))
            if family in getattr(self, "hidden_bond_families", set()):
                continue
            first = np.asarray(first_atom.cartesian)
            second = np.asarray(second_atom.cartesian)
            if getattr(self, "selected_scene_object", None) == ("bond", family):
                selected_instances.append(
                    CylinderInstance(
                        tuple(first), tuple(second), self.bond_radius * 1.35, bond_index
                    )
                )
            atom_colors = getattr(self, "atom_orbit_colors", {})
            first_color = atom_colors.get(first_key, site_colour(first_atom.site))
            second_color = atom_colors.get(second_key, site_colour(second_atom.site))
            if self.bond_style == "bicolor":
                gradient_instances.append(
                    GradientCylinderInstance(
                        tuple(float(value) for value in first),
                        tuple(float(value) for value in second),
                        self.bond_radius,
                        bond_index,
                        _rgb_tuple(_shade(first_color, 0.82)),
                        _rgb_tuple(_shade(second_color, 0.82)),
                    )
                )
            else:
                groups.setdefault("#7f8791", []).append(
                    CylinderInstance(tuple(first), tuple(second), self.bond_radius, bond_index)
                )
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        gradient_batch = build_gradient_cylinder_batch(gradient_instances, detail)
        if gradient_batch is not None:
            _tag_pick_kind(gradient_batch, PICK_BOND)
            self.plotter.add_mesh(
                gradient_batch,
                scalars="bond_rgb",
                rgb=True,
                preference="point",
                opacity=0.96,
                smooth_shading=True,
                ambient=0.22,
                specular=0.24,
                specular_power=16,
            )
        for color, instances in groups.items():
            batch = build_cylinder_batch(instances, detail)
            if batch is None:
                continue
            _tag_pick_kind(batch, PICK_BOND)
            self.plotter.add_mesh(
                batch,
                color=color,
                opacity=0.96,
                smooth_shading=True,
                ambient=0.22,
                specular=0.24,
                specular_power=16,
            )
        selected_batch = build_cylinder_batch(selected_instances, detail)
        if selected_batch is not None:
            _tag_pick_kind(selected_batch, PICK_BOND)
            self.plotter.add_mesh(
                selected_batch,
                color="#087dca",
                opacity=0.72,
                smooth_shading=True,
                ambient=0.28,
                specular=0.20,
            )

    def _block_colors(self) -> dict[str, str]:
        return {
            block.id: getattr(self, "block_colors", {}).get(
                block.id,
                BLOCK_TYPE_COLORS.get(
                    block.classification, BLOCK_COLORS[index % len(BLOCK_COLORS)]
                ),
            )
            for index, block in enumerate(self.hierarchy.blocks)
        }

    def _translations(self) -> tuple[np.ndarray, ...]:
        return tuple(np.asarray(value, dtype=float) for value in self.scene.translations)

    def _translations_for_site(self, site_index: int) -> tuple[np.ndarray, ...]:
        """Return only copies whose crystallographic centre is inside the view bounds."""
        if not hasattr(self.scene, "fractional_translations") or not hasattr(
            self.scene, "bounds"
        ):
            return self._translations()
        fractional = self.structure.sites[site_index].fractional
        kept = []
        for image, cartesian in zip(
            self.scene.fractional_translations,
            self.scene.translations,
            strict=True,
        ):
            position = tuple(fractional[axis] + image[axis] for axis in range(3))
            if all(
                self.scene.bounds[axis][0] - 1e-8
                <= position[axis]
                < self.scene.bounds[axis][1] - 1e-8
                for axis in range(3)
            ):
                kept.append(np.asarray(cartesian, dtype=float))
        return tuple(kept)

    def _aggregate_translations(
        self,
        polyhedron_ids: tuple[str, ...],
    ) -> tuple[np.ndarray, ...]:
        """Clip an aggregate using one crystallographic source centre."""
        if not hasattr(self.scene, "fractional_translations") or not hasattr(
            self.scene, "bounds"
        ):
            return self._translations()
        wanted = set(polyhedron_ids)
        center_index = next(
            (
                polyhedron.center_index
                for polyhedron in self.hierarchy.polyhedra
                if polyhedron.id in wanted
            ),
            None,
        )
        if center_index is None:
            return self._translations()
        return StructureViewer._translations_for_site(self, center_index)

    def _base_polyhedron_surface(self, polyhedron) -> pv.PolyData | None:
        if polyhedron.id in self._polyhedron_surface_cache:
            return self._polyhedron_surface_cache[polyhedron.id]
        points = np.asarray(polyhedron.vertex_coordinates, dtype=float)
        if len(points) < 3:
            self._polyhedron_surface_cache[polyhedron.id] = None
            return None
        try:
            if len(points) == 3:
                surface = pv.PolyData(points, faces=np.asarray([3, 0, 1, 2]))
            else:
                surface = (
                    pv.PolyData(points)
                    .delaunay_3d()
                    .extract_surface(algorithm="dataset_surface")
                )
            surface = surface.triangulate().compute_normals(
                cell_normals=True,
                point_normals=False,
                auto_orient_normals=True,
            )
        except Exception:
            surface = None
        self._polyhedron_surface_cache[polyhedron.id] = surface
        return surface

    @staticmethod
    def _base_edge_surface(surface: pv.PolyData, radius: float, detail) -> pv.PolyData | None:
        try:
            return surface.extract_all_edges().tube(
                radius=radius,
                n_sides={"high": 10, "medium": 8, "low": 6}[detail.value],
            )
        except Exception:
            return None

    def _polyhedron_block_map(self) -> dict[str, str]:
        return {
            polyhedron_id: block.id
            for block in self.hierarchy.blocks
            for polyhedron_id in block.polyhedron_ids
        }

    def _unit_colors(self) -> dict[str, str]:
        unit_palette = ("#397ed1", "#2b9b67", "#dd8730", "#8f5ac8", "#cc5798")
        return {
            unit.id: getattr(self, "unit_colors", {}).get(
                unit.id,
                STRUCTURAL_UNIT_TYPE_COLORS.get(
                    unit.classification,
                    unit_palette[index % len(unit_palette)],
                ),
            )
            for index, unit in enumerate(self.hierarchy.structural_units)
        }

    def _unit_name(self, unit) -> str:
        document = getattr(self, "_document", None)
        analysis = document.structural_analysis if document is not None else None
        if analysis is None:
            return unit.classification
        direct_assignment = next(
            (item for item in analysis.nomenclature if item.domain_id == unit.id),
            None,
        )
        domain = next(
            (
                item
                for item in analysis.structural_domains
                if item.polyhedron_ids == unit.polyhedron_ids
            ),
            None,
        )
        assignment = direct_assignment or (
            next(
                (item for item in analysis.nomenclature if item.domain_id == domain.id),
                None,
            )
            if domain is not None
            else None
        )
        if assignment is None:
            return unit.classification
        if assignment.vocabulary == "borate" and "-membered ring" in unit.classification:
            generic = unit.classification.split(" · ", 1)[0]
            descriptor = assignment.descriptor.replace(
                f"{len(unit.polyhedron_ids)}-membered ",
                "",
                1,
            )
            return f"{generic} · {descriptor}"
        return f"{unit.classification} · {assignment.descriptor}"

    def _polyhedron_unit_map(self) -> dict[str, str]:
        return {
            polyhedron_id: unit.id
            for unit in self.hierarchy.structural_units
            for polyhedron_id in unit.polyhedron_ids
        }

    def _draw_polyhedra(self, color_mode: str) -> None:
        block_colors = self._block_colors()
        block_map = self._polyhedron_block_map()
        unit_colors = self._unit_colors()
        unit_map = self._polyhedron_unit_map()
        family_counts: dict[str, int] = {}
        family_tones: dict[str, int] = {}
        tone_sequence = (0.0, 0.18, -0.16, 0.30, -0.28, 0.40, -0.38)
        surface_groups: dict[str, list[SurfaceInstance]] = {}
        edge_groups: dict[str, list[SurfaceInstance]] = {}
        outline_instances: list[SurfaceInstance] = []
        selected_outline_instances: list[SurfaceInstance] = []
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        for index, polyhedron in enumerate(self.hierarchy.polyhedra):
            if not self._polyhedron_visible(polyhedron):
                continue
            if color_mode == "block":
                color = block_colors[block_map[polyhedron.id]]
            elif color_mode == "unit":
                color = unit_colors[unit_map[polyhedron.id]]
            elif color_mode == "rigidity":
                score = normalized_rigidity(polyhedron_rigidity_index(polyhedron))
                color = self._rigidity_color(score)
            elif color_mode == "distortion":
                score = polyhedron.distortion
                color = "#2b83ba" if score < 0.01 else "#fdae61" if score < 0.05 else "#d7191c"
            else:
                center_site = _polyhedron_center_site(self.structure, polyhedron)
                orbit_key = site_orbit_key(center_site.label)
                base_color = POLYHEDRON_COLORS.get(
                    polyhedron.center_element,
                    site_colour(center_site),
                )
                if orbit_key not in family_tones:
                    family_index = family_counts.get(polyhedron.center_element, 0)
                    family_counts[polyhedron.center_element] = family_index + 1
                    family_tones[orbit_key] = family_index
                color = getattr(self, "polyhedron_orbit_colors", {}).get(
                    orbit_key,
                    _tone(base_color, tone_sequence[family_tones[orbit_key] % len(tone_sequence)]),
                )
            comparison_color = _comparison_polyhedron_color(
                self.comparison_highlight,
                polyhedron.id,
            )
            if comparison_color is not None:
                color = comparison_color
            surface = self._base_polyhedron_surface(polyhedron)
            if surface is None:
                continue
            translations = StructureViewer._translations_for_site(
                self, polyhedron.center_index
            )
            surface_groups.setdefault(color, []).extend(
                SurfaceInstance(
                    surface,
                    tuple(float(value) for value in translation),
                    index,
                )
                for translation in translations
            )
            if self.show_polyhedron_edges:
                edge_color = _shade(
                    color,
                    0.34 if self.render_style == "publication" else 0.52,
                )
                edge_surface = self._base_edge_surface(
                    surface,
                    self.polyhedron_edge_radius,
                    detail,
                )
                if edge_surface is not None:
                    edge_groups.setdefault(edge_color, []).extend(
                        SurfaceInstance(
                            edge_surface,
                            tuple(float(value) for value in translation),
                            index,
                        )
                        for translation in translations
                    )
            if _comparison_outlined(self.comparison_highlight, polyhedron.id):
                outline_surface = self._base_edge_surface(
                    surface,
                    max(
                        self.polyhedron_edge_radius * 1.8,
                        self.polyhedron_edge_radius + 0.012,
                    ),
                    detail,
                )
                if outline_surface is not None:
                    outline_instances.extend(
                        SurfaceInstance(
                            outline_surface,
                            tuple(float(value) for value in translation),
                            index,
                        )
                        for translation in translations
                    )
            if getattr(self, "selected_polyhedron_id", None) == polyhedron.id:
                selected_surface = self._base_edge_surface(
                    surface,
                    max(self.polyhedron_edge_radius * 2.2, 0.034),
                    detail,
                )
                if selected_surface is not None:
                    selected_outline_instances.extend(
                        SurfaceInstance(
                            selected_surface,
                            tuple(float(value) for value in translation),
                            index,
                        )
                        for translation in translations
                    )
        for color, instances in surface_groups.items():
            batch = build_surface_batch(instances)
            if batch is not None:
                if hasattr(batch, "cell_data"):
                    _tag_pick_kind(batch, PICK_POLYHEDRON)
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    opacity=self.polyhedron_opacity,
                    show_edges=False,
                    smooth_shading=False,
                    ambient=0.28 if self.render_style == "publication" else 0.24,
                    diffuse=0.72,
                    specular=0.10,
                    specular_power=18,
                )
        for color, instances in edge_groups.items():
            batch = build_surface_batch(instances)
            if batch is not None:
                if hasattr(batch, "cell_data"):
                    _tag_pick_kind(batch, PICK_POLYHEDRON)
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    opacity=0.98,
                    smooth_shading=True,
                    ambient=0.3,
                    specular=0.2,
                    specular_power=16,
                )
        outline_batch = build_surface_batch(outline_instances)
        if outline_batch is not None:
            self.plotter.add_mesh(
                outline_batch,
                color=OUTLINE_RED,
                opacity=1.0,
                smooth_shading=True,
                ambient=0.34,
                specular=0.12,
                specular_power=14,
            )
        selected_batch = build_surface_batch(selected_outline_instances)
        if selected_batch is not None:
            if hasattr(selected_batch, "cell_data"):
                _tag_pick_kind(selected_batch, PICK_POLYHEDRON)
            self.plotter.add_mesh(
                selected_batch,
                color="#087dca",
                opacity=1.0,
                smooth_shading=True,
                ambient=0.4,
                specular=0.15,
                specular_power=14,
            )

    def _draw_polyhedron_centers(self, comparison_only: bool = False) -> None:
        positions = self.structure.cartesian_positions
        items: list[tuple[str, SphereInstance]] = []
        outline_items: list[SphereInstance] = []
        for index, polyhedron in enumerate(self.hierarchy.polyhedra):
            if not self._polyhedron_visible(polyhedron):
                continue
            comparison_color = _comparison_atom_color(
                self.comparison_highlight,
                polyhedron.center_index,
            )
            outlined = _comparison_atom_outlined(
                self.comparison_highlight,
                polyhedron.center_index,
            )
            if comparison_only and comparison_color is None and not outlined:
                continue
            center = positions[polyhedron.center_index]
            center_site = _polyhedron_center_site(self.structure, polyhedron)
            if self.radius_model == "uniform":
                radius = 0.40
            elif self.radius_model == "covalent":
                radius = _site_display_radius(center_site)
            elif center_site.is_disordered:
                radius = _site_display_radius(center_site)
            else:
                radius = _coordination_ionic_radius(polyhedron.center_element, polyhedron.coordination_number)
            color = comparison_color or POLYHEDRON_COLORS.get(
                polyhedron.center_element,
                site_colour(center_site),
            )
            for translation in StructureViewer._translations_for_site(
                self, polyhedron.center_index
            ):
                instance = SphereInstance(
                    tuple(float(value) for value in center + translation),
                    radius * self.atom_scale,
                    index,
                )
                items.append(
                    (
                        color,
                        instance,
                    )
                )
                if outlined:
                    outline_items.append(
                        SphereInstance(
                            instance.center,
                            instance.radius * 1.12,
                            instance.source_index,
                        )
                    )
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        for color, instances in group_spheres_by_material(items).items():
            batch = build_sphere_batch(instances, detail)
            if batch is not None:
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    smooth_shading=True,
                    interpolation="phong",
                    ambient=0.07,
                    diffuse=0.80,
                    specular=0.62,
                    specular_power=32,
                )
        if outline_items:
            outline_batch = build_sphere_batch(outline_items, detail)
            if outline_batch is not None:
                self.plotter.add_mesh(
                    outline_batch,
                    color=OUTLINE_RED,
                    style="wireframe",
                    line_width=2.0,
                    opacity=1.0,
                    render_lines_as_tubes=True,
                    ambient=0.34,
                    specular=0.12,
                )

    def _draw_polyhedron_vertices(
        self,
        radius: float = 0.145,
        *,
        site_indices: Collection[int] | None = None,
        polyhedron_ids: Collection[str] | None = None,
    ) -> None:
        seen: set[tuple[float, float, float]] = set()
        items: list[tuple[str, SphereInstance]] = []
        for polyhedron_index, polyhedron in enumerate(self.hierarchy.polyhedra):
            if not self._polyhedron_visible(polyhedron):
                continue
            if polyhedron_ids is not None and polyhedron.id not in polyhedron_ids:
                continue
            ligand_color = ELEMENT_COLORS.get(polyhedron.ligand_element, "#ef5350")
            for translation in StructureViewer._translations_for_site(
                self, polyhedron.center_index
            ):
                for ligand, base_vertex in zip(
                    polyhedron.ligands,
                    polyhedron.vertex_coordinates,
                    strict=False,
                ):
                    if (
                        site_indices is not None
                        and ligand.site_index not in site_indices
                    ):
                        continue
                    vertex = np.asarray(base_vertex) + translation
                    key = tuple(round(value, 5) for value in vertex)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        (
                            ligand_color,
                            SphereInstance(
                                tuple(float(value) for value in vertex),
                                radius * self.atom_scale,
                                polyhedron_index,
                            ),
                        )
                    )
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        for color, instances in group_spheres_by_material(items).items():
            batch = build_sphere_batch(instances, detail)
            if batch is not None:
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    smooth_shading=True,
                    interpolation="phong",
                    ambient=0.08,
                    diffuse=0.80,
                    specular=0.60,
                    specular_power=30,
                )

    def _draw_atom_labels(self) -> None:
        subscript = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        points = []
        labels = []
        for atom in self.scene.atoms:
            if atom.site_index in self.hidden_atom_indices:
                continue
            match = re.match(r"^(.*?)(\d+)$", atom.site.label)
            label = (
                f"{match.group(1)}{match.group(2).translate(subscript)}"
                if match
                else atom.site.label
            )
            points.append(atom.cartesian)
            labels.append(label)
        if points:
            self.plotter.add_point_labels(
                points,
                labels,
                point_size=0,
                font_size=11,
                text_color="#202936",
                shape_opacity=0.0,
                always_visible=True,
            )

    def _draw_polyhedron_spokes(self) -> None:
        positions = self.structure.cartesian_positions
        groups: dict[str, list[CylinderInstance]] = {}
        for polyhedron_index, polyhedron in enumerate(self.hierarchy.polyhedra):
            if not self._polyhedron_visible(polyhedron):
                continue
            center = positions[polyhedron.center_index]
            center_site = _polyhedron_center_site(self.structure, polyhedron)
            color = POLYHEDRON_COLORS.get(
                polyhedron.center_element,
                site_colour(center_site),
            )
            for translation in StructureViewer._translations_for_site(
                self, polyhedron.center_index
            ):
                translated_center = center + translation
                for vertex in np.asarray(polyhedron.vertex_coordinates) + translation:
                    material = _shade(color, 0.72)
                    groups.setdefault(material, []).append(
                        CylinderInstance(
                            tuple(float(value) for value in translated_center),
                            tuple(float(value) for value in vertex),
                            0.015,
                            polyhedron_index,
                        )
                    )
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        for color, instances in groups.items():
            batch = build_cylinder_batch(instances, detail)
            if batch is not None:
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    opacity=0.96,
                    smooth_shading=True,
                    ambient=0.24,
                    specular=0.18,
                )

    def _rigidity_limits(self) -> tuple[float, float]:
        if not self.adaptive_rigidity_scale:
            return 0.0, 1.0
        if self.level == HierarchyLevel.RIGID_BLOCKS:
            values = [
                block.rigidity_score
                for block in self.hierarchy.blocks
                if block.id not in self.hidden_block_ids
            ]
        else:
            values = [
                normalized_rigidity(polyhedron_rigidity_index(polyhedron))
                for polyhedron in self.hierarchy.polyhedra
                if self._polyhedron_visible(polyhedron)
            ]
        if not values:
            return 0.0, 1.0
        lower, upper = min(values), max(values)
        if np.isclose(lower, upper):
            return max(0.0, lower - 0.05), min(1.0, upper + 0.05)
        padding = (upper - lower) * 0.08
        return max(0.0, lower - padding), min(1.0, upper + padding)

    def _rigidity_color(self, score: float) -> str:
        anchors = (
            (0.0, np.asarray((215, 48, 39))),
            (0.5, np.asarray((243, 182, 65))),
            (1.0, np.asarray((21, 157, 105))),
        )
        lower, upper = self._rigidity_limits()
        value = (float(score) - lower) / max(upper - lower, 1e-12)
        value = float(np.clip(value, 0.0, 1.0))
        left, right = (anchors[0], anchors[1]) if value <= 0.5 else (anchors[1], anchors[2])
        weight = (value - left[0]) / (right[0] - left[0])
        rgb = np.rint(left[1] * (1.0 - weight) + right[1] * weight).astype(int)
        return "#" + "".join(f"{component:02x}" for component in rgb)

    def _draw_structural_units(self) -> None:
        """Render every detected unit as one solid, atom-free building block.

        Normally the motif is shown without atoms, spokes, or a convex
        envelope. Every constituent polyhedron shares one semantic unit
        colour, while an active comparison may overlay highlighted centers.
        """
        polyhedra = {polyhedron.id: polyhedron for polyhedron in self.hierarchy.polyhedra}
        colors = self._unit_colors()
        surface_groups: dict[str, list[SurfaceInstance]] = {}
        edge_groups: dict[str, list[SurfaceInstance]] = {}
        outline_instances: list[SurfaceInstance] = []
        label_points: list[np.ndarray] = []
        labels: list[str] = []
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        for unit_index, unit in enumerate(self.hierarchy.structural_units):
            if unit.id in self.hidden_unit_ids:
                continue
            unit_color = (
                "#087dca"
                if getattr(self, "selected_scene_object", None) == ("unit", unit.id)
                else colors[unit.id]
            )
            for translation in StructureViewer._aggregate_translations(
                self, unit.polyhedron_ids
            ):
                translated_points: list[np.ndarray] = []
                for polyhedron_id in unit.polyhedron_ids:
                    polyhedron = polyhedra.get(polyhedron_id)
                    if polyhedron is None or not self._polyhedron_visible(polyhedron):
                        continue
                    surface = self._base_polyhedron_surface(polyhedron)
                    if surface is None:
                        continue
                    translated_points.append(np.asarray(polyhedron.vertex_coordinates) + translation)
                    translated = tuple(float(value) for value in translation)
                    color = _comparison_polyhedron_color(
                        self.comparison_highlight,
                        polyhedron.id,
                    ) or unit_color
                    surface_groups.setdefault(color, []).append(
                        SurfaceInstance(surface, translated, unit_index)
                    )
                    if self.show_polyhedron_edges:
                        edge_surface = self._base_edge_surface(
                            surface,
                            max(self.polyhedron_edge_radius * 0.82, 0.010),
                            detail,
                        )
                        if edge_surface is not None:
                            edge_groups.setdefault(_shade(color, 0.34), []).append(
                                SurfaceInstance(edge_surface, translated, unit_index)
                            )
                    if _comparison_outlined(
                        self.comparison_highlight,
                        polyhedron.id,
                    ):
                        outline_surface = self._base_edge_surface(
                            surface,
                            max(
                                self.polyhedron_edge_radius * 1.8,
                                self.polyhedron_edge_radius + 0.012,
                            ),
                            detail,
                        )
                        if outline_surface is not None:
                            outline_instances.append(
                                SurfaceInstance(
                                    outline_surface,
                                    translated,
                                    unit_index,
                                )
                            )
                if self.show_labels and translated_points:
                    label_points.append(np.mean(np.vstack(translated_points), axis=0))
                    labels.append(f"{unit.id} · {self._unit_name(unit)}")
        for color, instances in surface_groups.items():
            batch = build_surface_batch(instances)
            if batch is not None:
                _tag_pick_kind(batch, PICK_UNIT)
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    opacity=1.0,
                    show_edges=False,
                    smooth_shading=False,
                    ambient=0.24,
                    diffuse=0.72,
                    specular=0.18,
                    specular_power=22,
                )
        for color, instances in edge_groups.items():
            batch = build_surface_batch(instances)
            if batch is not None:
                _tag_pick_kind(batch, PICK_UNIT)
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    opacity=0.96,
                    smooth_shading=True,
                    ambient=0.28,
                    specular=0.16,
                )
        outline_batch = build_surface_batch(outline_instances)
        if outline_batch is not None:
            self.plotter.add_mesh(
                outline_batch,
                color=OUTLINE_RED,
                opacity=1.0,
                smooth_shading=True,
                ambient=0.32,
                specular=0.12,
            )
        if self.show_centers:
            self._draw_polyhedron_centers(comparison_only=True)
        if self.comparison_highlight is not None:
            self._draw_atoms(
                comparison_only=True,
                excluded_site_indices={
                    polyhedron.center_index
                    for polyhedron in self.hierarchy.polyhedra
                },
            )
        if label_points:
            self.plotter.add_point_labels(
                label_points,
                labels,
                point_size=0,
                font_size=10,
                text_color="#263342",
                shape_color="#ffffff",
                shape_opacity=0.78,
                always_visible=True,
            )

    def _draw_rigid_blocks(self) -> None:
        """Draw opaque mechanical bodies without their central cations."""
        polyhedra = {
            polyhedron.id: polyhedron for polyhedron in self.hierarchy.polyhedra
        }
        color_mode = self._resolved_color_mode("rigidity")
        if color_mode == "rigidity":
            colors = {
                block.id: self._rigidity_color(block.rigidity_score)
                for block in self.hierarchy.blocks
            }
        else:
            colors = self._block_colors()
        surface_groups: dict[str, list[SurfaceInstance]] = {}
        edge_groups: dict[str, list[SurfaceInstance]] = {}
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        for block_index, block in enumerate(self.hierarchy.blocks):
            if block.id in self.hidden_block_ids:
                continue
            color = (
                "#087dca"
                if getattr(self, "selected_scene_object", None) == ("block", block.id)
                else colors[block.id]
            )
            for translation in StructureViewer._aggregate_translations(
                self, block.polyhedron_ids
            ):
                for polyhedron_id in block.polyhedron_ids:
                    polyhedron = polyhedra.get(polyhedron_id)
                    if polyhedron is None or not self._polyhedron_visible(polyhedron):
                        continue
                    surface = self._base_polyhedron_surface(polyhedron)
                    if surface is None:
                        continue
                    translated = tuple(float(value) for value in translation)
                    surface_groups.setdefault(color, []).append(
                        SurfaceInstance(surface, translated, block_index)
                    )
                    if self.show_polyhedron_edges:
                        edge_surface = self._base_edge_surface(
                            surface,
                            max(self.polyhedron_edge_radius, 0.012),
                            detail,
                        )
                        if edge_surface is not None:
                            edge_groups.setdefault(_shade(color, 0.31), []).append(
                                SurfaceInstance(edge_surface, translated, block_index)
                            )
        for color, instances in surface_groups.items():
            batch = build_surface_batch(instances)
            if batch is not None:
                _tag_pick_kind(batch, PICK_BLOCK)
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    opacity=1.0,
                    show_edges=False,
                    smooth_shading=False,
                    ambient=0.30,
                    diffuse=0.68,
                    specular=0.16,
                    specular_power=20,
                )
        for color, instances in edge_groups.items():
            batch = build_surface_batch(instances)
            if batch is not None:
                _tag_pick_kind(batch, PICK_BLOCK)
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    opacity=1.0,
                    smooth_shading=True,
                    ambient=0.30,
                    specular=0.18,
                )

    def _draw_connectors(self, abstract: bool = False) -> None:
        centers = self._block_centers()
        sphere_items: list[tuple[str, SphereInstance]] = []
        outer_pivots: list[SphereInstance] = []
        rods: list[CylinderInstance] = []
        label_points: list[np.ndarray] = []
        labels: list[str] = []
        for connector_index, connector in enumerate(self.hierarchy.connectors):
            if (
                connector.id in self.hidden_connector_ids
                or connector.first_block in self.hidden_block_ids
                or connector.second_block in self.hidden_block_ids
            ):
                continue
            base_first = centers.get(connector.first_block)
            base_second = centers.get(connector.second_block)
            if base_first is None or base_second is None:
                continue
            if abstract:
                base_pivots = [(base_first + base_second) / 2.0]
                first, second = base_first, base_second
            else:
                first, pivot, second = self._connector_points(connector)
                base_pivots = [pivot]
            for translation in self._translations():
                translated_first = first + translation
                translated_second = second + translation
                for pivot in base_pivots:
                    pivot_array = np.asarray(pivot) + translation
                    for start, end in ((translated_first, pivot_array), (pivot_array, translated_second)):
                        if abstract:
                            rods.append(
                                CylinderInstance(
                                    tuple(float(value) for value in start),
                                    tuple(float(value) for value in end),
                                    0.035,
                                    connector_index,
                                )
                            )
                    if abstract:
                        sphere_items.append(
                            (
                                "#697586",
                                SphereInstance(
                                    tuple(float(value) for value in pivot_array),
                                    0.14,
                                    connector_index,
                                ),
                            )
                        )
                    else:
                        shared_element = self.structure.sites[connector.ligand_indices[0]].element
                        outer_pivots.append(
                            SphereInstance(
                                tuple(float(value) for value in pivot_array),
                                0.21,
                                connector_index,
                            )
                        )
                        sphere_items.append(
                            (
                                ELEMENT_COLORS.get(shared_element, "#f52218"),
                                SphereInstance(
                                    tuple(float(value) for value in pivot_array),
                                    0.115,
                                    connector_index,
                                ),
                            )
                        )
                        if self.show_connector_labels:
                            angle = self._connector_angle(
                                translated_first,
                                pivot_array,
                                translated_second,
                            )
                            site_label = self.structure.sites[connector.ligand_indices[0]].label
                            label_points.append(pivot_array)
                            labels.append(f"{connector.id} · {site_label} · {angle:.1f}°")
        detail = detail_level_for_atom_count(len(self.scene.atoms))
        if rods:
            batch = build_cylinder_batch(rods, detail)
            if batch is not None:
                self.plotter.add_mesh(
                    batch,
                    color="#697586",
                    smooth_shading=True,
                    opacity=0.95,
                )
        if outer_pivots:
            batch = build_sphere_batch(outer_pivots, detail)
            if batch is not None:
                self.plotter.add_mesh(
                    batch,
                    color="#e39a25",
                    opacity=0.30,
                    smooth_shading=True,
                )
        for color, instances in group_spheres_by_material(sphere_items).items():
            batch = build_sphere_batch(instances, detail)
            if batch is not None:
                self.plotter.add_mesh(
                    batch,
                    color=color,
                    smooth_shading=True,
                    specular=0.35,
                )
        if label_points:
            self.plotter.add_point_labels(
                label_points,
                labels,
                point_size=0,
                font_size=9,
                text_color="#263342",
                shape_color="#ffffff",
                shape_opacity=0.72,
                always_visible=True,
            )

    def _connector_points(self, connector) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return the real cation–shared-site–cation geometry."""
        polyhedra = {polyhedron.id: polyhedron for polyhedron in self.hierarchy.polyhedra}
        first_polyhedron = polyhedra[connector.first_polyhedron]
        second_polyhedron = polyhedra[connector.second_polyhedron]
        pivot = np.asarray(connector.pivot_coordinates[0], dtype=float)
        matrix = self.structure.cell.matrix
        pivot_fractional = pivot @ np.linalg.inv(matrix)

        def nearest_center(polyhedron) -> np.ndarray:
            fractional = np.asarray(
                self.structure.sites[polyhedron.center_index].fractional,
                dtype=float,
            )
            delta = fractional - pivot_fractional
            delta -= np.rint(delta)
            return pivot + delta @ matrix

        first = nearest_center(first_polyhedron)
        second = nearest_center(second_polyhedron)
        return first, pivot, second

    @staticmethod
    def _connector_angle(first: np.ndarray, pivot: np.ndarray, second: np.ndarray) -> float:
        left = first - pivot
        right = second - pivot
        denominator = np.linalg.norm(left) * np.linalg.norm(right)
        if denominator < 1e-10:
            return 0.0
        cosine = float(np.clip(np.dot(left, right) / denominator, -1.0, 1.0))
        return float(np.degrees(np.arccos(cosine)))

    def _block_centers(self) -> dict[str, np.ndarray]:
        positions = self.structure.cartesian_positions
        polyhedra = {polyhedron.id: polyhedron for polyhedron in self.hierarchy.polyhedra}
        return {
            block.id: np.mean(
                [positions[polyhedra[polyhedron_id].center_index] for polyhedron_id in block.polyhedron_ids],
                axis=0,
            )
            for block in self.hierarchy.blocks
            if block.polyhedron_ids
        }

    def _draw_skeleton(self) -> None:
        centers = self._block_centers()
        colors = self._block_colors()
        if self.show_centers:
            for translation in self._translations():
                for block in self.hierarchy.blocks:
                    if block.id in self.hidden_block_ids:
                        continue
                    center = centers.get(block.id)
                    if center is None:
                        continue
                    center = center + translation
                    radius = 0.30 + 0.11 * np.sqrt(max(len(block.polyhedron_ids), 1))
                    self.plotter.add_mesh(
                        pv.Sphere(radius=min(radius, 0.72), center=center, theta_resolution=28, phi_resolution=28),
                        color=colors[block.id],
                        opacity=0.94,
                        smooth_shading=True,
                        interpolation="phong",
                        ambient=0.08,
                        diffuse=0.80,
                        specular=0.55,
                        specular_power=28,
                    )
                    if self.show_labels:
                        self.plotter.add_point_labels(
                            [center],
                            [block.id],
                            text_color="#172033",
                            font_size=11,
                            point_size=0,
                            shape_opacity=0.0,
                            always_visible=True,
                        )
        if self.show_connectors:
            self._draw_connectors(abstract=True)

    def _draw_topology(self) -> None:
        report = getattr(self._document, "inorganic_topology", None)
        if report is None:
            return
        components = {item.id: item for item in report.components}
        polyhedra = {item.id: item for item in self.hierarchy.polyhedra}
        centers = {
            identifier: self.structure.cell.frac_to_cart(
                self.structure.sites[polyhedron.center_index].fractional
            )
            for identifier, polyhedron in polyhedra.items()
        }
        cell_matrix = np.asarray(self.structure.cell.matrix, dtype=float)
        cell_scale = min(float(np.linalg.norm(vector)) for vector in cell_matrix)
        node_radius = max(0.06, 0.025 * cell_scale)
        width_by_kind = {"corner": 3.0, "edge": 5.0, "face": 7.0}

        def display_translations(identifier: str) -> tuple[np.ndarray, ...]:
            polyhedron = polyhedra.get(identifier)
            if polyhedron is None:
                return ()
            if hasattr(self, "scene") and hasattr(self, "_translations_for_site"):
                return tuple(self._translations_for_site(polyhedron.center_index))
            return (np.zeros(3, dtype=float),)

        for family_number, family in enumerate(report.families):
            if family.id in self.hidden_topology_family_ids:
                continue
            color = _TOPOLOGY_COLORS[family_number % len(_TOPOLOGY_COLORS)]
            identifiers = {
                identifier
                for component_id in family.component_ids
                for identifier in components[component_id].polyhedron_ids
            }
            for identifier in sorted(identifiers):
                center = centers.get(identifier)
                if center is None:
                    continue
                for image_number, translation in enumerate(
                    display_translations(identifier)
                ):
                    self.plotter.add_mesh(
                        pv.Sphere(
                            radius=node_radius,
                            center=center + translation,
                            theta_resolution=20,
                            phi_resolution=20,
                        ),
                        color=color,
                        smooth_shading=True,
                        name=(
                            f"topology:{family.id}:node:{identifier}:"
                            f"{image_number}"
                        ),
                    )
            for edge_number, connection in enumerate(
                self.hierarchy.polyhedron_connections
            ):
                if connection.first not in identifiers or connection.second not in identifiers:
                    continue
                first = centers.get(connection.first)
                second = centers.get(connection.second)
                if first is None or second is None:
                    continue
                for image_number, translation in enumerate(
                    display_translations(connection.first)
                ):
                    translated_second = (
                        second
                        + translation
                        + np.asarray(connection.translation) @ cell_matrix
                    )
                    self.plotter.add_mesh(
                        pv.Line(first + translation, translated_second),
                        color=color,
                        line_width=width_by_kind.get(connection.kind, 3.0),
                        name=(
                            f"topology:{family.id}:edge:{edge_number}:"
                            f"{image_number}"
                        ),
                    )

        cation_components = {item.id: item for item in report.cation_components}
        for family_number, family in enumerate(report.cation_families):
            if family.id in self.hidden_topology_family_ids:
                continue
            color = _TOPOLOGY_COLORS[
                (family_number + len(report.families)) % len(_TOPOLOGY_COLORS)
            ]
            identifiers = {
                identifier
                for component_id in family.component_ids
                for identifier in cation_components[component_id].polyhedron_ids
            }
            for identifier in sorted(identifiers):
                center = centers.get(identifier)
                if center is None:
                    continue
                polyhedron = polyhedra[identifier]
                node_color = site_colour(
                    self.structure.sites[polyhedron.center_index]
                )
                for image_number, translation in enumerate(
                    display_translations(identifier)
                ):
                    self.plotter.add_mesh(
                        pv.Sphere(
                            radius=node_radius * 1.3,
                            center=center + translation,
                            theta_resolution=20,
                            phi_resolution=20,
                        ),
                        color=node_color,
                        smooth_shading=True,
                        name=(
                            f"topology:{family.id}:cation-node:{identifier}:"
                            f"{image_number}"
                        ),
                    )
            for edge_number, edge in enumerate(report.cation_edges):
                if edge.first not in identifiers or edge.second not in identifiers:
                    continue
                first = centers.get(edge.first)
                second = centers.get(edge.second)
                if first is None or second is None:
                    continue
                for image_number, translation in enumerate(
                    display_translations(edge.first)
                ):
                    translated_second = (
                        second
                        + translation
                        + np.asarray(edge.translation) @ cell_matrix
                    )
                    shared_ligand = edge.mode == "shared-ligand"
                    self.plotter.add_mesh(
                        pv.Line(first + translation, translated_second),
                        color=color,
                        line_width=4.0 if shared_ligand else 1.5,
                        opacity=0.92 if shared_ligand else 0.32,
                        name=(
                            f"topology:{family.id}:{edge.mode}-edge:"
                            f"{edge_number}:{image_number}"
                        ),
                    )

    def view_axis(self, axis: str) -> None:
        {"a": self.plotter.view_yz, "b": self.plotter.view_xz, "c": self.plotter.view_xy}[axis]()
        self.plotter.reset_camera()

    def zoom(self, factor: float) -> None:
        self.plotter.camera.zoom(factor)
        self.plotter.render()

    def save_screenshot(self, path: str) -> None:
        self.plotter.screenshot(path)
