from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QStackedWidget, QTabBar, QWidget

from crystal_viewer.analysis.comparison import ComparisonReport
from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.motif_comparison import MatchLimits, MotifComparisonReport
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui import main_window as main_module
from crystal_viewer.ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _document(name: str) -> StructureDocument:
    sites = [AtomSite("Si1", "Si", (0.5, 0.5, 0.5))]
    structure = CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), sites, sites)
    return StructureDocument.from_structure(structure, HierarchyReport())


def _motif_report(
    pair: tuple[StructureDocument, StructureDocument],
    *,
    approximate: bool = False,
) -> MotifComparisonReport:
    return MotifComparisonReport(
        first_document_id=pair[0].id,
        second_document_id=pair[1].id,
        matches=(),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=approximate,
        states_explored=1,
        limit_reasons=("max_seconds",) if approximate else (),
    )


@dataclass
class _Job:
    work: object
    succeeded: object
    failed: object


class _Executor:
    def __init__(self) -> None:
        self.jobs: list[_Job] = []
        self.close_calls: list[int] = []

    def submit(self, work, succeeded, failed) -> None:
        self.jobs.append(_Job(work, succeeded, failed))

    def succeed(self, index: int) -> object:
        job = self.jobs[index]
        result = job.work()
        job.succeeded(result)
        return result

    def fail(self, index: int, error: BaseException) -> None:
        self.jobs[index].failed(error)

    def close(self, timeout_ms: int) -> bool:
        self.close_calls.append(timeout_ms)
        return False


