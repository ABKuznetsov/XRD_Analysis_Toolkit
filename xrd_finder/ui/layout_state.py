from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QTabWidget, QToolButton, QWidget


class SplitterLayoutState:
    def __init__(
        self,
        settings: QSettings,
        names: tuple[str, ...] = ("main_splitter", "center_splitter", "composition_splitter"),
    ) -> None:
        self._settings = settings
        self._names = names
        self._splitters: dict[str, QSplitter] = {}
        self._pinned = bool(settings.value("layout/pinned", False, type=bool))
        self.pin_button: QToolButton | None = None

    @property
    def pinned(self) -> bool:
        return self._pinned

    def register(self, name: str, splitter: QSplitter) -> QSplitter:
        self._splitters[name] = splitter
        self._apply_lock(splitter)
        return splitter

    def add_pin_corner(self, tabs: QTabWidget, help_callback: Callable[[], None]) -> QToolButton:
        corner = QWidget()
        row = QHBoxLayout(corner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        pin_button = QToolButton()
        pin_button.setText("Pin")
        pin_button.setCheckable(True)
        pin_button.setChecked(self._pinned)
        pin_button.setToolTip("Lock or unlock the current panel layout.")
        pin_button.toggled.connect(self.set_pinned)

        help_button = QToolButton()
        help_button.setText("?")
        help_button.setToolTip("Open quick help")
        help_button.clicked.connect(help_callback)

        row.addWidget(pin_button)
        row.addWidget(help_button)
        tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        self.pin_button = pin_button
        self.apply_lock()
        return pin_button

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._settings.setValue("layout/pinned", pinned)
        if pinned:
            self.save()
        self.apply_lock()

    def apply_lock(self) -> None:
        for splitter in self._splitters.values():
            self._apply_lock(splitter)

    def save(self) -> None:
        for name in self._names:
            splitter = self._splitters.get(name)
            if splitter is not None:
                self._settings.setValue(f"layout/{name}", splitter.saveState())

    def restore(self) -> None:
        for name in self._names:
            splitter = self._splitters.get(name)
            state = self._settings.value(f"layout/{name}", None)
            if splitter is not None and state is not None:
                splitter.restoreState(state)

    def _apply_lock(self, splitter: QSplitter) -> None:
        for index in range(1, splitter.count()):
            splitter.handle(index).setEnabled(not self._pinned)
        splitter.setHandleWidth(1 if self._pinned else 7)
