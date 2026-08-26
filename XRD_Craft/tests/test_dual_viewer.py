from __future__ import annotations

import os
from math import sqrt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from crystal_viewer.analysis.descriptors.model import FocusCommand
from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyLevel,
    HierarchyReport,
    PeriodicSiteRef,
)
from crystal_viewer.analysis.motif_comparison import (
    MotifComparisonReport,
    MotifMatch,
)
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui import dual_viewer as dual_module
from crystal_viewer.ui.comparison_highlight import MATCH_PALETTE
from crystal_viewer.ui.viewer import CameraState


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _document(name: str) -> StructureDocument:
    sites = [AtomSite("Si1", "Si", (0.5, 0.5, 0.5))]
    structure = CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), sites, sites)
    return StructureDocument.from_structure(structure, HierarchyReport())


def _focus_document(
    name: str,
    polyhedron_ids: tuple[str, ...],
    *,
    site_count: int = 6,
) -> StructureDocument:
    sites = [
        AtomSite(f"Si{index + 1}", "Si", (0.1 * index, 0.0, 0.0))
        for index in range(site_count)
    ]
    structure = CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), sites, sites)
    document = StructureDocument.from_structure(structure, HierarchyReport())
    document.hierarchy.polyhedra.extend(
        CoordinationPolyhedron(
            identifier,
            index,
            "Si",
            "O",
            (),
            (),
            (),
            0.0,
            0.0,
        )
        for index, identifier in enumerate(polyhedron_ids)
    )
    return document


def _motif_report(first_id: str, second_id: str) -> MotifComparisonReport:
    return MotifComparisonReport(
        first_document_id=first_id,
        second_document_id=second_id,
        matches=(
            MotifMatch(
                id="M1",
                classification="chain",
                periodic_rank=1,
                node_pairs=(("P1", "P7"), ("I3", "I8")),
                edge_pairs=(),
                edge_kinds=(),
                topology_score=1.0,
                geometry_score=1.0,
                chemistry_score=1.0,
                total_score=1.0,
            ),
        ),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=False,
        states_explored=1,
    )