class _Workspace(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.report = None
        self.statuses: list[str] = []

    def set_loading(self, text: str) -> None:
        self.report = None
        self.statuses.append(text)

    def set_status(self, text: str) -> None:
        self.statuses.append(text)

    def set_report(self, report) -> None:
        self.report = report


class _Dual(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.pairs = []
        self.first_document = None
        self.second_document = None
        self.motif_reports = []
        self.statuses: list[str] = []
        self.label_updates = []

    def set_pair(self, *pair) -> None:
        self.pairs.append(pair)
        self.first_document, self.second_document = pair

    def set_motif_report(self, report) -> None:
        self.motif_reports.append(report)

    def set_show_labels(self, site_labels: bool, connector_labels: bool) -> None:
        self.label_updates.append((site_labels, connector_labels))

    def set_comparison_status(self, text: str) -> None:
        self.statuses.append(text)


class _State:
    show_visual_comparison = MainWindow.show_visual_comparison
    show_compare_workspace = MainWindow.show_compare_workspace
    _comparison_mode_tab_changed = MainWindow._comparison_mode_tab_changed
    _set_comparison_mode = MainWindow._set_comparison_mode
    _set_comparison_tabs_visible = MainWindow._set_comparison_tabs_visible

    def __init__(self, documents, executor: _Executor) -> None:
        _application()
        self.collection = StructureCollection(max_compared=2)
        for document in documents:
            self.collection.add(document)
        for document in documents[:2]:
            self.collection.set_compared(document.id, True)
        self.collection.assign_visual("A", documents[0].id)
        self.collection.assign_visual("B", documents[1].id)
        self.comparison_limits = MatchLimits(max_states=50_000, max_seconds=5.0, max_nodes=128)
        self.structure_workspace = QWidget()
        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.structure_workspace)
        self.comparison_visual_page = QWidget()
        self.compare_workspace = _Workspace()
        self.comparison_mode_stack = QStackedWidget()
        self.comparison_mode_stack.addWidget(self.comparison_visual_page)
        self.comparison_mode_stack.addWidget(self.compare_workspace)
        self.comparison_mode_tabs = QTabBar()
        self.comparison_mode_tabs.addTab("Visual comparison")
        self.comparison_mode_tabs.addTab("Comparison table")
        self.comparison_mode_tabs.currentChanged.connect(self._comparison_mode_tab_changed)
        self.viewer_stack = QStackedWidget()
        self.viewer_stack.addWidget(QWidget())
        self.dual_viewer = _Dual()
        self.viewer_stack.addWidget(self.dual_viewer)
        self.labels_check = SimpleNamespace(isChecked=lambda: True)
        self.pivot_labels_check = SimpleNamespace(isChecked=lambda: False)
        self.status_messages: list[str] = []
        self.statusBar = lambda: SimpleNamespace(showMessage=self.status_messages.append)
        MainWindow._initialize_comparison_requests(self, executor)

    def _show_visual_pair(self, pair) -> None:
        MainWindow._show_visual_pair(self, pair)


def _patch_computation(monkeypatch, calls: list, *, approximate: bool = False) -> None:
    def cached(*pair, limits):
        calls.append(("motif", pair, limits))
        return _motif_report(pair, approximate=approximate)

    def compared(pair, *, motif_report):
        calls.append(("report", pair, motif_report))
        return ComparisonReport(
            tuple(document.id for document in pair),
            tuple(document.structure.name for document in pair),
            (),
        )

    monkeypatch.setattr(main_module, "cached_compare", cached)
    monkeypatch.setattr(main_module, "compare_documents", compared)


def test_visual_entry_shows_pair_before_background_computation_and_uses_no_modal(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    executor = _Executor()
    state = _State(documents, executor)
    calls = []
    _patch_computation(monkeypatch, calls)
    monkeypatch.setattr(
        main_module.QMessageBox,
        "information",
        lambda *_args: (_ for _ in ()).throw(AssertionError("modal used")),
    )
    monkeypatch.setattr(
        MainWindow,
        "_comparison_bundle",
        lambda *_args: (_ for _ in ()).throw(AssertionError("synchronous seam used")),
    )

    state.show_visual_comparison()

    assert state.dual_viewer.pairs == [documents]
    assert state.viewer_stack.currentWidget() is state.dual_viewer
    assert state.dual_viewer.statuses[-1] == "Comparing structures…"
    assert calls == []
    assert len(executor.jobs) == 1

    executor.succeed(0)

    assert state.dual_viewer.motif_reports[-1].exact is True
    assert state.dual_viewer.statuses[-1] == "Exact comparison ready"


def test_table_first_loads_empty_workspace_then_installs_grouped_report(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    executor = _Executor()
    state = _State(documents, executor)
    calls = []
    _patch_computation(monkeypatch, calls, approximate=True)

    state.show_compare_workspace()

    assert state.compare_workspace.report is None
    assert state.compare_workspace.statuses[-1] == "Comparing structures…"
    assert state.comparison_mode_stack.currentWidget() is state.compare_workspace
    assert calls == []

    executor.succeed(0)

    assert state.compare_workspace.report.document_ids == tuple(document.id for document in documents)
    assert state.compare_workspace.statuses[-1] == "Approximate comparison ready · max_seconds"


def test_visual_to_table_in_flight_uses_one_computation(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    executor = _Executor()
    state = _State(documents, executor)
    calls = []
    _patch_computation(monkeypatch, calls)

    state.show_visual_comparison()
    state.show_compare_workspace()

    assert len(executor.jobs) == 1
    executor.succeed(0)
    assert [kind for kind, *_rest in calls] == ["motif", "report"]
    assert state.compare_workspace.report is not None
    assert len(state.dual_viewer.motif_reports) == 1


def test_stale_pair_result_cannot_overwrite_new_pair(monkeypatch) -> None:
    documents = (_document("first"), _document("second"), _document("third"))
    executor = _Executor()
    state = _State(documents, executor)
    calls = []
    _patch_computation(monkeypatch, calls)

    state.show_visual_comparison()
    state.collection.assign_visual("A", documents[1].id)
    state.collection.assign_visual("B", documents[2].id)
    state.show_visual_comparison()

    assert len(executor.jobs) == 1
    executor.succeed(0)
    assert state.dual_viewer.motif_reports == []
    assert len(executor.jobs) == 2
    executor.succeed(1)
    executor.jobs[0].succeeded(executor.jobs[0].work())

    assert state.dual_viewer.motif_reports[-1].first_document_id == documents[1].id
    assert state.dual_viewer.motif_reports[-1].second_document_id == documents[2].id
    assert state.compare_workspace.report.document_ids == (documents[1].id, documents[2].id)


def test_failure_is_textual_not_cached_and_retry_succeeds(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    executor = _Executor()
    state = _State(documents, executor)
    calls = []
    _patch_computation(monkeypatch, calls)

    state.show_visual_comparison()
    executor.fail(0, RuntimeError("matcher exploded"))

    assert state.dual_viewer.statuses[-1] == "Comparison failed: matcher exploded"
    assert state.compare_workspace.statuses[-1] == "Comparison failed: matcher exploded"
    assert state.status_messages[-1] == "Comparison failed: matcher exploded"

    state.show_visual_comparison()
    assert len(executor.jobs) == 2
    executor.succeed(1)
    assert state.dual_viewer.statuses[-1] == "Exact comparison ready"


def test_result_installs_highlight_without_reset_and_cached_repeat_uses_no_worker(monkeypatch) -> None:
    documents = (_document("first"), _document("second"))
    executor = _Executor()
    state = _State(documents, executor)
    calls = []
    _patch_computation(monkeypatch, calls)

    state.show_visual_comparison()
    pair_calls_before_result = len(state.dual_viewer.pairs)
    labels_before_result = tuple(state.dual_viewer.label_updates)
    executor.succeed(0)

    assert len(state.dual_viewer.pairs) == pair_calls_before_result
    assert tuple(state.dual_viewer.label_updates) == labels_before_result
    assert len(state.dual_viewer.motif_reports) == 1

    state.show_compare_workspace()
    assert len(executor.jobs) == 1
    assert state.compare_workspace.report is not None


def test_close_stops_accepting_results_and_wait_is_bounded() -> None:
    documents = (_document("first"), _document("second"))
    executor = _Executor()
    state = _State(documents, executor)
    state.show_visual_comparison()

    MainWindow._close_comparison_requests(state, timeout_ms=80)
    executor.jobs[0].succeeded((_motif_report(documents), object()))

    assert executor.close_calls == [80]
    assert state.dual_viewer.motif_reports == []
