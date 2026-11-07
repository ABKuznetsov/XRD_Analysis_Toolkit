from __future__ import annotations
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.ui.theme import glass_button_style, is_dark_theme, theme_colors
from xrd_finder.services.ccdc_service import CCDC_WEB_ENABLED, CCDC_WEB_UNAVAILABLE_MESSAGE
from xrd_finder.ui.database_descriptions import database_description


class DatabasePanelWidget(QWidget):
    sourceToggled = Signal(str, bool)
    materialsProjectToggled = Signal(bool)
    saveMaterialsProjectRequested = Signal()
    manageUserLibraryRequested = Signal()
    rebuildUserIndexRequested = Signal()
    rebuildLocalPeakIndexRequested = Signal()
    auditLocalCompositionRequested = Signal()
    exportPreparedLibraryRequested = Signal()
    importPreparedLibraryRequested = Signal()
    optimizeLibraryStorageRequested = Signal()
    clearUserLibraryRequested = Signal()
    indexCodFolderRequested = Signal()
    indexCodZipRequested = Signal()
    downloadCodArchiveRequested = Signal()
    prepareCodInorganicRequested = Signal()
    prepareCoreMofRequested = Signal()
    manageConnectionsRequested = Signal()
    readyLibrariesRequested = Signal()
    readyLibraryRequested = Signal(str)
    ccdcAccountRequested = Signal()
    ccdcPortalRequested = Signal()
    exportCodRequested = Signal()
    importCodRequested = Signal()
    clearCodRequested = Signal()
    updateRruffRequested = Signal()
    clearRruffRequested = Signal()
    chooseMatchPdf2FolderRequested = Signal()
    refreshMatchPdf2Requested = Signal()
    clearMatchPdf2Requested = Signal()
    exportMaterialsProjectRequested = Signal()
    importMaterialsProjectRequested = Signal()
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
        self.setObjectName('databaseSettingsBody')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet('QWidget#databaseSettingsBody QLabel, '
            'QWidget#databaseSettingsBody QCheckBox { font-size: 13px; }')
        self.source_checkboxes: dict[str, QCheckBox] = {}
        self.management_cards: dict[str, QWidget] = {}
        self._connected_row_names: set[str] = set()
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
        row = self.database_table.rowCount()
        for index in range(self.database_table.rowCount()):
            name_item = self.database_table.item(index, 0)
            if name_item is None or name_item.text() != source_name:
                continue
            row = index
            break
        if row == self.database_table.rowCount():
            self.database_table.insertRow(row)
        self._set_table_row(self.database_table, row, values)
        self._fit_table_height()

    def _fit_table_height(self):
        table = self.database_table
        density = getattr(self.window(), '_ui_density_factor', 1.)
        header = table.horizontalHeader()
        table.setFixedHeight(max(round(44 * density), header.sizeHint().height(), header.height())
            + sum(table.rowHeight(i) for i in range(table.rowCount())) + round(10 * density))

    def sync_connected_rows(self, rows):
        names = {row[0] for row in rows}
        for index in range(self.database_table.rowCount() - 1, -1, -1):
            item = self.database_table.item(index, 0)
            if item and item.text() in self._connected_row_names - names:
                self.database_table.removeRow(index)
        for row in rows:
            self.update_row(row[0], row)
        self._connected_row_names = names
        self._fit_table_height()

    def showEvent(self, event):
        self._fit_table_height()
        super().showEvent(event)

    def _build_ui(
        self,
        rows: list[list[str]],
        source_states: dict[str, bool],
        materials_project_enabled: bool,
        materials_project_status_text: str,
        materials_project_api_key: str,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.database_table = self._table(["Database", "Status", "Details"], rows)
        self.database_table.setObjectName('databaseOverviewTable')
        self._fit_table_height()
        self.database_table.setWordWrap(True)
        self.database_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.database_table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.database_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.database_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.database_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.database_table.setColumnWidth(2, 340)

        settings = QWidget()
        settings_layout = QHBoxLayout(settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(16)
        search_controls = QVBoxLayout()
        settings_layout.addWidget(self.database_table, 2)
        settings_layout.addLayout(search_controls, 1)
        search_controls.addWidget(self._section_title("Databases used for search"))
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
            ("CoRE MOF SI", "sources/core_mof", 3, 1),
        ]:
            checkbox = QCheckBox(label)
            description = database_description(label)
            if description:
                self._describe(checkbox, description)
            checkbox.setChecked(bool(source_states.get(key, False)))
            checkbox.toggled.connect(lambda checked, setting_key=key: self.sourceToggled.emit(setting_key, checked))
            self.source_checkboxes[key] = checkbox
            source_layout.addWidget(checkbox, row, column)
        search_controls.addWidget(source_box)

        self.materials_project_checkbox = QCheckBox("Use Materials Project in phase search")
        self.materials_project_checkbox.setChecked(materials_project_enabled)
        self.materials_project_checkbox.toggled.connect(self.materialsProjectToggled)
        self.materials_project_checkbox.setText("Use Materials Project")
        self.materials_project_checkbox.setToolTip("Use Materials Project in phase search")
        self._describe(self.materials_project_checkbox, database_description('Materials Project'))
        search_controls.addWidget(self.materials_project_checkbox)

        self.materials_project_status_label = QLabel(materials_project_status_text)
        self.materials_project_status_label.setWordWrap(True)
        search_controls.addWidget(self.materials_project_status_label)

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
        search_controls.addWidget(key_row)
        search_controls.addStretch(1)

        management = QWidget()
        management_layout = QHBoxLayout(management)
        management_layout.setContentsMargins(0, 0, 0, 0)
        management_layout.setSpacing(16)
        library_actions = QVBoxLayout()
        source_actions = QVBoxLayout()
        library_actions.addWidget(self._management_row('Additional databases',[
            ('Connections…',self.manageConnectionsRequested),
            ('Organic / MOF…',self.readyLibrariesRequested),
        ]))
        library_actions.addWidget(
            self._management_row(
                "User phase library",
                [
                    ("Manage", self.manageUserLibraryRequested),
                ],
            )
        )
        library_actions.addWidget(
            self._management_row(
                "Local diffraction index",
                [
                    ("Check composition", self.auditLocalCompositionRequested),
                    ("Recalculate", self.rebuildLocalPeakIndexRequested),
                    ("Export prepared…", self.exportPreparedLibraryRequested),
                    ("Import prepared…", self.importPreparedLibraryRequested),
                    ("Optimize storage…", self.optimizeLibraryStorageRequested),
                ],
            )
        )
        library_actions.addWidget(
            self._management_row(
                "COD local/bulk",
                [
                    ("Update from folder", self.indexCodFolderRequested),
                    ("Update from ZIP", self.indexCodZipRequested),
                    ("Download archive", self.downloadCodArchiveRequested),
                    ("Inorganic COD…", self.prepareCodInorganicRequested),
                    ("Export", self.exportCodRequested),
                    ("Import", self.importCodRequested),
                    ("Clear", self.clearCodRequested),
                ],
            )
        )
        source_actions.addWidget(self._management_row('CoRE MOF SI',[
            ('Download CIFs…',self.prepareCoreMofRequested),
        ]))
        for key, label in [('curated_cofs', 'CURATED COFs'), ('qmof', 'QMOF'), ('omdb', 'OMDB')]:
            source_actions.addWidget(self._management_row(label, [
                ('Set up…', lambda _checked=False, source=key: self.readyLibraryRequested.emit(source)),
            ]))
        ccdc_row = self._management_row('CCDC / CSD',[
            ('Sign in to CCDC…',self.ccdcAccountRequested),
            ('Open CCDC',self.ccdcPortalRequested),
        ])
        for button in ccdc_row.findChildren(QPushButton):
            if button.text() != '?':
                button.setEnabled(CCDC_WEB_ENABLED)
        source_actions.addWidget(ccdc_row)
        source_actions.addWidget(
            self._management_row(
                "RRUFF powder",
                [
                    ("Update", self.updateRruffRequested),
                    ("Clear", self.clearRruffRequested),
                ],
            )
        )
        source_actions.addWidget(
            self._management_row(
                "PDF-2",
                [
                    ("Choose folder", self.chooseMatchPdf2FolderRequested),
                    ("Refresh", self.refreshMatchPdf2Requested),
                    ("Clear", self.clearMatchPdf2Requested),
                ],
            )
        )
        source_actions.addWidget(
            self._management_row(
                "AFLOW",
                [
                    ("Clear", self.clearAflowRequested),
                ],
            )
        )
        source_actions.addWidget(
            self._management_row(
                "OQMD",
                [
                    ("Clear", self.clearOqmdRequested),
                ],
            )
        )
        library_actions.addWidget(
            self._management_row(
                "Materials Project",
                [
                    ("Update settings", self.saveMaterialsProjectRequested),
                    ("Export", self.exportMaterialsProjectRequested),
                    ("Import", self.importMaterialsProjectRequested),
                    ("Clear", self.clearMaterialsProjectRequested),
                ],
            )
        )
        # Keep complete database cards together; avoid two very tall towers of buttons.
        for temporary in (library_actions, source_actions):
            while temporary.count():
                temporary.takeAt(0)
        for labels in (
            ('Additional databases', 'User phase library', 'Local diffraction index'),
            ('COD local/bulk', 'Materials Project'),
            ('CoRE MOF SI', 'CURATED COFs', 'QMOF'),
            ('OMDB', 'CCDC / CSD', 'RRUFF powder'),
            ('PDF-2', 'AFLOW', 'OQMD'),
        ):
            column = QVBoxLayout()
            column.setSpacing(8)
            for label in labels:
                column.addWidget(self.management_cards[label])
            column.addStretch(1)
            management_layout.addLayout(column, 1)
        layout.addWidget(settings)
        layout.addWidget(self._section_title('Database management'))
        layout.addWidget(management)

        help_label = QLabel(
            "Clear permanently deletes the selected local cache. This cannot be undone."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        layout.addStretch(1)

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty('uiRole', 'sectionTitle')
        return label

    def _management_row(self, label_text: str, actions) -> QWidget:
        row = QFrame()
        row.setProperty('databaseCard', True)
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.management_cards[label_text] = row
        layout = QGridLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        title = QLabel(label_text)
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600;")
        heading = QHBoxLayout()
        heading.addWidget(title, 1)
        layout.addLayout(heading, 0, 0, 1, 2)
        description = database_description(label_text)
        first_action_row = 1
        if description:
            self._describe(row, description)
            help_button = QPushButton('?')
            help_button.setFixedSize(24, 24)
            help_button.setStyleSheet('QPushButton { padding: 0; min-height: 0; font-weight: 600; }')
            help_button.setAccessibleName('About ' + description.name)
            self._describe(help_button, description)
            help_button.clicked.connect(lambda: QToolTip.showText(
                help_button.mapToGlobal(help_button.rect().bottomLeft()), description.tooltip(), help_button))
            heading.addWidget(help_button)
            summary = QLabel(description.summary)
            summary.setWordWrap(True)
            summary.setProperty('uiRole', 'muted')
            summary.setStyleSheet('font-size: 12px;')
            layout.addWidget(summary, 1, 0, 1, 2)
            first_action_row = 2
        for index, (button_text, signal) in enumerate(actions):
            button = QPushButton(button_text)
            button.setMinimumHeight(28)
            button.setStyleSheet(self._button_style(button_text))
            if description:
                self._describe(button, description)
            button.clicked.connect(signal)
            layout.addWidget(button, first_action_row + index // 2, index % 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return row

    @staticmethod
    def _describe(widget, description):
        widget.setToolTip(description.tooltip())
        widget.setProperty('databaseHelpName', description.name)
        widget.setProperty('databaseHelpDetails', description.details)
        widget.setProperty('databaseHelpUsage', description.usage)

    def _set_table_row(self, table, row_index, row):
        location = row[3] if len(row) > 3 else ''
        description = database_description(row[0])
        tip = description.tooltip() if description else ''
        if location and location not in tip:
            tip = tip.replace('</qt>', '<p>' + escape(location) + '</p></qt>') if tip else escape(location)
        for col_index, value in enumerate(row[:table.columnCount()]):
            item = QTableWidgetItem(value)
            item.setToolTip(tip)
            table.setItem(row_index, col_index, item)

    def _table(self, headers: list[str], rows: list[list[str]]) -> QTableWidget:
        table = QTableWidget(len(rows), len(headers))
        table.setStyleSheet('QTableWidget { font-size: 13px; }')
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        for row_index, row in enumerate(rows):
            self._set_table_row(table, row_index, row)
        table.resizeColumnsToContents()
        table.setShowGrid(False)
        table.verticalHeader().setMinimumSectionSize(12)
        table.verticalHeader().setDefaultSectionSize(24)
        return table

    def _button_style(self, text: str) -> str:
        colors = theme_colors(is_dark_theme(self))
        if "Clear" in text:
            background, border, foreground = '#87394b', '#b65d72', '#ffffff'
        elif "Download" in text or "Save" in text:
            background, border, foreground = '#087f69', '#119b7f', '#ffffff'
        else:
            background, border, foreground = colors['alt'], colors['border'], colors['text']
        return glass_button_style(background, border, foreground, padding='4px 10px')
