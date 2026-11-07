"""One connection editor for local CIF libraries and mapped online sources."""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QDialogButtonBox,QFileDialog,QFormLayout,
    QGroupBox,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout)

from xrd_finder.services.library_connections import LibraryConnection,load_connections,save_connections
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog

KIND_LABELS = {'folder':'CIF folder','zip':'CIF ZIP file','zip_url':'Online CIF ZIP','json_api':'JSON API → CIF'}


class ConnectionEditor(ScreenBoundDialog):
    def __init__(self, owner, connection=None):
        super().__init__(owner)
        self.connection=connection or LibraryConnection(name='',kind='folder',location='')
        self.setWindowTitle('Database connection');self.resize(650,600)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.name=QLineEdit(self.connection.name);form.addRow('Name',self.name)
        self.kind=QComboBox()
        for key,label in KIND_LABELS.items():self.kind.addItem(label,key)
        self.kind.setCurrentIndex(self.kind.findData(self.connection.kind));form.addRow('Connection',self.kind)
        self.kind.setEnabled(not self.connection.preset)
        row=QHBoxLayout();self.location=QLineEdit(self.connection.location)
        self.browse=QPushButton('Browse…');self.browse.clicked.connect(self._browse)
        row.addWidget(self.location,1);row.addWidget(self.browse);form.addRow('Location / URL',row)
        self.enabled=QCheckBox('Use in search');self.enabled.setChecked(self.connection.enabled)
        form.addRow('',self.enabled)
        self.auth=QGroupBox('Authentication (optional)');auth=QFormLayout(self.auth)
        self.header=QLineEdit(self.connection.auth_header)
        self.key=QLineEdit(self.connection.api_key);self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('Full header value, e.g. Bearer …')
        auth.addRow('Header',self.header);auth.addRow('Value',self.key);layout.addWidget(self.auth)
        self.mapping=QGroupBox('JSON fields');mapping=QFormLayout(self.mapping);self.fields={}
        for key,label in [('results_path','Results array'),('id_field','Card ID'),('formula_field','Formula'),
                          ('name_field','Phase name'),('cif_field','CIF URL')]:
            edit=QLineEdit(getattr(self.connection,key));self.fields[key]=edit;mapping.addRow(label,edit)
            edit.setToolTip('Nested fields use dots, for example data.cards or files.cif. No code is executed.')
        layout.addWidget(self.mapping)
        self.note=QLabel();self.note.setWordWrap(True);layout.addWidget(self.note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._update_kind);self._update_kind()

    def _update_kind(self):
        kind=self.kind.currentData();online=kind in {'zip_url','json_api'}
        self.browse.setVisible(not online);self.auth.setVisible(online);self.mapping.setVisible(kind=='json_api')
        self.location.setReadOnly(bool(self.connection.preset and online))
        if self.connection.preset:self.auth.hide()
        self.location.setPlaceholderText('https://example.org/search?q={query}&limit={limit}' if kind=='json_api' else '')
        self.note.setText('GET API: use {query} and {limit} in the search URL. The response must contain an array of cards with IDs and CIF links. '
            'One response, up to 500 cards per query. Formula and name are optional; field paths are case-sensitive. '
            'The API key is stored in your local application settings and is not included in library exports.' if kind=='json_api'
            else 'New and changed CIFs are calculated in background processes. Existing ready cards are reused. '
            'Use Prepare after saving this connection. Original files are not modified.')

    def _browse(self):
        if self.kind.currentData()=='folder':path=QFileDialog.getExistingDirectory(self,'CIF folder')
        else:path,_=QFileDialog.getOpenFileName(self,'CIF ZIP',str(Path.home()),'ZIP (*.zip)')
        if path:self.location.setText(path)

    def _save(self):
        try:
            self.connection=replace(self.connection,name=self.name.text().strip(),kind=self.kind.currentData(),
                location=self.location.text().strip(),enabled=self.enabled.isChecked(),api_key=self.key.text(),
                auth_header=self.header.text().strip(),**{k:v.text().strip() for k,v in self.fields.items()}).validate()
        except ValueError as error:
            QMessageBox.warning(self,'Database connection',str(error));return
        self.accept()


class LibraryConnectionsDialog(ScreenBoundDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner
        self.setWindowTitle('Database connections');self.resize(850,450)
        layout=QVBoxLayout(self)
        note=QLabel('Connect CIF folders, ZIP archives or a JSON API. Imported cards use the same local search, Match and Gain cache.')
        note.setWordWrap(True);layout.addWidget(note)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Use','Database','Connection','Cards'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemChanged.connect(self._toggle);self.table.itemDoubleClicked.connect(lambda _:self.edit())
        self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        row=QHBoxLayout();layout.addLayout(row)
        for label,callback in [('Add database…',self.add),('Edit…',self.edit),('Prepare',self.prepare),
                               ('Remove connection',self.remove),('Close',self.close)]:
            button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
        self.refresh()
        ready=QPushButton('Organic and MOF databases…')
        ready.clicked.connect(self.owner._show_ready_libraries)
        layout.insertWidget(1,ready)

    def refresh(self):
        self.connections=load_connections(self.owner.settings);self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.connections))
            for row,c in enumerate(self.connections):
                check=QTableWidgetItem();check.setFlags(check.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Checked if c.enabled else Qt.CheckState.Unchecked)
                self.table.setItem(row,0,check)
                for col,text in enumerate([c.name,KIND_LABELS[c.kind],str(self.owner.local_phase_cache.source_count(c.source))],1):
                    self.table.setItem(row,col,QTableWidgetItem(text))
            self.table.resizeColumnsToContents()
        finally:self.table.blockSignals(False)
        self.owner._refresh_custom_source_names()

    def _save(self):
        save_connections(self.owner.settings,self.connections);self.refresh()

    def _toggle(self,item):
        if item.column()!=0:return
        self.connections[item.row()].enabled=item.checkState()==Qt.CheckState.Checked;self._save()

    def add(self):
        editor=ConnectionEditor(self)
        if editor.exec()==QDialog.DialogCode.Accepted:
            self.connections.append(editor.connection);self._save()

    def edit(self):
        row=self.table.currentRow()
        if row<0:return
        editor=ConnectionEditor(self,self.connections[row])
        if editor.exec()==QDialog.DialogCode.Accepted:
            self.connections[row]=editor.connection;self._save()

    def prepare(self):
        row=self.table.currentRow()
        if row<0:return
        connection=self.connections[row]
        if connection.kind=='json_api':
            QMessageBox.information(self,'JSON API','Connection saved. Use Search database or Search by formula in Finder; returned CIFs are prepared in the background.');return
        self.owner._prepare_library_connection(connection)

    def remove(self):
        row=self.table.currentRow()
        if row<0:return
        connection=self.connections[row]
        if self.owner.local_phase_cache.source_count(connection.source):
            # Keep an explicit disabled record, so retained cards do not become
            # enabled as an unconfigured imported library on the next search.
            connection.enabled=False
            QMessageBox.information(self,'Database connection','The connection is disabled. Cached cards are retained.')
        else:self.connections.pop(row)
        self._save()
