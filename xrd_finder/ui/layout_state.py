from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QTabWidget, QToolButton, QWidget
from xrd_finder.ui.workspace_preferences import (
    DEFAULT_SPLITTER_PROPORTIONS, load_workspace_preferences,
    normalized_proportions, save_workspace_preferences,
)


def _legacy_splitter_proportions(state, splitter):
    """Read native pixel weights before current-screen minimum sizes distort them."""
    probe = QSplitter(splitter.orientation())
    try:
        for _ in range(splitter.count()):
            probe.addWidget(QWidget())
        # Hidden, unconstrained widgets need no backing image. A generous
        # logical extent preserves the original ratios to rounding accuracy.
        probe.resize(1000000, 1000000)
        try:
            restored = probe.restoreState(state)
        except (TypeError, ValueError):
            return None
        return normalized_proportions(probe.sizes(), probe.count()) if restored else None
    finally:
        probe.deleteLater()


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
        self._splitter_proportions = {}
        # A fresh installation starts with visible, usable layout handles.
        # Existing users keep their explicit lock state and saved arrangement.
        has_saved_layout = settings.contains("ui/workspace_view_v1") or any(
            key.startswith("layout/") for key in settings.allKeys()
        )
        self._pinned = bool(settings.value("layout/pinned", has_saved_layout, type=bool))
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

    def remember_splitter_proportions(self, name, splitter=None) -> None:
        splitter = splitter or self._splitters.get(name)
        if splitter is not None:
            values = normalized_proportions(splitter.sizes(), splitter.count())
            if values is not None:
                self._splitter_proportions[name] = values

    def apply_proportions(self) -> None:
        for name, splitter in self._splitters.items():
            values = self._splitter_proportions.get(name)
            if values is None:
                continue
            extent = splitter.width() if splitter.orientation() == Qt.Orientation.Horizontal else splitter.height()
            available = max(1, extent-splitter.handleWidth()*(splitter.count()-1))
            splitter.setSizes([max(1, round(value*available)) for value in values])

    def save(self, *, workspace_updates=None) -> None:
        data = load_workspace_preferences(self._settings)
        if workspace_updates:
            data.update(workspace_updates)
        panels = {}
        for name in self._names:
            splitter = self._splitters.get(name)
            if splitter is not None:
                if name not in self._splitter_proportions:
                    self.remember_splitter_proportions(name, splitter)
                values = self._splitter_proportions.get(name)
                if values is not None:
                    panels[name] = values
        data['splitters'] = panels
        tables = data.get('tables', {})
        tables = dict(tables) if isinstance(tables, dict) else {}
        for name, table in self._tables.items():
            if getattr(table, '_manual_column_layout', False):
                tables[name] = table.column_layout_state()
        data['tables'] = tables
        save_workspace_preferences(self._settings, data)
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            return
        # The old binary records are migration inputs, never parallel writers.
        for name in panels:
            self._settings.remove(f'layout/{name}')
        for name in self._tables:
            if name in tables:
                self._settings.remove(f'layout/tables/{name}')
                self._settings.remove(f'layout/table_proportions/{name}')
        self._settings.sync()

    def restore(self) -> None:
        data = load_workspace_preferences(self._settings)
        panels = data.get('splitters', {})
        panels = panels if isinstance(panels, dict) else {}
        for name in self._names:
            splitter = self._splitters.get(name)
            if splitter is None:
                continue
            values = normalized_proportions(panels.get(name), splitter.count())
            if values is None:
                state = self._settings.value(f'layout/{name}', None)
                if state is not None:
                    values = _legacy_splitter_proportions(state, splitter)
            if values is None:
                values = normalized_proportions(DEFAULT_SPLITTER_PROPORTIONS.get(name), splitter.count())
            if values is None:
                values = normalized_proportions(splitter.sizes(), splitter.count())
            if values is not None:
                self._splitter_proportions[name] = values
        tables = data.get('tables', {})
        tables = tables if isinstance(tables, dict) else {}
        for name, table in self._tables.items():
            if table.restore_column_layout(tables.get(name)):
                continue
            state = self._settings.value(f"layout/tables/{name}", None)
            if state is not None:
                table.restore_column_layout(state, self._settings.value(f"layout/table_proportions/{name}", None))
        self.apply_proportions()

    def _apply_lock(self, splitter: QSplitter) -> None:
        for index in range(1, splitter.count()):
            splitter.handle(index).setEnabled(not self._pinned)
        density=getattr(splitter.window(),"_ui_density_factor",1.)
        splitter.setHandleWidth(max(1,round((1 if self._pinned else 7)*density)))
