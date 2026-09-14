from __future__ import annotations

from PySide6.QtCore import QSize, Signal, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QToolButton,
    QWidget,
)


class FinderTopToolBar(QWidget):
    newProjectRequested = Signal()
    openProjectRequested = Signal()
    saveProjectRequested = Signal()
    importRequested = Signal()
    autoSearchRequested = Signal()
    resetDataRequested = Signal()
    resetViewRequested = Signal()
    databaseSettingsRequested = Signal()
    plotAppearanceRequested = Signal()
    instrumentSettingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("finderTopToolBar")
        self.setMaximumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

        self.new_button = self._button(
            "New",
            QStyle.StandardPixmap.SP_FileIcon,
            "Create a new project",
        )
        self.new_button.clicked.connect(self.newProjectRequested)
        self.open_button = self._button(
            "Open",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            "Open a project",
        )
        self.open_button.clicked.connect(self.openProjectRequested)
        self.save_button = self._button(
            "Save",
            QStyle.StandardPixmap.SP_DialogSaveButton,
            "Save the current project",
        )
        self.save_button.clicked.connect(self.saveProjectRequested)
        self.import_button = self._button(
            "Import",
            QStyle.StandardPixmap.SP_ArrowDown,
            "Import XRD or CIF files",
        )
        self.import_button.clicked.connect(self.importRequested)
        self.auto_search_button = self._button(
            "Auto search",
            QStyle.StandardPixmap.SP_MediaPlay,
            "Find and rank phase candidates from the active XRD pattern",
        )
        self.auto_search_button.clicked.connect(self.autoSearchRequested)
        self.reset_data_button = self._button(
            "Reset data",
            QStyle.StandardPixmap.SP_BrowserReload,
            "Restore the original observed pattern",
        )
        self.reset_data_button.clicked.connect(self.resetDataRequested)
        self.reset_view_button = self._button(
            "Reset view",
            QStyle.StandardPixmap.SP_DialogResetButton,
            "Show the full XRD range and reset plot zoom",
        )
        self.reset_view_button.clicked.connect(self.resetViewRequested)
        self.database_button = self._button(
            "DB",
            QStyle.StandardPixmap.SP_DriveHDIcon,
            "Open database settings",
        )
        self.database_button.clicked.connect(self.databaseSettingsRequested)
        self.view_button = self._button(
            "View",
            QStyle.StandardPixmap.SP_DesktopIcon,
            "Open plot appearance settings",
        )
        self.view_button.clicked.connect(self.plotAppearanceRequested)
        self.instrument_button = self._button(
            "Instr",
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "Open instrument profile settings",
        )
        self.instrument_button.clicked.connect(self.instrumentSettingsRequested)
        layout.addWidget(self.new_button)
        layout.addWidget(self.open_button)
        layout.addWidget(self.save_button)
        layout.addWidget(self.import_button)
        layout.addSpacing(10)
        layout.addWidget(self.auto_search_button)
        layout.addWidget(self.reset_data_button)
        layout.addWidget(self.reset_view_button)
        layout.addSpacing(10)
        layout.addWidget(self.database_button)
        layout.addWidget(self.view_button)
        layout.addWidget(self.instrument_button)
        layout.addStretch(1)

    def _button(self, text: str, icon: QStyle.StandardPixmap, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setIcon(self.style().standardIcon(icon))
        button.setIconSize(QSize(16, 16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setAutoRaise(True)
        button.setMaximumHeight(28)
        button.setMinimumWidth(0)
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        return button

    def set_auto_search_busy(self, busy: bool) -> None:
        self.auto_search_button.setEnabled(not busy)
        self.auto_search_button.setText("Searching..." if busy else "Auto search")
