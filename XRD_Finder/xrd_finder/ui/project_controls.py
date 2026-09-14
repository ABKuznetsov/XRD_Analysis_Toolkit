from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

class ProjectControlsWidget(QWidget):
    newProjectRequested = Signal()
    loadProjectRequested = Signal()
    saveProjectRequested = Signal()
    saveProjectAsRequested = Signal()
    addSeriesRequested = Signal()
    importRequested = Signal()
    moveRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        add_series_button = QPushButton("Add series")
        add_series_button.setAutoDefault(False)
        add_series_button.setMinimumHeight(26)
        add_series_button.setToolTip("Add a named series to the project tree. Select it before importing related XRD/CIF files.")
        add_series_button.clicked.connect(self.addSeriesRequested)

        order_row = QHBoxLayout()
        order_row.setContentsMargins(0, 0, 0, 0)
        order_row.setSpacing(4)
        order_row.addWidget(QLabel("Order"))

        move_up_button = QToolButton()
        move_up_button.setText("Up")
        move_up_button.setToolTip("Move selected series, XRD or CIF up")
        move_up_button.clicked.connect(lambda: self.moveRequested.emit(-1))

        move_down_button = QToolButton()
        move_down_button.setText("Down")
        move_down_button.setToolTip("Move selected series, XRD or CIF down")
        move_down_button.clicked.connect(lambda: self.moveRequested.emit(1))

        order_row.addWidget(move_up_button)
        order_row.addWidget(move_down_button)
        order_row.addStretch(1)

        layout.addWidget(add_series_button)
        layout.addLayout(order_row)
