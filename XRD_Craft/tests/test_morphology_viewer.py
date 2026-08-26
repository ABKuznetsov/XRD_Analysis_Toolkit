from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QWidget

from crystal_viewer.analysis.morphology import MillerFamily, MorphologyPlane
from crystal_viewer.analysis.morphology_geometry import MorphologyFacet, MorphologyModel
from crystal_viewer.analysis.surface_markings import (
    MarkingPolyline,
    MarkingSegment,
    SurfaceMarkingKind,
)
from crystal_viewer.analysis.twin_geometry import (
    CompositionPlane,
    TwinAggregate,
    TwinDomain,
    TwinFacet,
)
from crystal_viewer.ui.morphology_colors import allocate_family_colors, family_color, rgb_tuple
from crystal_viewer.ui.morphology_viewer import MorphologyViewer, build_morphology_mesh


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _model() -> MorphologyModel:
    first = MillerFamily((1, 0, 0), ((1, 0, 0),), 1.0, 1, 1.0, "test")
    second = MillerFamily((0, 1, 0), ((0, 1, 0),), 1.0, 1, 1.0, "test")
    planes = (MorphologyPlane(first, 1.0, 1.0), MorphologyPlane(second, 1.0, 1.0))
    facets = (
        MorphologyFacet((1, 0, 0), (1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 0, 1)), (1, 0, 0), 0.5),
        MorphologyFacet((0, 1, 0), (0, 1, 0), ((0, 1, 0), (1, 1, 0), (0, 1, 1)), (0, 1, 0), 0.5),
    )
    return MorphologyModel(planes, (), facets, 1.0, {(1, 0, 0): 0.5, (0, 1, 0): 0.5}, {(1, 0, 0): 0.5, (0, 1, 0): 0.5})


def test_mesh_batches_facets_and_preserves_family_ids() -> None:
    colors = {(1, 0, 0): "#112233", (0, 1, 0): "#abcdef"}
    result = build_morphology_mesh(_model(), colors)

    assert result.mesh.n_cells == 2
    assert set(np.asarray(result.mesh.cell_data["family_id"])) == {0, 1}
    assert set(result.family_by_id.values()) == {(1, 0, 0), (0, 1, 0)}
    assert result.mesh.cell_data["family_rgb"].shape == (2, 3)
    for cell_index, family_id in enumerate(result.mesh.cell_data["family_id"]):
        family = result.family_by_id[int(family_id)]
        assert tuple(result.mesh.cell_data["family_rgb"][cell_index]) == rgb_tuple(colors[family])


def test_simple_form_colors_are_distinct_and_stable() -> None:
    colors = tuple(family_color(hkl) for hkl in ((1, 0, 0), (1, 1, 0), (1, 1, 1)))

    assert len(set(colors)) == 3
    assert family_color((-1, 0, 0)) == colors[0]
    assert family_color((2, 0, 0)) == colors[0]


