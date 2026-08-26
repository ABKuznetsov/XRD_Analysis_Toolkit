from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QStackedWidget, QTabBar, QWidget

from crystal_viewer.analysis.comparison import ComparisonReport
from crystal_viewer.analysis import comparison as comparison_module
from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.motif_comparison import MatchLimits, MotifComparisonReport
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui.main_window import MainWindow
from crystal_viewer.ui import main_window as main_module


def _document(name: str) -> StructureDocument:
    sites = [AtomSite("Si1", "Si", (0.5, 0.5, 0.5))]
    structure = CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), sites, sites)
    return StructureDocument.from_structure(structure, HierarchyReport())


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


class _CompareWorkspace(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.report = None

    def set_report(self, report) -> None:
        self.report = report


class _DualViewer(QWidget):
    pair_swapped = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.pairs = []
        self.motif_reports = []
        self.focuses = []
        self.first_document = None
        self.second_document = None

    def set_pair(self, *pair) -> None:
        self.pairs.append(pair)
        self.first_document, self.second_document = pair

    def set_motif_report(self, report) -> None:
        self.motif_reports.append(report)

    def focus(self, command) -> None:
        self.focuses.append(command)

    def swap_documents(self) -> None:
        first, second = self.first_document, self.second_document
        self.set_pair(second, first)
        self.pair_swapped.emit(second.id, first.id)

    def set_show_labels(self, _site_labels: bool, _connector_labels: bool) -> None:
        pass


class _ComparisonNavigationState:
    _comparison_mode_tab_changed = MainWindow._comparison_mode_tab_changed
    _set_comparison_mode = MainWindow._set_comparison_mode
    _set_comparison_tabs_visible = MainWindow._set_comparison_tabs_visible
    show_compare_workspace = MainWindow.show_compare_workspace
    show_selected_comparison = MainWindow.show_selected_comparison
    show_visual_comparison = MainWindow.show_visual_comparison
    _focus_comparison = MainWindow._focus_comparison

    def _dual_pair_swapped(self, first_id: str, second_id: str) -> None:
        callback = getattr(MainWindow, "_dual_pair_swapped", None)
        if callback is not None:
            callback(self, first_id, second_id)

    def __init__(self, documents: tuple[StructureDocument, ...]) -> None:
        _application()
        self.collection = StructureCollection(max_compared=2)
        for document in documents:
            self.collection.add(document)
        for document in documents[:2]:
            self.collection.set_compared(document.id, True)
        self.collection.assign_visual("A", documents[0].id)
        self.collection.assign_visual("B", documents[1].id)
        self.structure_workspace = QWidget()
        self.analysis_workspace = QWidget()
        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.structure_workspace)
        self.central_stack.addWidget(self.analysis_workspace)
        self.comparison_visual_page = QWidget()
        self.compare_workspace = _CompareWorkspace()
        self.comparison_mode_stack = QStackedWidget()
        self.comparison_mode_stack.addWidget(self.comparison_visual_page)
        self.comparison_mode_stack.addWidget(self.compare_workspace)
        self.comparison_mode_tabs = QTabBar()
        self.comparison_mode_tabs.addTab("Visual comparison")
        self.comparison_mode_tabs.addTab("Comparison table")
        self.comparison_mode_tabs.currentChanged.connect(self._comparison_mode_tab_changed)
        self.viewer_stack = QStackedWidget()
        self.viewer_stack.addWidget(QWidget())
        self.dual_viewer = _DualViewer()
        self.dual_viewer.pair_swapped.connect(self._dual_pair_swapped)
        self.viewer_stack.addWidget(self.dual_viewer)
        self.labels_check = SimpleNamespace(isChecked=lambda: False)
        self.pivot_labels_check = SimpleNamespace(isChecked=lambda: False)
        self.object_tree = SimpleNamespace(set_collection=lambda _collection: None)
        self.statusBar = lambda: SimpleNamespace(showMessage=lambda _message: None)

    def _show_visual_pair(self, pair) -> None:
        MainWindow._show_visual_pair(self, pair)


