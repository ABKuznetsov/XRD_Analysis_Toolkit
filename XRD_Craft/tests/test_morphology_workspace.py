from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QWidget

from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.analysis.morphology_state import MorphologyEditState
from crystal_viewer.analysis.surface_markings import SurfaceMarking, SurfaceMarkingKind
from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec
from crystal_viewer.ui.striation_table_model import StriationEdit
from crystal_viewer.ui.morphology_table_model import MorphologyColumn
from crystal_viewer.ui.morphology_workspace import MorphologyWorkspace

ROOT = Path(__file__).resolve().parents[1]


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


class ImmediateExecutor:
    def submit(self, work, succeeded, failed) -> None:
        try:
            succeeded(work())
        except BaseException as error:
            failed(error)

    def close(self, _timeout_ms: int) -> bool:
        return True


class HoldableExecutor(ImmediateExecutor):
    def __init__(self) -> None:
        self.hold = False
        self.jobs = []

    def submit(self, work, succeeded, failed) -> None:
        if self.hold:
            self.jobs.append((work, succeeded, failed))
            return
        super().submit(work, succeeded, failed)


class FakeViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.model = None
        self.selected_family = None

    def set_model(self, model, *, reset_camera=False) -> None:
        self.model = model

    def select_family(self, family) -> None:
        self.selected_family = family

    def clear(self) -> None:
        self.model = None


def _document() -> StructureDocument:
    structure = load_cif(ROOT / "tests" / "data" / "morphology" / "body_centered.cif")
    return StructureDocument.from_structure(structure, HierarchyReport())


def test_workspace_installs_bfdh_result_as_selectable_text_and_table() -> None:
    _application()
    workspace = MorphologyWorkspace(
        executor=ImmediateExecutor(),
        viewer_factory=FakeViewer,
    )
    workspace.set_document(_document())

    assert workspace.splitter.orientation() is Qt.Orientation.Vertical
    assert workspace.splitter.childrenCollapsible()
    assert workspace.lower_panel.minimumHeight() == 0
    assert workspace.editor_tabs.minimumHeight() == 0
    assert workspace.status_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert "BFDH" in workspace.method_label.text()
    assert workspace.table.model().rowCount() > 0
    assert workspace.viewer.model is not None
    assert (
        workspace.table.horizontalHeader().sectionResizeMode(0)
        is QHeaderView.ResizeMode.Stretch
    )
    model = workspace.table.model()
    checked = {
        model.data(model.index(row, 0), model.FamilyRole)
        for row in range(model.rowCount())
        if model.data(model.index(row, MorphologyColumn.ENABLED), Qt.ItemDataRole.CheckStateRole)
        == Qt.CheckState.Checked
    }
    assert checked == set(workspace.state.primary_families)
    assert workspace.state.primary_initialized
    assert len(checked) < model.rowCount()
    assert "80%" in workspace.primary_coverage_label.text()


def test_enabling_additional_family_preserves_complete_palette() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    workspace.set_document(_document())
    model = workspace.table.model()
    before = {
        model.data(model.index(row, 0), model.FamilyRole): model.data(
            model.index(row, MorphologyColumn.HKL), model.ColorRole
        )
        for row in range(model.rowCount())
    }
    row = next(
        row
        for row in range(model.rowCount())
        if model.data(model.index(row, MorphologyColumn.ENABLED), Qt.ItemDataRole.CheckStateRole)
        == Qt.CheckState.Unchecked
    )

    assert model.setData(
        model.index(row, MorphologyColumn.ENABLED),
        Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )

    rebuilt = workspace.table.model()
    after = {
        rebuilt.data(rebuilt.index(row, 0), rebuilt.FamilyRole): rebuilt.data(
            rebuilt.index(row, MorphologyColumn.HKL), rebuilt.ColorRole
        )
        for row in range(rebuilt.rowCount())
    }
    assert after == before


def test_workspace_rho_edit_rebuilds_and_marks_manual() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    document = _document()
    workspace.set_document(document)
    model = workspace.table.model()
    index = model.index(0, MorphologyColumn.CURRENT_RHO)
    original = float(model.data(index, Qt.ItemDataRole.EditRole))

    assert model.setData(index, original * 1.25, Qt.ItemDataRole.EditRole)

    rebuilt = workspace.table.model()
    assert rebuilt.data(rebuilt.index(0, MorphologyColumn.STATE)) == "manual"
    assert document.morphology_state is not None
    assert workspace.viewer.model is not None


def test_selected_facet_has_synchronized_relative_slider_and_exact_distance() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    workspace.set_document(_document())
    model = workspace.table.model()
    plane = model.model.planes[0]

    assert workspace.distance_slider.minimum() == 20
    assert workspace.distance_slider.maximum() == 300
    assert not workspace.distance_slider.isEnabled()

    workspace._row_selected(model.index(0, MorphologyColumn.HKL))

    assert workspace.distance_slider.isEnabled()
    assert workspace.distance_slider.value() == 100
    assert workspace.distance_spin.value() == pytest.approx(plane.rho)
    assert "ρ₀" in workspace.selected_facet_label.text()