def test_complete_family_palette_is_unique_and_stable() -> None:
    families = tuple((1, index // 7, index % 7) for index in range(40))

    first = allocate_family_colors(families)
    second = allocate_family_colors(reversed(families))

    assert first == second
    assert len(set(first.values())) == len(families)
    assert first[(1, 2, 3)] != first[(1, 3, 2)]
    active_subset = {family: first[family] for family in families[:5]}
    assert active_subset == {family: second[family] for family in families[:5]}


def test_facets_are_opaque_and_each_plane_is_labelled_at_its_centroid() -> None:
    _application()

    class RecordingPlotter:
        def __init__(self) -> None:
            self.interactor = QWidget()
            self.camera_position = None
            self.surface_options = None
            self.label_points = None
            self.labels = None
            self.legend = None

        def clear(self): pass
        def add_mesh(self, *_args, **kwargs):
            self.surface_options = kwargs
            return object()
        def add_axes(self, **_kwargs): pass
        def enable_cell_picking(self, **_kwargs): pass
        def reset_camera(self): pass
        def render(self): pass
        def add_text(self, *_args, **_kwargs): pass
        def add_legend(self, entries, **_kwargs): self.legend = entries
        def add_point_labels(self, points, labels, **_kwargs):
            self.label_points = np.asarray(points)
            self.labels = tuple(labels)

    plotter = RecordingPlotter()
    viewer = MorphologyViewer(plotter_factory=lambda _parent: plotter)
    try:
        viewer.set_model(_model(), reset_camera=True)

        assert plotter.surface_options["opacity"] == 1.0
        assert plotter.labels == ("(1 0 0)", "(0 1 0)")
        np.testing.assert_allclose(
            plotter.label_points,
            ((1.0, 1.0 / 3.0, 1.0 / 3.0), (1.0 / 3.0, 1.0, 1.0 / 3.0)),
        )
        assert len(plotter.legend) == 2
    finally:
        viewer.close()


def test_viewer_replaces_model_and_tracks_selected_family() -> None:
    _application()
    class FakePlotter:
        def __init__(self) -> None:
            self.interactor = QWidget()
            self.camera_position = None
            self.actors = []

        def clear(self):
            self.actors.clear()

        def add_mesh(self, *_args, **_kwargs):
            actor = object()
            self.actors.append(actor)
            return actor

        def add_axes(self, **_kwargs):
            return None

        def enable_cell_picking(self, **_kwargs):
            return None

        def reset_camera(self):
            return None

        def render(self):
            return None

        def remove_actor(self, actor):
            if actor in self.actors:
                self.actors.remove(actor)

        def add_text(self, *_args, **_kwargs):
            return None

        def add_legend(self, *_args, **_kwargs):
            return None

        def add_point_labels(self, *_args, **_kwargs):
            return None

    fake = FakePlotter()
    viewer = MorphologyViewer(plotter_factory=lambda _parent: fake)
    try:
        viewer.set_model(_model(), reset_camera=True)
        viewer.select_family((1, 0, 0))

        assert viewer.model is not None
        assert viewer.selected_family == (1, 0, 0)
        assert viewer.surface_actor is not None
        viewer.clear()
        assert viewer.model is None
    finally:
        viewer.close()


def test_png_contains_structure_title_and_family_legend(tmp_path) -> None:
    _application()

    class FakePlotter:
        def __init__(self) -> None:
            self.interactor = QWidget()
            self.camera_position = None
            self.texts = []
            self.legend = None
            self.screenshot_path = None

        def clear(self): pass
        def add_mesh(self, *_args, **_kwargs): return object()
        def add_axes(self, **_kwargs): pass
        def enable_cell_picking(self, **_kwargs): pass
        def reset_camera(self): pass
        def render(self): pass
        def remove_actor(self, *_args): pass
        def add_text(self, text, **_kwargs): self.texts.append(text)
        def add_legend(self, entries, **_kwargs): self.legend = entries
        def add_point_labels(self, *_args, **_kwargs): pass
        def screenshot(self, path): self.screenshot_path = path

    fake = FakePlotter()
    viewer = MorphologyViewer(plotter_factory=lambda _parent: fake)
    try:
        viewer.set_structure_name("Test crystal")
        viewer.set_model(_model(), reset_camera=True)
        target = tmp_path / "morphology.png"
        viewer.export_png(target)

        assert "Test crystal" in fake.texts
        assert {entry[0] for entry in fake.legend} == {"{0 1 0}", "{1 0 0}"}
        assert fake.screenshot_path == str(target)
    finally:
        viewer.close()


def test_aggregate_render_contract_is_opaque_batched_labelled_and_has_no_picker_overlay() -> None:
    _application()
    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    twin_orientation = ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    first = TwinFacet(
        (1, 0, 0), (1, 0, 0), (1, 0, 0),
        ((1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (1.0, 0.0, 1.0)),
        (1.0, 0.0, 0.0), 0.5, "I",
    )
    second = TwinFacet(
        (0, 1, 0), (0, 1, 0), (0, 1, 0),
        ((0.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, -1.0, 1.0)),
        (0.0, -1.0, 0.0), 0.5, "II",
    )
    aggregate = TwinAggregate(
        (
            TwinDomain("I", identity, (0.0, 0.0, 0.0), (first,), first.vertices, "I"),
            TwinDomain("II", twin_orientation, (0.0, 0.0, 0.0), (second,), second.vertices, "II"),
        ),
        (first, second),
        (
            CompositionPlane(
                (0.0, 0.0, 1.0), 0.0,
                ((-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)),
                (0, 0, 1),
            ),
        ),
    )
    induction = (
        MarkingPolyline(
            ((0.2, 0.1, 0.0), (0.8, 0.1, 0.0), (0.2, 0.1, 0.0)),
            (1, 0, 0), "I", SurfaceMarkingKind.INDUCTION,
        ),
    )
    twin_lines = (
        MarkingSegment((0.0, -1.0, 0.0), (0.0, -1.0, 1.0), (0, 1, 0), "II"),
    )

    class RecordingPlotter:
        def __init__(self) -> None:
            self.interactor = QWidget()
            self.camera_position = None
            self.meshes = []
            self.point_labels = []
            self.texts = []
            self.picking = None

        def clear(self): pass
        def add_mesh(self, mesh, **kwargs):
            self.meshes.append((mesh, kwargs))
            return object()
        def add_axes(self, **_kwargs): pass
        def enable_cell_picking(self, **kwargs): self.picking = kwargs
        def reset_camera(self): pass
        def render(self): pass
        def add_text(self, text, **_kwargs): self.texts.append(text)
        def add_legend(self, *_args, **_kwargs): pass
        def add_point_labels(self, points, labels, **_kwargs):
            self.point_labels.append((np.asarray(points), tuple(labels)))

    plotter = RecordingPlotter()
    viewer = MorphologyViewer(plotter_factory=lambda _parent: plotter)
    try:
        viewer.set_model(
            _model(),
            aggregate=aggregate,
            induction_contours=induction,
            twin_segments=twin_lines,
            reset_camera=True,
        )

        surfaces = [options for _mesh, options in plotter.meshes if str(options.get("name", "")).startswith("morphology-domain-")]
        assert len(surfaces) == 2
        assert all(options["opacity"] == 1.0 for options in surfaces)
        assert surfaces[0]["edge_color"] != surfaces[1]["edge_color"]
        names = {options.get("name") for _mesh, options in plotter.meshes}
        assert "morphology-composition-planes" in names
        assert "morphology-induction-lines" in names
        assert "morphology-twin-lines" in names
        assert sum(name == "morphology-induction-lines" for name in names) == 1
        labels = {label for _points, group in plotter.point_labels for label in group}
        assert "Composition (0 0 1)" in labels
        assert {"I a", "I b", "I c", "II a", "II b", "II c"} <= labels
        assert plotter.picking["show_message"] is False
        assert not any("Press R" in text for text in plotter.texts)
    finally:
        viewer.close()


def test_replacing_a_model_restarts_cell_picking_without_double_enable() -> None:
    _application()

    class StrictPickingPlotter:
        def __init__(self) -> None:
            self.interactor = QWidget()
            self.camera_position = None
            self.picking_enabled = False
            self.disable_calls = 0

        def clear(self): pass
        def add_mesh(self, *_args, **_kwargs): return object()
        def add_axes(self, **_kwargs): pass
        def reset_camera(self): pass
        def render(self): pass
        def add_text(self, *_args, **_kwargs): pass
        def add_legend(self, *_args, **_kwargs): pass
        def add_point_labels(self, *_args, **_kwargs): pass
        def enable_cell_picking(self, **_kwargs):
            if self.picking_enabled:
                raise RuntimeError("picking already enabled")
            self.picking_enabled = True
        def disable_picking(self):
            self.picking_enabled = False
            self.disable_calls += 1

    plotter = StrictPickingPlotter()
    viewer = MorphologyViewer(plotter_factory=lambda _parent: plotter)
    try:
        viewer.set_model(_model(), reset_camera=True)
        viewer.set_model(_model(), reset_camera=False)

        assert plotter.picking_enabled
        assert plotter.disable_calls >= 1
    finally:
        viewer.close()