def test_comparison_table_changes_only_center_mode() -> None:
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)

    state.show_compare_workspace()

    assert state.compare_workspace.report.document_ids == tuple(document.id for document in documents)
    assert state.central_stack.currentWidget() is state.structure_workspace
    assert state.comparison_mode_stack.currentWidget() is state.compare_workspace


def test_return_from_table_restores_split_visual_workspace() -> None:
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)
    state.show_compare_workspace()

    state.show_visual_comparison()

    assert state.central_stack.currentWidget() is state.structure_workspace
    assert state.viewer_stack.currentWidget() is state.dual_viewer
    assert state.comparison_mode_tabs.currentIndex() == 0
    assert state.comparison_mode_stack.currentWidget() is state.comparison_visual_page
    assert state.dual_viewer.pairs[-1] == documents


def test_selecting_table_tab_prepares_report_before_showing_table() -> None:
    state = _ComparisonNavigationState((_document("first"), _document("second")))

    state.comparison_mode_tabs.setCurrentIndex(1)

    assert state.compare_workspace.report.document_ids == tuple(
        document.id for document in state.collection.compared_documents()
    )
    assert state.central_stack.currentWidget() is state.structure_workspace
    assert state.comparison_mode_stack.currentWidget() is state.compare_workspace


def test_show_selected_comparison_returns_from_table_to_visual_page_for_new_pair() -> None:
    documents = (_document("first"), _document("second"), _document("third"))
    state = _ComparisonNavigationState(documents)
    state.show_compare_workspace()
    state.collection.set_compared(documents[0].id, False)
    state.collection.set_compared(documents[2].id, True)

    state.show_selected_comparison()

    assert state.dual_viewer.pairs[-1] == documents[1:]
    assert state.comparison_mode_tabs.currentIndex() == 0
    assert state.comparison_mode_stack.currentWidget() is state.comparison_visual_page


def test_table_reuses_reversed_visual_pair_instead_of_checked_order() -> None:
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)
    state.collection.assign_visual("A", documents[1].id)
    state.collection.assign_visual("B", documents[0].id)

    state.show_visual_comparison()
    state.show_compare_workspace()

    assert state.dual_viewer.pairs[-1] == documents[::-1]
    assert state.compare_workspace.report.document_ids == tuple(
        document.id for document in documents[::-1]
    )
    assert len(documents[1].comparison_cache) == 1
    assert documents[0].comparison_cache == {}


def test_visual_table_visual_reuses_one_bundle_and_passes_exact_motif_report(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)
    motif_report = object()
    matcher_calls = []
    comparison_calls = []

    def fake_cached_compare(*pair, limits=None):
        matcher_calls.append(pair)
        return motif_report

    def fake_compare_documents(pair, *, motif_report):
        comparison_calls.append((pair, motif_report))
        return ComparisonReport(
            tuple(document.id for document in pair),
            tuple(document.structure.name for document in pair),
            (),
        )

    monkeypatch.setattr(main_module, "cached_compare", fake_cached_compare)
    monkeypatch.setattr(main_module, "compare_documents", fake_compare_documents)

    state.show_visual_comparison()
    state.show_compare_workspace()
    state.show_visual_comparison()

    assert matcher_calls == [documents]
    assert comparison_calls == [(documents, motif_report)]
    assert len(state.dual_viewer.motif_reports) == 2
    assert all(report is motif_report for report in state.dual_viewer.motif_reports)
    assert state.compare_workspace.report.document_ids == tuple(
        document.id for document in documents
    )


