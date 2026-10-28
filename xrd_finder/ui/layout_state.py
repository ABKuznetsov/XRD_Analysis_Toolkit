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
        self._tables = {}
        self._pinned = bool(settings.value("layout/pinned", True, type=bool))
        self.pin_button: QToolButton | None = None
        self.help_button: QToolButton | None = None

    @property
    def pinned(self) -> bool:
        return self._pinned

    def register(self, name: str, splitter: QSplitter) -> QSplitter:
        splitter.setChildrenCollapsible(False)
        self._splitters[name] = splitter
        self._apply_lock(splitter)
        return splitter

    def add_pin_corner(self, tabs: QTabWidget, help_callback: Callable[[], None]) -> QToolButton:
        corner = QWidget()
        row = QHBoxLayout(corner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        pin_button = QToolButton()
        pin_button.setText("Edit layout")
        pin_button.setObjectName("editLayoutButton")
        pin_button.setAccessibleName("Edit layout")
        pin_button.setCheckable(True)
        pin_button.setChecked(not self._pinned)
        pin_button.setToolTip("On: move and resize panels and table columns. Off: save and lock the layout.")
        pin_button.toggled.connect(lambda editing: self.set_pinned(not editing))

        help_button = QToolButton()
        help_button.setText("?")
        help_button.setToolTip("Open quick help")
        help_button.clicked.connect(help_callback)

        row.addWidget(pin_button)
        row.addWidget(help_button)
        tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        self.pin_button = pin_button
        self.help_button = help_button
        self.apply_lock()
        return pin_button

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._settings.setValue("layout/pinned", pinned)
        if pinned:
            self.save()
        else:
            self._settings.sync()
        self.apply_lock()
        if self.pin_button is not None:
            self.pin_button.blockSignals(True)
            self.pin_button.setChecked(not pinned)
            self.pin_button.blockSignals(False)

    def apply_lock(self) -> None:
        for splitter in self._splitters.values():
            self._apply_lock(splitter)
        for table in self._tables.values():
            table.set_column_layout_editable(not self._pinned)

    def register_table(self, name: str, table) -> None:
        self._tables[name] = table
        table.set_column_layout_editable(not self._pinned)

    def save(self) -> None:
        for name in self._names:
            splitter = self._splitters.get(name)
            if splitter is not None:
                self._settings.setValue(f"layout/{name}", splitter.saveState())
        for name, table in self._tables.items():
            if getattr(table, '_manual_column_layout', False):
                self._settings.setValue(f"layout/tables/{name}", table.horizontalHeader().saveState())
                self._settings.setValue(f"layout/table_proportions/{name}", table.column_layout_proportions())
        self._settings.sync()

    def restore(self) -> None:
        for name in self._names:
            splitter = self._splitters.get(name)
            state = self._settings.value(f"layout/{name}", None)
            if splitter is not None and state is not None:
                splitter.restoreState(state)
        for name, table in self._tables.items():
            state = self._settings.value(f"layout/tables/{name}", None)
            if state is not None:
                table.restore_column_layout(state, self._settings.value(f"layout/table_proportions/{name}", None))

    def _apply_lock(self, splitter: QSplitter) -> None:
        for index in range(1, splitter.count()):
            splitter.handle(index).setEnabled(not self._pinned)
        density=getattr(splitter.window(),"_ui_density_factor",1.)
        splitter.setHandleWidth(max(1,round((1 if self._pinned else 7)*density)))
