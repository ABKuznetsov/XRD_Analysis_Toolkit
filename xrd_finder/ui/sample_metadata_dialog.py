"""Edit optional per-pattern provenance without changing measured data."""
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QCheckBox, QDateTimeEdit, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit

from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog, scrollable_dialog_body


class SampleMetadataDialog(ScreenBoundDialog):
    def __init__(self, sample_name, metadata, parent=None, *, focus_field='sample_id', notes=''):
        super().__init__(parent)
        self.setWindowTitle('Sample details')
        self.resize(500, 430)
        self._focus_field = focus_field
        self._original_datetime = str(metadata.get('sample_datetime') or '')
        self._datetime_changed = False
        layout = scrollable_dialog_body(self)
        name = QLabel(str(sample_name))
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setWordWrap(True)
        name.setProperty('uiRole', 'sectionTitle')
        layout.addWidget(name)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.sample_id_input = QLineEdit(str(metadata.get('sample_id') or ''))
        self.sample_id_input.setAccessibleName('Sample ID')
        form.addRow('Sample ID', self.sample_id_input)
        self.datetime_enabled = QCheckBox('Record measurement date/time')
        self.datetime_input = QDateTimeEdit()
        self.datetime_input.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
        self.datetime_input.setCalendarPopup(True)
        self.datetime_input.setAccessibleName('Measurement date and time')
        parsed = QDateTime.fromString(self._original_datetime, Qt.DateFormat.ISODate)
        self.datetime_input.setDateTime(parsed if parsed.isValid() else QDateTime.currentDateTime())
        self.datetime_enabled.setChecked(parsed.isValid())
        self.datetime_input.setEnabled(self.datetime_enabled.isChecked())
        self.datetime_enabled.toggled.connect(self.datetime_input.setEnabled)
        self.datetime_enabled.toggled.connect(self._date_changed)
        self.datetime_input.dateTimeChanged.connect(self._date_changed)
        form.addRow(self.datetime_enabled)
        form.addRow('Date/time as recorded', self.datetime_input)
        layout.addLayout(form)
        layout.addWidget(QLabel('Notes'))
        self.notes_input = QPlainTextEdit()
        self.notes_input.setAccessibleName('Synthesis and sample notes')
        self.notes_input.setPlaceholderText('Synthesis route, temperatures, dwell times, atmosphere, sample preparation…')
        self.notes_input.setPlainText(str(notes or ''))
        self.notes_input.setMinimumHeight(96)
        layout.addWidget(self.notes_input, 1)
        hint = QLabel('Applies only to this pattern. The source file and project creation date are kept.')
        hint.setWordWrap(True)
        hint.setProperty('uiRole', 'muted')
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout().addWidget(buttons)

    def _date_changed(self, *_args):
        self._datetime_changed = True

    def values(self):
        if not self._datetime_changed:
            recorded = self._original_datetime
        elif self.datetime_enabled.isChecked():
            recorded = self.datetime_input.dateTime().toString(Qt.DateFormat.ISODate)
        else:
            recorded = ''
        return {'sample_id': self.sample_id_input.text().strip(), 'sample_datetime': recorded}

    def notes(self):
        return self.notes_input.toPlainText()

    def showEvent(self, event):
        super().showEvent(event)
        if self._focus_field == 'notes':
            self.notes_input.setFocus()
        elif self._focus_field == 'sample_id':
            self.sample_id_input.setFocus()
            self.sample_id_input.selectAll()
        elif self.datetime_enabled.isChecked():
            self.datetime_input.setFocus()
        else:
            self.datetime_enabled.setFocus()