def test_application_bundle_cache_is_directional_and_reuses_forward_report(monkeypatch) -> None:
    """Catch bypassing the motif cache when the UI revisits an ordered pair."""
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)
    application_limits = MatchLimits(
        max_states=50_000,
        max_seconds=5.0,
        max_nodes=128,
    )
    state.comparison_limits = application_limits
    compute_calls: list[tuple[str, str, MatchLimits]] = []

    def fake_compare_motifs(first, second, limits):
        compute_calls.append((first.id, second.id, limits))
        return MotifComparisonReport(
            first_document_id=first.id,
            second_document_id=second.id,
            matches=(),
            substitutions=(),
            unmatched_first=(),
            unmatched_second=(),
            approximate=False,
            states_explored=0,
        )

    monkeypatch.setattr(comparison_module, "compare_motifs", fake_compare_motifs)

    state.show_visual_comparison()
    forward_report = state._active_comparison_bundle[1]
    state.show_compare_workspace()
    state.show_visual_comparison()

    state.dual_viewer.swap_documents()
    reverse_report = state._active_comparison_bundle[1]
    state.dual_viewer.swap_documents()
    reused_forward_report = state._active_comparison_bundle[1]

    forward_ids = tuple(document.id for document in documents)
    assert reused_forward_report is forward_report
    assert reverse_report is not forward_report
    assert compute_calls == [
        (*forward_ids, application_limits),
        (*forward_ids[::-1], application_limits),
    ]


def test_application_bundle_invalidates_when_explicit_limits_change(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)
    low = MatchLimits(max_states=10, max_seconds=0.5, max_nodes=16)
    production = MatchLimits(max_states=50_000, max_seconds=5.0, max_nodes=128)
    calls: list[MatchLimits] = []

    def fake_cached_compare(first, second, *, limits):
        calls.append(limits)
        return MotifComparisonReport(
            first_document_id=first.id,
            second_document_id=second.id,
            matches=(),
            substitutions=(),
            unmatched_first=(),
            unmatched_second=(),
            approximate=False,
            states_explored=1,
        )

    monkeypatch.setattr(main_module, "cached_compare", fake_cached_compare)

    state.comparison_limits = low
    state.show_visual_comparison()
    low_bundle = state._active_comparison_bundle
    state.comparison_limits = production
    state.show_visual_comparison()
    production_bundle = state._active_comparison_bundle
    state.show_compare_workspace()
    state.show_visual_comparison()

    assert calls == [low, production]
    assert production_bundle is not low_bundle
    assert state._active_comparison_bundle is production_bundle


def test_table_first_row_focus_loads_the_same_ordered_pair_and_report() -> None:
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)
    command = object()

    state.show_compare_workspace()
    assert state.dual_viewer.pairs == []

    state._focus_comparison(command)

    assert state.dual_viewer.pairs == [documents]
    assert state.dual_viewer.motif_reports[-1] is state._active_comparison_bundle[1]
    assert state.dual_viewer.focuses == [command]
    assert state.viewer_stack.currentWidget() is state.dual_viewer


def test_dual_swap_updates_canonical_pair_table_and_focus_without_reset(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    state = _ComparisonNavigationState(documents)
    forward_ids = tuple(document.id for document in documents)
    reversed_ids = forward_ids[::-1]
    motif_reports = {forward_ids: object(), reversed_ids: object()}
    matcher_calls = []

    def fake_cached_compare(*pair, limits=None):
        matcher_calls.append(pair)
        return motif_reports[tuple(document.id for document in pair)]

    def fake_compare_documents(pair, *, motif_report):
        pair_ids = tuple(document.id for document in pair)
        assert motif_report is motif_reports[pair_ids]
        return ComparisonReport(
            tuple(document.id for document in pair),
            tuple(document.structure.name for document in pair),
            (),
        )

    monkeypatch.setattr(main_module, "cached_compare", fake_cached_compare)
    monkeypatch.setattr(main_module, "compare_documents", fake_compare_documents)
    state.show_visual_comparison()

    state.dual_viewer.swap_documents()
    state.show_compare_workspace()
    state._focus_comparison(object())

    assert state.collection.visual_pair() == documents[::-1]
    assert state.compare_workspace.report.document_ids == tuple(
        document.id for document in documents[::-1]
    )
    assert state.dual_viewer.pairs == [documents, documents[::-1]]
    assert state.dual_viewer.motif_reports[-1] is motif_reports[reversed_ids]
    assert matcher_calls == [documents, documents[::-1]]