class FakeViewer(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.style_updates = 0
        self.level = HierarchyLevel.ATOMS
        self.document = None
        self._camera = CameraState(
            (10.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            5.0,
            30.0,
            True,
        )
        self.applied_camera = None
        self.show_labels = False
        self.show_connector_labels = False
        self.hierarchy = None
        self.hidden_atom_indices = set()
        self.hidden_polyhedron_ids = set()
        self.hidden_unit_ids = set()
        self.hidden_block_ids = set()
        self.hidden_connector_ids = set()
        self.comparison_highlight = None
        self.redraw_count = 0
        self.saved_path = None

    def set_document(self, document, reset_camera=True) -> None:
        self.document = document
        self.hierarchy = document.hierarchy
        self.apply_visual_state(document.visual, redraw=False)

    def set_level(self, level) -> None:
        self.level = HierarchyLevel(level)

    def camera_state(self):
        return self._camera

    def apply_camera_state(self, state) -> None:
        self.applied_camera = state

    def redraw(self, reset_camera=False) -> None:
        self.redraw_count += 1

    def apply_visual_state(self, state, redraw=True) -> None:
        self.level = HierarchyLevel(state.level)
        self.hidden_atom_indices = set(state.hidden_atom_indices)
        self.hidden_polyhedron_ids = set(state.hidden_polyhedron_ids)
        self.hidden_unit_ids = set(state.hidden_unit_ids)
        self.hidden_block_ids = set(state.hidden_block_ids)
        self.hidden_connector_ids = set(state.hidden_connector_ids)
        if redraw:
            self.redraw(reset_camera=False)

    def set_comparison_highlight(self, highlight) -> None:
        self.comparison_highlight = highlight
        self.redraw(reset_camera=False)

    def save_screenshot(self, path) -> None:
        self.saved_path = path

    def setStyleSheet(self, style) -> None:
        self.style_updates += 1
        super().setStyleSheet(style)


def test_dual_viewer_sets_one_level_on_both_sides(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    viewer.set_pair(_document("first"), _document("second"))

    viewer.set_level(HierarchyLevel.POLYHEDRA)

    assert viewer.left.level is HierarchyLevel.POLYHEDRA
    assert viewer.right.level is HierarchyLevel.POLYHEDRA


def test_comparison_status_is_ordinary_selectable_text(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()

    viewer.set_comparison_status("Comparing structures…")

    assert isinstance(viewer.status_label, QLabel)
    assert viewer.status_label.text() == "Comparing structures…"
    assert viewer.status_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_camera_copy_uses_camera_state_without_redraw(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    viewer.set_pair(_document("first"), _document("second"))
    viewer.left._camera = CameraState(
        (10.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        5.0,
        30.0,
        True,
    )
    viewer.right._camera = CameraState(
        (0.0, 20.0, 0.0),
        (1.0, 2.0, 3.0),
        (0.0, 1.0, 0.0),
        12.0,
        25.0,
        False,
    )

    viewer._copy_camera(viewer.left, viewer.right)

    assert viewer.right.applied_camera.position == pytest.approx((1.0 + sqrt(334.0), 2.0, 3.0))
    assert viewer.right.applied_camera.focal_offset == (1.0, 2.0, 3.0)
    assert viewer.right.applied_camera.parallel_scale == 12.0
    assert viewer.right.applied_camera.view_angle == 25.0
    assert viewer.right.applied_camera.parallel_projection is True


def test_dual_viewer_propagates_site_and_connector_labels(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()

    viewer.set_show_labels(site_labels=True, connector_labels=True)

    assert viewer.left.show_labels is True
    assert viewer.right.show_labels is True
    assert viewer.left.show_connector_labels is True
    assert viewer.right.show_connector_labels is True


def test_window_under_mouse_becomes_active(monkeypatch) -> None:
    application = _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()

    application.sendEvent(viewer.right, QEvent(QEvent.Type.Enter))

    assert viewer.active_viewer is viewer.right
    assert viewer.right.property("comparisonActive") is True
    assert viewer.left.property("comparisonActive") is False


def test_repeated_activation_does_not_restyle_vtk_widgets(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    before = (viewer.left.style_updates, viewer.right.style_updates)

    viewer._set_active_viewer(viewer.left)

    assert (viewer.left.style_updates, viewer.right.style_updates) == before


def test_rotation_sync_preserves_target_scale_and_pan() -> None:
    source = CameraState((10.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 5.0, 30.0, True)
    target = CameraState((0.0, 20.0, 0.0), (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 12.0, 25.0, True)

    result = dual_module.rotation_only_camera_state(source, target)

    assert result.focal_offset == target.focal_offset
    assert result.parallel_scale == target.parallel_scale
    assert result.view_angle == target.view_angle
    assert result.position == pytest.approx((1.0 + sqrt(334.0), 2.0, 3.0))


def test_polyhedron_focus_is_applied_independently_to_both_sides(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    documents = []
    for name in ("first", "second"):
        document = _document(name)
        ligands = tuple(PeriodicSiteRef(0) for _ in range(6))
        document.hierarchy.polyhedra.extend(
            (
                CoordinationPolyhedron("Mo1", 0, "Mo", "O", ligands, (2.0,) * 6, ((0.0, 0.0, 0.0),) * 6, 0.0, 0.0),
                CoordinationPolyhedron("Si1", 0, "Si", "O", ligands[:4], (1.6,) * 4, ((0.0, 0.0, 0.0),) * 4, 0.0, 0.0),
            )
        )
        documents.append(document)
    viewer.set_pair(*documents)
    command = FocusCommand(
        "isolate",
        HierarchyLevel.POLYHEDRA,
        "polyhedron-type",
        {"center": "Mo", "coordination": 6},
    )

    viewer.focus(command)

    assert viewer.left.hidden_polyhedron_ids == {"Si1"}
    assert viewer.right.hidden_polyhedron_ids == {"Si1"}
    assert viewer.left.level is HierarchyLevel.POLYHEDRA
    assert viewer.right.level is HierarchyLevel.POLYHEDRA


def test_motif_report_maps_directional_highlights_and_redraws_once(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    first = _document("first")
    second = _document("second")
    viewer.set_pair(first, second)
    viewer.set_show_labels(site_labels=True, connector_labels=True)
    viewer.left.redraw_count = viewer.right.redraw_count = 0

    viewer.set_motif_report(_motif_report(first.id, second.id))

    assert viewer.left.comparison_highlight.polyhedron_colors == {"P1": MATCH_PALETTE[0]}
    assert viewer.right.comparison_highlight.polyhedron_colors == {"P7": MATCH_PALETTE[0]}
    assert viewer.left.comparison_highlight.atom_colors == {3: MATCH_PALETTE[0]}
    assert viewer.right.comparison_highlight.atom_colors == {8: MATCH_PALETTE[0]}
    assert viewer.left.level is HierarchyLevel.STRUCTURAL_UNITS
    assert viewer.right.level is HierarchyLevel.STRUCTURAL_UNITS
    assert (viewer.left.show_labels, viewer.right.show_labels) == (True, True)
    assert (viewer.left.show_connector_labels, viewer.right.show_connector_labels) == (True, True)
    assert (viewer.left.redraw_count, viewer.right.redraw_count) == (1, 1)
    assert viewer.right.applied_camera is not None


def test_swapping_pair_remaps_report_and_replacing_pair_clears_it(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    first = _document("first")
    second = _document("second")
    viewer.set_pair(first, second)
    report = _motif_report(first.id, second.id)
    viewer.set_motif_report(report)

    viewer.swap_documents()

    assert (viewer.first_document, viewer.second_document) == (second, first)
    assert viewer.left.comparison_highlight.polyhedron_colors == {"P7": MATCH_PALETTE[0]}
    assert viewer.right.comparison_highlight.polyhedron_colors == {"P1": MATCH_PALETTE[0]}

    viewer.set_pair(_document("third"), _document("fourth"))

    assert viewer.left.comparison_highlight is None
    assert viewer.right.comparison_highlight is None


def test_swapped_pair_reverses_exact_focus_payload_including_empty_side(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    first = _focus_document("first", ("P1", "P2"))
    second = _focus_document("second", ("P7", "P8"))
    viewer.set_pair(first, second)
    report = _motif_report(first.id, second.id)
    viewer.set_motif_report(report)
    viewer.swap_documents()

    viewer.focus(
        FocusCommand(
            "isolate",
            HierarchyLevel.STRUCTURAL_UNITS,
            "motif-pair",
            {
                "first_polyhedron_ids": ("P1",),
                "second_polyhedron_ids": (),
                "first_atom_indices": (4,),
                "second_atom_indices": (),
            },
        )
    )

    assert viewer._motif_report is report
    assert viewer.left.hidden_polyhedron_ids == {"P7", "P8"}
    assert viewer.left.hidden_atom_indices == {0, 1, 2, 3, 4, 5}
    assert viewer.right.hidden_polyhedron_ids == {"P2"}
    assert viewer.right.hidden_atom_indices == {1, 2, 3, 5}


def test_motif_report_rejects_documents_outside_the_active_pair(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    viewer.set_pair(_document("first"), _document("second"))

    with pytest.raises(ValueError, match="active pair"):
        viewer.set_motif_report(_motif_report("unrelated-a", "unrelated-b"))


def test_motif_focus_isolates_asymmetric_polyhedra_and_atoms(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    first = _focus_document("first", ("P1", "P2", "P3"))
    second = _focus_document("second", ("P7", "P8", "P9"))
    viewer.set_pair(first, second)
    command = FocusCommand(
        "isolate",
        HierarchyLevel.STRUCTURAL_UNITS,
        "motif-pair",
        {
            "first_polyhedron_ids": ("P1", "P2"),
            "second_polyhedron_ids": ("P8",),
            "first_atom_indices": (4,),
            "second_atom_indices": (5,),
        },
    )

    viewer.focus(command)

    assert viewer.left.hidden_polyhedron_ids == {"P3"}
    assert viewer.right.hidden_polyhedron_ids == {"P7", "P9"}
    assert viewer.left.hidden_atom_indices == {2, 3, 5}
    assert viewer.right.hidden_atom_indices == {0, 2, 3, 4}
    assert (viewer.left.redraw_count, viewer.right.redraw_count) == (1, 1)


def test_empty_first_side_focus_does_not_fall_back_to_second_side(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    first = _focus_document("first", ("P1", "P2"), site_count=4)
    second = _focus_document("second", ("P7", "P8"), site_count=4)
    viewer.set_pair(first, second)

    viewer.focus(
        FocusCommand(
            "isolate",
            HierarchyLevel.STRUCTURAL_UNITS,
            "unmatched-pair",
            {
                "first_polyhedron_ids": (),
                "second_polyhedron_ids": ("P8",),
                "first_atom_indices": (),
                "second_atom_indices": (3,),
            },
        )
    )

    assert viewer.left.hidden_polyhedron_ids == {"P1", "P2"}
    assert viewer.left.hidden_atom_indices == {0, 1, 2, 3}
    assert viewer.right.hidden_polyhedron_ids == {"P7"}
    assert viewer.right.hidden_atom_indices == {0, 2}


def test_clear_focus_restores_visual_state_and_retains_highlight_and_labels(monkeypatch) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    first = _focus_document("first", ("P1", "P2"), site_count=4)
    second = _focus_document("second", ("P7", "P8"), site_count=4)
    first.visual.level = HierarchyLevel.POLYHEDRA
    first.visual.hidden_atom_indices = {3}
    first.visual.hidden_polyhedron_ids = {"P2"}
    second.visual.level = HierarchyLevel.ATOMS
    second.visual.hidden_atom_indices = {0}
    second.visual.hidden_polyhedron_ids = {"P7"}
    viewer.set_pair(first, second)
    viewer.set_show_labels(site_labels=True, connector_labels=True)
    viewer.set_motif_report(_motif_report(first.id, second.id))
    left_highlight = viewer.left.comparison_highlight
    right_highlight = viewer.right.comparison_highlight
    snapshots = (
        (first.visual.level, set(first.visual.hidden_atom_indices), set(first.visual.hidden_polyhedron_ids)),
        (second.visual.level, set(second.visual.hidden_atom_indices), set(second.visual.hidden_polyhedron_ids)),
    )

    viewer.focus(
        FocusCommand(
            "isolate",
            HierarchyLevel.STRUCTURAL_UNITS,
            "motif-pair",
            {
                "first_polyhedron_ids": ("P1",),
                "second_polyhedron_ids": ("P8",),
                "first_atom_indices": (),
                "second_atom_indices": (),
            },
        )
    )

    assert snapshots == (
        (first.visual.level, first.visual.hidden_atom_indices, first.visual.hidden_polyhedron_ids),
        (second.visual.level, second.visual.hidden_atom_indices, second.visual.hidden_polyhedron_ids),
    )

    viewer.clear_focus()

    assert viewer.left.level is HierarchyLevel.POLYHEDRA
    assert viewer.left.hidden_atom_indices == {3}
    assert viewer.left.hidden_polyhedron_ids == {"P2"}
    assert viewer.right.level is HierarchyLevel.ATOMS
    assert viewer.right.hidden_atom_indices == {0}
    assert viewer.right.hidden_polyhedron_ids == {"P7"}
    assert viewer.left.comparison_highlight is left_highlight
    assert viewer.right.comparison_highlight is right_highlight
    assert (viewer.left.show_labels, viewer.right.show_labels) == (True, True)
    assert (viewer.left.show_connector_labels, viewer.right.show_connector_labels) == (True, True)


def test_save_images_uses_same_camera_and_both_targets(monkeypatch, tmp_path) -> None:
    _application()
    monkeypatch.setattr(dual_module, "StructureViewer", FakeViewer)
    viewer = dual_module.DualStructureViewer()
    viewer.set_pair(_document("first"), _document("second"))
    viewer.left._camera = CameraState(
        (6.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        5.0,
        30.0,
        True,
    )
    viewer.right._camera = CameraState(
        (0.0, 10.0, 0.0),
        (1.0, 2.0, 3.0),
        (0.0, 1.0, 0.0),
        12.0,
        25.0,
        False,
    )
    left = tmp_path / "pair-A.png"
    right = tmp_path / "pair-B.png"

    viewer.save_images(left, right)

    assert viewer.left.saved_path == left
    assert viewer.right.saved_path == right
    assert viewer.right.applied_camera.position == pytest.approx((1.0 + sqrt(74.0), 2.0, 3.0))
    assert viewer.right.applied_camera.focal_offset == (1.0, 2.0, 3.0)
    assert viewer.right.applied_camera.parallel_scale == 12.0
