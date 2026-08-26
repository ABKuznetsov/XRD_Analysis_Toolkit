from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView, QPushButton, QTableView, QWidget
from PySide6.QtGui import QStandardItemModel

from crystal_viewer.ui.morphology_workspace import MorphologyWorkspace


class ImmediateExecutor:
    def submit(self, work, succeeded, failed) -> None:
        try:
            succeeded(work())
        except BaseException as error:
            failed(error)

    def close(self, _timeout_ms: int) -> bool:
        return True


class FakeViewer(QWidget):
    def set_model(self, *_args, **_kwargs) -> None:
        pass

    def select_family(self, *_args) -> None:
        pass


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_lower_editor_has_three_full_width_contextual_table_tabs() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)

    assert workspace.editor_tabs.count() == 3
    assert tuple(workspace.editor_tabs.tabText(index) for index in range(3)) == (
        "Facets", "Twins", "Striation"
    )
    for table in (workspace.table, workspace.twin_table, workspace.striation_table):
        table.setModel(QStandardItemModel(0, 1, table))
        assert table.horizontalHeader().sectionResizeMode(0) is QHeaderView.ResizeMode.Stretch

    assert workspace.table.parentWidget() is workspace.facets_page
    assert workspace.twin_table.parentWidget() is workspace.twins_page
    assert workspace.striation_table.parentWidget() is workspace.striation_page
    assert workspace.twin_editor.parentWidget() is workspace.twins_page


def test_lower_editor_has_no_duplicate_file_actions() -> None:
    _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)

    button_texts = tuple(button.text() for button in workspace.findChildren(QPushButton))
    assert not any(
        forbidden in text
        for forbidden in ("Save model", "Open model", "Export CSV", "Export PNG")
        for text in button_texts
    )
    assert workspace.add_family_button.parentWidget() is workspace.facets_page
    assert workspace.marking_apply_button.parentWidget() is workspace.striation_page


def test_lower_editor_has_a_grabbable_splitter_and_explicit_collapse_restore() -> None:
    application = _application()
    workspace = MorphologyWorkspace(executor=ImmediateExecutor(), viewer_factory=FakeViewer)
    workspace.resize(1400, 900)
    workspace.show()
    application.processEvents()
    original = tuple(workspace.splitter.sizes())

    assert workspace.splitter.handleWidth() >= 10
    workspace.panel_toggle_button.click()
    application.processEvents()

    assert workspace.splitter.sizes()[1] == 0
    assert "Show" in workspace.panel_toggle_button.text()

    workspace.panel_toggle_button.click()
    application.processEvents()

    restored = workspace.splitter.sizes()
    assert restored[0] > 0
    assert restored[1] >= min(original[1], 200)
    assert "Hide" in workspace.panel_toggle_button.text()
