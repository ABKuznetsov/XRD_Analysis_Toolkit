from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.ui.theme import glass_button_style


class DatabasePanelWidget(QWidget):
    sourceToggled = Signal(str, bool)
    materialsProjectToggled = Signal(bool)
    saveMaterialsProjectRequested = Signal()
    rebuildUserIndexRequested = Signal()
    rebuildLocalPeakIndexRequested = Signal()
    clearUserLibraryRequested = Signal()
    indexCodFolderRequested = Signal()
    indexCodZipRequested = Signal()
    downloadCodArchiveRequested = Signal()
    clearCodRequested = Signal()
    updateRruffRequested = Signal()
    clearRruffRequested = Signal()
    chooseMatchPdf2FolderRequested = Signal()
    refreshMatchPdf2Requested = Signal()
    clearMatchPdf2Requested = Signal()
    clearMaterialsProjectRequested = Signal()
    clearAflowRequested = Signal()
    clearOqmdRequested = Signal()

    def __init__(
        self,
        rows: list[list[str]],
        source_states: dict[str, bool],
        materials_project_enabled: bool,
        materials_project_status_text: str,
        materials_project_api_key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_checkboxes: dict[str, QCheckBox] = {}
        self.database_table: QTableWidget | None = None
        self.materials_project_checkbox: QCheckBox | None = None
        self.materials_project_status_label: QLabel | None = None
        self.materials_project_api_key_input: QLineEdit | None = None
        self._build_ui(
            rows,
            source_states,
            materials_project_enabled,
            materials_project_status_text,
            materials_project_api_key,
        )

    def api_key(self) -> str:
        return self.materials_project_api_key_input.text().strip() if self.materials_project_api_key_input else ""

    def materials_project_enabled(self) -> bool:
        return bool(self.materials_project_checkbox and self.materials_project_checkbox.isChecked())

    def set_materials_project_status(self, text: str) -> None:
        if self.materials_project_status_label is not None:
            self.materials_project_status_label.setText(text)

    def set_materials_project_checked(self, checked: bool) -> None:
        if self.materials_project_checkbox is not None and self.materials_project_checkbox.isChecked() != checked:
            self.materials_project_checkbox.blockSignals(True)
            self.materials_project_checkbox.setChecked(checked)
            self.materials_project_checkbox.blockSignals(False)

    def set_source_checked(self, setting_key: str, checked: bool) -> None:
        checkbox = self.source_checkboxes.get(setting_key)
        if checkbox is not None and checkbox.isChecked() != checked:
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def update_row(self, source_name: str, values: list[str]) -> None:
        if self.database_table is None:
            return
        for row in range(self.database_table.rowCount()):
            name_item = self.database_table.item(row, 0)
            if name_item is None or name_item.text() != source_name:
                continue
            location = values[3] if len(values) > 3 else ""
            for column, value in enumerate(values[: self.database_table.columnCount()]):
                item = QTableWidgetItem(value)
                if location:
                    item.setToolTip(location)
                self.database_table.setItem(row, column, item)
            self.database_table.resizeColumnsToContents()
            self.database_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            return

    def _build_ui(
        self,
        rows: list[list[str]],
        source_states: dict[str, bool],
        materials_project_enabled: bool,
        materials_project_status_text: str,
        materials_project_api_key: str,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.database_table = self._table(["Database", "Status", "Details"], rows)
        self.database_table.setMinimumHeight(220)
        self.database_table.setMaximumHeight(300)
        self.database_table.setWordWrap(True)
        self.database_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.database_table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.database_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.database_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.database_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.database_table.setColumnWidth(2, 340)
        layout.addWidget(self.database_table)

        layout.addWidget(self._section_title("Databases used for search"))
        source_box = QWidget()
        source_layout = QGridLayout(source_box)
        source_layout.setContentsMargins(0, 0, 0, 0)
        for label, key, row, column in [
            ("User library", "sources/user_library", 0, 0),
            ("COD local", "sources/cod_local", 0, 1),
            ("COD online", "sources/cod_online", 1, 0),
            ("RRUFF", "sources/rruff", 1, 1),
            ("PDF-2", "sources/match_pdf2", 2, 0),
            ("AFLOW", "sources/aflow", 2, 1),
            ("OQMD", "sources/oqmd", 3, 0),
        ]:
            checkbox = QCheckBox(label)
            checkbox.setChecked(bool(source_states.get(key, False)))
            checkbox.toggled.connect(lambda checked, setting_key=key: self.sourceToggled.emit(setting_key, checked))
            self.source_checkboxes[key] = checkbox
            source_layout.addWidget(checkbox, row, column)
        layout.addWidget(source_box)

        self.materials_project_checkbox = QCheckBox("Use Materials Project in phase search")
        self.materials_project_checkbox.setChecked(materials_project_enabled)
        self.materials_project_checkbox.toggled.connect(self.materialsProjectToggled)
        layout.addWidget(self.materials_project_checkbox)

        self.materials_project_status_label = QLabel(materials_project_status_text)
        layout.addWidget(self.materials_project_status_label)

        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        self.materials_project_api_key_input = QLineEdit()
        self.materials_project_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.materials_project_api_key_input.setPlaceholderText("Materials Project API key")
        self.materials_project_api_key_input.setText(materials_project_api_key)
        save_key = QPushButton("Save API key")
        save_key.setStyleSheet(self._button_style("Save API key"))
        save_key.clicked.connect(self.saveMaterialsProjectRequested)
        key_layout.addWidget(self.materials_project_api_key_input, 1)
        key_layout.addWidget(save_key)
        layout.addWidget(key_row)

        layout.addWidget(self._section_title("Database management"))
        layout.addWidget(
            self._management_row(
                "User phase library",
                [
                    ("Update index", self.rebuildUserIndexRequested),
                    ("Clear", self.clearUserLibraryRequested),
                ],
            )
        )
        layout.addWidget(
            self._management_row(
                "Local peak SQL index",
                [
                    ("Rebuild peak index", self.rebuildLocalPeakIndexRequested),
                ],
            )
        )
        layout.addWidget(
            self._management_row(
                "COD local/bulk",
                [
                    ("Update from folder", self.indexCodFolderRequested),
                    ("Update from ZIP", self.indexCodZipRequested),
                    ("Download archive", self.downloadCodArchiveRequested),
                    ("Clear", self.clearCodRequested),
                ],
            )
        )
        layout.addWidget(
            self._management_row(
                "RRUFF powder",
                [
                    ("Update", self.updateRruffRequested),
                    ("Clear", self.clearRruffRequested),
                ],
            )
        )
        layout.addWidget(
            self._management_row(
                "PDF-2",
                [
                    ("Choose folder", self.chooseMatchPdf2FolderRequested),
                    ("Refresh", self.refreshMatchPdf2Requested),
                    ("Clear", self.clearMatchPdf2Requested),
                ],
            )
        )
        layout.addWidget(
            self._management_row(
                "AFLOW",
                [
                    ("Clear", self.clearAflowRequested),
                ],
            )
        )
        layout.addWidget(
            self._management_row(
                "OQMD",
                [
                    ("Clear", self.clearOqmdRequested),
                ],
            )
        )
        layout.addWidget(
            self._management_row(
                "Materials Project",
                [
                    ("Update settings", self.saveMaterialsProjectRequested),
                    ("Clear", self.clearMaterialsProjectRequested),
                ],
            )
        )

        help_label = QLabel(
            "Clear permanently deletes the selected local cache. This cannot be undone."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        layout.addStretch(1)

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #f1f3f4; font-weight: 700; margin-top: 6px;")
        return label

    def _management_row(self, label_text: str, actions) -> QWidget:
        row = QWidget()
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        title = QLabel(label_text)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title, 0, 0, 1, 2)
        for index, (button_text, signal) in enumerate(actions):
            button = QPushButton(button_text)
            button.setMinimumHeight(28)
            button.setStyleSheet(self._button_style(button_text))
            button.clicked.connect(signal)
            layout.addWidget(button, 1 + index // 2, index % 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return row

    def _table(self, headers: list[str], rows: list[list[str]]) -> QTableWidget:
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        for row_index, row in enumerate(rows):
            location = row[3] if len(row) > 3 else ""
            for col_index, value in enumerate(row[: len(headers)]):
                item = QTableWidgetItem(value)
                if location:
                    item.setToolTip(location)
                table.setItem(row_index, col_index, item)
        table.resizeColumnsToContents()
        table.setStyleSheet(
            "QTableWidget { gridline-color: #2b2f34; }"
            "QHeaderView::section { background: #33383e; color: #f1f3f4; padding: 4px; }"
        )
        return table

    def _button_style(self, text: str) -> str:
        if "Clear" in text:
            background, border = "#8a2d35", "#bc5963"
        elif "Download" in text:
            background, border = "#0b8043", "#35a96c"
        elif "Save" in text or "settings" in text:
            background, border = "#6f45a3", "#9972ca"
        else:
            background, border = "#2367a5", "#5a9bd8"
        return glass_button_style(background, border, padding="5px 10px", pressed_padding="6px 10px 4px 10px")
