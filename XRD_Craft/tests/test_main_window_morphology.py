from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QDockWidget, QMainWindow, QWidget

from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui.main_window import MainWindow
from crystal_viewer.ui import main_window as main_module
from crystal_viewer.analysis.morphology_state import MorphologyEditState
from crystal_viewer.analysis.morphology_state import LoadedMorphologyState


def _document() -> StructureDocument:
    site = AtomSite("Si1", "Si", (0.0, 0.0, 0.0))
    structure = CrystalStructure("sample", UnitCell(5.0, 5.0, 5.0), [site], [site])
    return StructureDocument.from_structure(structure, HierarchyReport())


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_morphology_tab_replaces_only_central_content_and_keeps_side_workspace() -> None:
    document = _document()
    shown = []
    installed = []
    morphology = SimpleNamespace(set_document=installed.append)
    state = SimpleNamespace(
        active_document_id=document.id,
        collection=SimpleNamespace(documents={document.id: document}),
        central_stack=SimpleNamespace(setCurrentWidget=lambda widget: shown.append(("central", widget))),
        structure_workspace=object(),
        comparison_mode_stack=SimpleNamespace(setCurrentWidget=lambda widget: shown.append(("page", widget))),
        morphology_workspace=morphology,
        _set_comparison_tabs_visible=lambda visible: shown.append(("tabs", visible)),
        statusBar=lambda: SimpleNamespace(showMessage=lambda text: shown.append(("status", text))),
    )

    MainWindow._show_morphology(state)

    assert installed == [document]
    assert ("central", state.structure_workspace) in shown
    assert ("page", morphology) in shown
    assert ("tabs", False) in shown


def test_view_tab_routes_morphology_without_coercing_to_hierarchy_level() -> None:
    calls = []
    state = SimpleNamespace(
        view_tabs=SimpleNamespace(tabData=lambda _index: "morphology"),
        _show_morphology=lambda: calls.append("morphology"),
    )

    MainWindow._view_tab_changed(state, 6)

    assert calls == ["morphology"]


def test_save_morphology_writes_sidecar_without_changing_cif(monkeypatch, tmp_path) -> None:
    source = tmp_path / "sample.cif"
    source.write_text("data_sample\n", encoding="utf-8")
    before = source.read_bytes()
    target = tmp_path / "sample.morphology.json"
    site = AtomSite("Si1", "Si", (0.0, 0.0, 0.0))
    structure = CrystalStructure(
        "sample",
        UnitCell(5.0, 5.0, 5.0),
        [site],
        [site],
        source_path=source,
    )
    messages = []
    state = SimpleNamespace(
        structure=structure,
        current_path=source,
        morphology_workspace=SimpleNamespace(state=MorphologyEditState()),
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
    )
    monkeypatch.setattr(
        main_module.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )

    MainWindow.save_morphology_model(state)

    assert target.is_file()
    assert source.read_bytes() == before
    assert "Saved" in messages[-1]


def test_source_mismatch_is_offered_as_non_modal_manual_model(monkeypatch, tmp_path) -> None:
    document = _document()
    offered = []
    state = SimpleNamespace(
        structure=document.structure,
        morphology_workspace=SimpleNamespace(
            offer_incompatible_state=lambda loaded, message: offered.append((loaded, message))
        ),
    )
    path = tmp_path / "other.morphology.json"
    path.write_text("{}", encoding="utf-8")
    loaded_state = MorphologyEditState(max_index=4)
    monkeypatch.setattr(main_module.QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(path), ""))
    monkeypatch.setattr(
        main_module,
        "load_morphology_state",
        lambda *_a, **_k: LoadedMorphologyState(loaded_state, False, "Source mismatch"),
    )

    MainWindow.open_morphology_model(state)

    assert offered == [(loaded_state, "Source mismatch")]


def test_file_menu_owns_context_enabled_morphology_actions() -> None:
    _application()
    class MenuHarness(MainWindow):
        def __init__(self) -> None:
            QMainWindow.__init__(self)
            self.cell_check = QCheckBox()
            self.axes_check = QCheckBox()
            self.labels_check = QCheckBox()
            self.output_dock = QDockWidget()
            self.summary_bar = QWidget()
            self.series_report = None
            self.structure = None
            self.morphology_workspace = SimpleNamespace(current_model=None)
            self._build_actions()

    window = MenuHarness()
    try:
        assert window.open_morphology_action.text() == "Open Morphology Model…"
        assert window.save_morphology_action.text() == "Save Morphology Model…"
        assert window.morphology_csv_action.text() == "Morphology CSV…"
        assert window.morphology_json_action.text() == "Morphology JSON…"
        assert window.morphology_png_action.text() == "Morphology PNG…"
        assert not window.open_morphology_action.isEnabled()
        assert not window.morphology_csv_action.isEnabled()

        window.structure = _document().structure
        window.morphology_workspace.current_model = object()
        window._update_morphology_actions()

        assert window.open_morphology_action.isEnabled()
        assert window.save_morphology_action.isEnabled()
        assert window.morphology_csv_action.isEnabled()
        assert window.morphology_json_action.isEnabled()
        assert window.morphology_png_action.isEnabled()
    finally:
        window.deleteLater()
