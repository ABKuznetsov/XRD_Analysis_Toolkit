from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from crystal_viewer.analysis.reporting import (
    Availability,
    REPORT_PRESETS,
    TABLE_DEFINITIONS,
    StructureReport,
    report_preset,
)
from crystal_viewer.ui.report_table_model import ReportTableModel


class AnalysisWorkspace(QWidget):
    object_refs_selected = Signal(tuple)
    export_csv_requested = Signal(str)
    export_json_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.report: StructureReport | None = None
        self._models: dict[str, ReportTableModel] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter()
        root.addWidget(splitter)

        catalogue_panel = QFrame()
        catalogue_layout = QVBoxLayout(catalogue_panel)
        title = QLabel("ANALYSIS CATALOGUE")
        title.setObjectName("eyebrow")
        catalogue_layout.addWidget(title)
        self.preset_combo = QComboBox()
        for preset in REPORT_PRESETS:
            self.preset_combo.addItem(preset.title, preset.id)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        catalogue_layout.addWidget(self.preset_combo)
        self.catalogue = QTreeWidget()
        self.catalogue.setHeaderLabels(("Table", "State"))
        self.catalogue.currentItemChanged.connect(self._catalogue_changed)
        catalogue_layout.addWidget(self.catalogue, 1)
        splitter.addWidget(catalogue_panel)

        centre = QFrame()
        centre_layout = QVBoxLayout(centre)
        self.table_title = QLabel("Select a report table")
        self.table_title.setObjectName("selectedTitle")
        centre_layout.addWidget(self.table_title)
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)
        self.table_view.clicked.connect(self._row_selected)
        centre_layout.addWidget(self.table_view, 1)
        splitter.addWidget(centre)

        properties = QFrame()
        properties_layout = QVBoxLayout(properties)
        heading = QLabel("TABLE PROPERTIES")
        heading.setObjectName("eyebrow")
        properties_layout.addWidget(heading)
        form = QFormLayout()
        self.availability_label = QLabel("—")
        self.method_label = QLabel("—")
        self.method_label.setWordWrap(True)
        self.warning_label = QLabel("—")
        self.warning_label.setWordWrap(True)
        form.addRow("Availability", self.availability_label)
        form.addRow("Method", self.method_label)
        form.addRow("Warnings", self.warning_label)
        properties_layout.addLayout(form)
        self.csv_button = QPushButton("Export current table as CSV…")
        self.json_button = QPushButton("Export report as JSON…")
        self.csv_button.clicked.connect(self._request_csv)
        self.json_button.clicked.connect(self.export_json_requested)
        properties_layout.addWidget(self.csv_button)
        properties_layout.addWidget(self.json_button)
        properties_layout.addStretch()
        splitter.addWidget(properties)
        splitter.setSizes((260, 760, 280))

    def set_report(self, report: StructureReport) -> None:
        self.report = report
        self._models.clear()
        self.catalogue.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        first_available: QTreeWidgetItem | None = None
        for definition in TABLE_DEFINITIONS:
            group = groups.get(definition.group)
            if group is None:
                group = QTreeWidgetItem((definition.group, ""))
                groups[definition.group] = group
                self.catalogue.addTopLevelItem(group)
            table = report.tables.get(definition.id)
            available = table is not None and table.availability is Availability.AVAILABLE
            state = "Available" if available else f"Stage {definition.stage}"
            item = QTreeWidgetItem((definition.title, state))
            item.setData(0, Qt.ItemDataRole.UserRole, definition.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            group.addChild(item)
            if available and first_available is None:
                first_available = item
        self.catalogue.expandAll()
        self._preset_changed(self.preset_combo.currentIndex())
        if first_available is not None:
            self.catalogue.setCurrentItem(first_available)

    def _catalogue_changed(self, current, _previous) -> None:
        if current is None or self.report is None:
            return
        table_id = current.data(0, Qt.ItemDataRole.UserRole)
        if not table_id or table_id not in self.report.tables:
            return
        table = self.report.tables[table_id]
        model = self._models.setdefault(table_id, ReportTableModel(table, self))
        self.table_view.setModel(model)
        self.table_view.resizeColumnsToContents()
        self.table_title.setText(table.title)
        self.availability_label.setText(table.availability.value)
        self.method_label.setText(table.method or table.unavailable_reason or "Source CIF")
        self.warning_label.setText("\n".join(w.message for w in table.warnings) or "None")
        self.csv_button.setEnabled(table.availability is Availability.AVAILABLE)

    def _row_selected(self, index) -> None:
        model = self.table_view.model()
        if isinstance(model, ReportTableModel) and index.isValid():
            self.object_refs_selected.emit(model.rows[index.row()].object_refs)

    def _request_csv(self) -> None:
        current = self.catalogue.currentItem()
        if current is not None:
            table_id = current.data(0, Qt.ItemDataRole.UserRole)
            if table_id:
                self.export_csv_requested.emit(table_id)

    def _preset_changed(self, _index: int) -> None:
        preset_id = self.preset_combo.currentData()
        if not preset_id:
            return
        selected = set(report_preset(str(preset_id)).table_ids)
        for group_index in range(self.catalogue.topLevelItemCount()):
            group = self.catalogue.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                item = group.child(child_index)
                table_id = item.data(0, Qt.ItemDataRole.UserRole)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if table_id in selected else Qt.CheckState.Unchecked,
                )

    def selected_table_ids(self) -> tuple[str, ...]:
        selected: list[str] = []
        for group_index in range(self.catalogue.topLevelItemCount()):
            group = self.catalogue.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                item = group.child(child_index)
                if item.checkState(0) is Qt.CheckState.Checked:
                    table_id = item.data(0, Qt.ItemDataRole.UserRole)
                    if table_id:
                        selected.append(str(table_id))
        return tuple(selected)