def test_distance_slider_rebuilds_selected_family_and_keeps_selection() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    document = _document()
    workspace.set_document(document)
    model = workspace.table.model()
    family = model.data(model.index(0, 0), model.FamilyRole)
    rho0 = model.model.planes[0].rho0
    workspace._row_selected(model.index(0, MorphologyColumn.HKL))

    workspace.distance_slider.setValue(75)

    override = workspace.state.override_for(family)
    assert override is not None
    assert override.rho == pytest.approx(0.75 * rho0)
    assert document.morphology_state == workspace.state
    assert workspace.distance_spin.value() == pytest.approx(0.75 * rho0)
    assert workspace._selected_family() == family


def test_added_family_becomes_selected_for_distance_editing() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    workspace.set_document(_document())

    workspace.hkl_input.setText("2 1 0")
    workspace.add_family_button.click()

    assert workspace.distance_slider.isEnabled()
    assert (2, 1, 0) in next(
        plane.family.equivalents
        for plane in workspace.current_model.planes
        if plane.family.hkl == workspace._selected_family()
    )


def test_replacing_document_object_with_same_id_clears_stale_distance_editor() -> None:
    _application()
    executor = HoldableExecutor()
    workspace = MorphologyWorkspace(executor=executor, viewer_factory=FakeViewer)
    first = _document()
    workspace.set_document(first)
    model = workspace.table.model()
    workspace._row_selected(model.index(0, MorphologyColumn.HKL))
    second_structure = load_cif(
        ROOT / "tests" / "data" / "morphology" / "primitive_cubic.cif"
    )
    second = StructureDocument.from_structure(second_structure, HierarchyReport())
    second.id = first.id
    executor.hold = True

    workspace.set_document(second)

    assert workspace.document is second
    assert workspace.current_model is None
    assert not workspace.distance_slider.isEnabled()
    assert workspace._selected_facet_family is None


def test_workspace_adds_and_removes_user_plane_family() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    workspace.set_document(_document())

    workspace.hkl_input.setText("2 1 0")
    workspace.add_family_button.click()

    model = workspace.table.model()
    row = next(
        row
        for row in range(model.rowCount())
        if (2, 1, 0) in model.model.planes[row].family.equivalents
    )
    workspace.table.selectRow(row)
    workspace.remove_family_button.click()

    assert workspace.state.override_for((2, 1, 0)) is None


def test_incompatible_state_offer_is_selectable_and_applies_without_modal() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    document = _document()
    workspace.set_document(document)
    loaded = MorphologyEditState(max_index=4).with_distance((1, 0, 0), 1.7)

    workspace.offer_incompatible_state(loaded, "Source mismatch")

    assert workspace.mismatch_bar.isVisibleTo(workspace)
    assert workspace.mismatch_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    workspace.apply_mismatch_button.click()
    assert workspace.state == loaded
    assert document.morphology_state == loaded
    assert not workspace.mismatch_bar.isVisibleTo(workspace)


def test_incompatible_state_offer_is_cleared_when_active_document_changes() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    first = _document()
    second_structure = load_cif(
        ROOT / "tests" / "data" / "morphology" / "primitive_cubic.cif"
    )
    second = StructureDocument.from_structure(second_structure, HierarchyReport())
    offered = MorphologyEditState(max_index=4).with_distance((1, 0, 0), 1.7)
    workspace.set_document(first)
    workspace.offer_incompatible_state(offered, "Source mismatch")

    workspace.set_document(second)
    workspace.apply_mismatch_button.click()

    assert workspace._pending_incompatible_state is None
    assert not workspace.mismatch_bar.isVisibleTo(workspace)
    assert second.morphology_state != offered


def test_workspace_builds_twin_geometry_and_invalid_edit_keeps_last_valid_result() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    workspace.set_document(_document())
    valid = TwinAggregateSpec(
        TwinAggregateKind.CONTACT,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 1, 0)),
    )

    workspace._twin_spec_changed(valid)

    installed = workspace.current_calculation
    assert installed.twin_aggregate is not None
    assert len(installed.twin_aggregate.domains) == 2
    invalid = TwinAggregateSpec(
        TwinAggregateKind.CONTACT,
        valid.law,
        composition_offset=1_000_000.0,
    )
    workspace._twin_spec_changed(invalid)
    assert workspace.current_calculation is installed
    assert workspace.state == installed.state
    assert workspace.document.morphology_state == installed.state
    assert "not changed" in workspace.status_label.text().lower()


def test_line_width_only_edit_reuses_installed_morphology_and_twin_geometry() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    workspace.set_document(_document())
    twin = TwinAggregateSpec(
        TwinAggregateKind.POLYSYNTHETIC,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 1, 0)),
        composition_plane_hkl=(1, 1, 0),
        lamella_count=4,
    )
    workspace._twin_spec_changed(twin)
    family = workspace.current_model.planes[0].family.hkl
    initial = SurfaceMarking(family, SurfaceMarkingKind.INDUCTION, 4, 1.5)
    workspace._striation_edit_requested(StriationEdit(family, initial))
    model = workspace.current_model
    aggregate = workspace.current_calculation.twin_aggregate

    workspace._striation_edit_requested(
        StriationEdit(family, SurfaceMarking(family, SurfaceMarkingKind.INDUCTION, 4, 3.0))
    )

    assert workspace.current_model is model
    assert workspace.current_calculation.twin_aggregate is aggregate
    assert workspace.state.markings[0].line_width == 3.0
