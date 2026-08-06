from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from xrd_finder.ui.theme import command_button_style


class ProjectControlsWidget(QWidget):
    newProjectRequested = Signal()
    loadProjectRequested = Signal()
    saveProjectRequested = Signal()
    importRequested = Signal()
    moveRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        project_layout = QVBoxLayout()
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.setSpacing(5)

        new_project_button = QPushButton("New project")
        new_project_button.setAutoDefault(False)
        new_project_button.setDefault(False)
        new_project_button.setMinimumHeight(34)
        new_project_button.setToolTip("Clear the current XRD patterns, structures, candidates, and calculated overlays.")
        new_project_button.setStyleSheet(command_button_style("#5f6368", "#8a8d91"))
        new_project_button.clicked.connect(self.newProjectRequested)

        load_project_button = QPushButton("Load project")
        load_project_button.setAutoDefault(False)
        load_project_button.setMinimumHeight(34)
        load_project_button.setToolTip("Load a saved XRD project manifest.")
        load_project_button.setStyleSheet(command_button_style("#0b8043", "#35a96c"))
        load_project_button.clicked.connect(self.loadProjectRequested)

        save_project_button = QPushButton("Save project")
        save_project_button.setAutoDefault(False)
        save_project_button.setMinimumHeight(34)
        save_project_button.setToolTip("Save the current project manifest, including processed XRD curves.")
        save_project_button.setStyleSheet(command_button_style("#2367a5", "#5a9bd8"))
        save_project_button.clicked.connect(self.saveProjectRequested)

        project_layout.addWidget(new_project_button)
        project_layout.addWidget(load_project_button)
        project_layout.addWidget(save_project_button)

        import_button = QPushButton("Import XRD / CIF")
        import_button.setAutoDefault(False)
        import_button.setMinimumHeight(34)
        import_button.setToolTip("Import XRD patterns and CIF structures. You can also drag files into the window.")
        import_button.setStyleSheet(command_button_style("#e9328f", "#ff65b3"))
        import_button.clicked.connect(self.importRequested)

        order_row = QHBoxLayout()
        order_row.setContentsMargins(0, 0, 0, 0)
        order_row.setSpacing(4)
        order_row.addWidget(QLabel("Order"))

        move_up_button = QToolButton()
        move_up_button.setText("Up")
        move_up_button.setToolTip("Move selected XRD or CIF up")
        move_up_button.clicked.connect(lambda: self.moveRequested.emit(-1))

        move_down_button = QToolButton()
        move_down_button.setText("Down")
        move_down_button.setToolTip("Move selected XRD or CIF down")
        move_down_button.clicked.connect(lambda: self.moveRequested.emit(1))

        order_row.addWidget(move_up_button)
        order_row.addWidget(move_down_button)
        order_row.addStretch(1)

        layout.addLayout(project_layout)
        layout.addWidget(import_button)
        layout.addLayout(order_row)
