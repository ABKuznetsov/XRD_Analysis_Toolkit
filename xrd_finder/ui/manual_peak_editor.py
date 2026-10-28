"""Modeless numeric controls for a discrete, manually entered peak list."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


class ManualPeakEditor(ScreenBoundDialog):
    addRequested = Signal(float, float)
    updateRequested = Signal(float, float, float)
    removeRequested = Signal(float)

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle('Manual peaks')
        self.resize(420, 440)
        self._selected_angle = None
        layout = QVBoxLayout(self)
        hint = QLabel('Click the plot to add a peak, or enter its values below. '
            'Right-click a peak to remove it. Changes are saved with the project.')
        hint.setWordWrap(True); layout.addWidget(hint)
        self.angle = QDoubleSpinBox(); self.angle.setDecimals(4); self.angle.setRange(.0001, 125.)
        self.angle.setValue(20.); self.angle.setSuffix(' °')
        self.intensity = QDoubleSpinBox(); self.intensity.setDecimals(2); self.intensity.setRange(0., 100.)
        self.intensity.setValue(100.)
        form = QFormLayout(); form.addRow('2θ', self.angle); form.addRow('Intensity (0–100)', self.intensity)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.add_button = QPushButton('Add peak')
        self.update_button = QPushButton('Update selected')
        self.remove_button = QPushButton('Remove selected')
        for button in (self.add_button, self.update_button, self.remove_button): row.addWidget(button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['2θ (°)', 'Intensity'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.cellClicked.connect(self._select_row)
        layout.addWidget(self.table, 1)
        self.add_button.clicked.connect(lambda: self.addRequested.emit(self.angle.value(), self.intensity.value()))
        self.update_button.clicked.connect(self._update)
        self.remove_button.clicked.connect(self._remove)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close); layout.addWidget(buttons)

    def set_peaks(self, peaks):
        self.table.setRowCount(len(peaks)); self._selected_angle = None
        self.update_button.setEnabled(False); self.remove_button.setEnabled(False)
        for row, (angle, intensity) in enumerate(peaks):
            self.table.setItem(row, 0, QTableWidgetItem(f'{angle:.4f}'))
            self.table.setItem(row, 1, QTableWidgetItem(f'{intensity:.2f}'))

    def _select_row(self, row, _column):
        if self.table.item(row, 0) is None: return
        self._selected_angle = float(self.table.item(row, 0).text())
        self.update_button.setEnabled(True); self.remove_button.setEnabled(True)
        self.angle.setValue(self._selected_angle)
        self.intensity.setValue(float(self.table.item(row, 1).text()))

    def _update(self):
        if self._selected_angle is not None:
            self.updateRequested.emit(self._selected_angle, self.angle.value(), self.intensity.value())

    def _remove(self):
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0) is not None:
            self.removeRequested.emit(float(self.table.item(row, 0).text()))
