"""Formula/name picker for structural calibration references."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


class CalibrationReferenceDialog(ScreenBoundDialog):
    searchRequested = Signal(str)
    referenceRequested = Signal(object)
    cancelRequested = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self._bounds_window = parent._bounds_window
        self.setWindowTitle('Choose standard CIF')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(820, 500); self.setMinimumSize(600, 360)
        self.rows = []; self.busy = False
        layout = QVBoxLayout(self)
        line = QHBoxLayout(); layout.addLayout(line)
        self.query = QLineEdit(); self.query.setPlaceholderText('Formula, name or database ID')
        self.search_button = QPushButton('Search')
        self.search_button.clicked.connect(lambda: self.searchRequested.emit(self.query.text().strip()))
        self.query.returnPressed.connect(self.search_button.click)
        line.addWidget(self.query, 1); line.addWidget(self.search_button)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Source','Database ID','Formula','Phase'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.cellDoubleClicked.connect(lambda *_: self.use_button.click())
        layout.addWidget(self.table,1)
        self.status = QLabel('Search installed and configured structure databases. Sample element filters are not used.')
        self.status.setTextFormat(Qt.TextFormat.PlainText); self.status.setWordWrap(True)
        layout.addWidget(self.status)
        line = QHBoxLayout(); layout.addLayout(line)
        self.cancel_button = QPushButton('Cancel search'); self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancelRequested.emit); line.addWidget(self.cancel_button)
        line.addStretch(1)
        self.use_button = QPushButton('Use CIF'); self.use_button.clicked.connect(self._select)
        line.addWidget(self.use_button)
        close = QPushButton('Close'); close.clicked.connect(self.reject); line.addWidget(close)
        self._sync()

    def set_busy(self, busy):
        self.busy = busy; self._sync()

    def _sync(self):
        self.query.setEnabled(not self.busy); self.search_button.setEnabled(not self.busy)
        self.table.setEnabled(not self.busy); self.cancel_button.setVisible(self.busy)
        self.use_button.setEnabled(not self.busy and 0 <= self.table.currentRow() < len(self.rows))

    def set_rows(self, rows):
        self.rows = rows; self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, field in enumerate(('Source','Entry','Formula','Phase')):
                item = QTableWidgetItem(row.get(field,''))
                item.setToolTip(item.text()); self.table.setItem(i,j,item)
        self.status.setText(f'{len(rows)} structure cards found.' if rows else 'No structures found. Check Manage databases or load a CIF file.')
        if rows: self.table.selectRow(0)

    def _select(self):
        row = self.table.currentRow()
        if not self.busy and 0 <= row < len(self.rows): self.referenceRequested.emit(dict(self.rows[row]))

    def reject(self):
        self.cancelRequested.emit(); super().reject()
