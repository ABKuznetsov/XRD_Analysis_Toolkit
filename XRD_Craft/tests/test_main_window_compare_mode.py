from __future__ import annotations

from types import SimpleNamespace

from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.motif_comparison import MatchLimits
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui.main_window import MainWindow
from crystal_viewer.ui import main_window as main_module


def _check(checked: bool) -> SimpleNamespace:
    return SimpleNamespace(isChecked=lambda: checked)


def _document(name: str) -> StructureDocument:
    sites = [AtomSite("Si1", "Si", (0.5, 0.5, 0.5))]
    structure = CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), sites, sites)
    return StructureDocument.from_structure(structure, HierarchyReport())


def _show_visual_pair(state, pair) -> None:
    state.dual_viewer.set_pair(*pair)
    MainWindow._apply_dual_label_settings(state, state.dual_viewer)
    state.viewer_stack.setCurrentWidget(state.dual_viewer)


def test_assigning_a_and_b_opens_dual_workspace() -> None:
    collection = StructureCollection()
    documents = (_document("first"), _document("second"))
    for document in documents:
        collection.add(document)
    shown = []
    paired = []
    state = SimpleNamespace(
        collection=collection,
        viewer_stack=SimpleNamespace(setCurrentWidget=shown.append),
        dual_viewer=SimpleNamespace(
            set_pair=lambda *pair: paired.append(pair),
            set_show_labels=lambda _site_labels, _connector_labels: None,
        ),
        labels_check=_check(False),
        pivot_labels_check=_check(False),
        _show_visual_pair=lambda pair: _show_visual_pair(state, pair),
        _set_comparison_tabs_visible=lambda _visible: None,
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )

    MainWindow._assign_visual_slot(state, "A", documents[0].id)
    MainWindow._assign_visual_slot(state, "B", documents[1].id)

    assert paired[-1] == documents
    assert shown[-1] is state.dual_viewer


def test_compare_button_opens_checked_pair_in_split_view() -> None:
    collection = StructureCollection(max_compared=2)
    documents = (_document("first"), _document("second"))
    for document in documents:
        collection.add(document)
        collection.set_compared(document.id, True)
    shown = []
    paired = []
    state = SimpleNamespace(
        collection=collection,
        viewer_stack=SimpleNamespace(setCurrentWidget=shown.append),
        dual_viewer=SimpleNamespace(
            set_pair=lambda *pair: paired.append(pair),
            set_show_labels=lambda _site_labels, _connector_labels: None,
        ),
        labels_check=_check(False),
        pivot_labels_check=_check(False),
        object_tree=SimpleNamespace(set_collection=lambda _collection: None),
        _show_visual_pair=lambda pair: _show_visual_pair(state, pair),
        _set_comparison_tabs_visible=lambda _visible: None,
    )

    MainWindow.show_selected_comparison(state)

    assert paired[-1] == documents
    assert shown[-1] is state.dual_viewer
    assert collection.visual_pair() == documents


def test_dual_viewer_is_created_only_when_comparison_is_requested(monkeypatch) -> None:
    added = []
    connected = []

    class FakeSignal:
        def connect(self, callback) -> None:
            connected.append(callback)

    class FakeDualViewer:
        def __init__(self) -> None:
            self.table_requested = FakeSignal()
            self.pair_swapped = FakeSignal()

    monkeypatch.setattr(main_module, "DualStructureViewer", FakeDualViewer)
    state = SimpleNamespace(
        dual_viewer=None,
        viewer_stack=SimpleNamespace(addWidget=added.append),
        show_compare_workspace=lambda: None,
        _dual_pair_swapped=lambda _first_id, _second_id: None,
    )

    viewer = MainWindow._ensure_dual_viewer(state)

    assert isinstance(viewer, FakeDualViewer)
    assert added == [viewer]
    assert connected == [state.show_compare_workspace, state._dual_pair_swapped]


def test_toolbar_commands_target_window_under_mouse_in_dual_mode() -> None:
    right = object()
    dual = SimpleNamespace(active_viewer=right)
    single = object()
    state = SimpleNamespace(
        dual_viewer=dual,
        viewer=single,
        viewer_stack=SimpleNamespace(currentWidget=lambda: dual),
    )

    assert MainWindow._command_viewer(state) is right


def test_opening_comparison_applies_labels_chosen_in_single_view() -> None:
    class FakeCheck:
        def __init__(self, checked: bool) -> None:
            self.checked = checked

        def isChecked(self) -> bool:
            return self.checked

    collection = StructureCollection()
    documents = (_document("first"), _document("second"))
    for slot, document in zip(("A", "B"), documents, strict=True):
        collection.add(document)
        collection.assign_visual(slot, document.id)
    paired = []
    label_updates = []
    dual = SimpleNamespace(
        set_pair=lambda *pair: paired.append(pair),
        set_show_labels=lambda site_labels, connector_labels: label_updates.append(
            (site_labels, connector_labels)
        ),
    )
    site_labels = FakeCheck(True)
    connector_labels = FakeCheck(True)
    state = SimpleNamespace(
        collection=collection,
        dual_viewer=dual,
        viewer_stack=SimpleNamespace(setCurrentWidget=lambda _widget: None),
        central_stack=SimpleNamespace(setCurrentWidget=lambda _widget: None),
        structure_workspace=object(),
        labels_check=site_labels,
        pivot_labels_check=connector_labels,
        _show_visual_pair=lambda pair: _show_visual_pair(state, pair),
        comparison_visual_page=object(),
        _set_comparison_tabs_visible=lambda _visible: None,
        _set_comparison_mode=lambda _widget, _tab_index: None,
    )

    MainWindow.show_visual_comparison(state)
    site_labels.checked = False
    connector_labels.checked = False
    MainWindow.show_visual_comparison(state)

    assert paired == [documents, documents]
    assert label_updates == [(True, True), (False, False)]


def test_comparison_signature_is_ordered_and_includes_content_and_exact_limits() -> None:
    documents = (_document("first"), _document("second"))
    low = MatchLimits(max_states=10, max_seconds=0.5, max_nodes=16)
    high = MatchLimits(max_states=50_000, max_seconds=5.0, max_nodes=128)
    state = SimpleNamespace(comparison_limits=low)

    forward = MainWindow._comparison_signature(state, documents)
    reverse = MainWindow._comparison_signature(state, documents[::-1])
    state.comparison_limits = high
    changed_limits = MainWindow._comparison_signature(state, documents)
    documents[1].structure.cell = UnitCell(6.0, 5.0, 5.0)
    changed_content = MainWindow._comparison_signature(state, documents)

    assert forward != reverse
    assert forward != changed_limits
    assert changed_limits != changed_content
