import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from crystal_viewer.analysis.reporting import Provenance
from crystal_viewer.ui.analysis_workspace import AnalysisWorkspace
from crystal_viewer.ui.report_table_model import ReportTableModel
from crystal_viewer.ui.theme import application_style
from tests.reporting_helpers import sample_report, sample_table


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_table_model_exposes_display_and_provenance_roles() -> None:
    _application()
    model = ReportTableModel(sample_table())
    index = model.index(0, 0)

    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "Al1"
    assert model.data(index, ReportTableModel.ProvenanceRole) == Provenance.REPORTED.value


def test_checking_row_changes_only_presentation_selection() -> None:
    _application()
    table = sample_table()
    model = ReportTableModel(table)

    assert model.setData(model.index(0, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert not model.rows[0].include_in_publication
    assert table.rows[0].include_in_publication
    assert table.rows[0].cells["label"].display == "Al1"


def test_workspace_loads_catalogue_and_available_table() -> None:
    _application()
    workspace = AnalysisWorkspace()
    workspace.set_report(sample_report())

    assert workspace.catalogue.topLevelItemCount() > 0
    assert workspace.table_view.model().rowCount() == 1


def test_application_theme_explicitly_styles_table_view() -> None:
    style = application_style()

    assert "QTableView {" in style
    assert "alternate-background-color" in style
    assert "QTableView::item:selected" in style
