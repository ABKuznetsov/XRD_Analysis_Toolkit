from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Signal, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLayout, QMenu, QSizePolicy, QToolButton, QWidget

from xrd_finder.ui.theme import is_dark_theme, theme_colors, search_mode_button_style, SEARCH_MODE_COLORS
from xrd_finder.ui.toolbar_icons import toolbar_icon


class FinderTopToolBar(QWidget):
    newProjectRequested = Signal()
    openProjectRequested = Signal()
    saveProjectRequested = Signal()
    importRequested = Signal()
    autoSearchRequested = Signal()
    peakSearchRequested = Signal()
    resetDataRequested = Signal()
    resetViewRequested = Signal()
    databaseSettingsRequested = Signal()
    plotAppearanceRequested = Signal()
    instrumentSettingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('finderTopToolBar')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._restyling = False
        self._buttons: list[QToolButton] = []
        layout = QHBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self.new_button = self._button('New project', 'new', 'Create a new project', self.newProjectRequested)
        self.open_button = self._button('Open project', 'open', 'Open a project', self.openProjectRequested)
        self.save_button = self._button('Save', 'save', 'Save the current project', self.saveProjectRequested)
        self.import_button = self._button('Import data', 'import', 'Import XRD patterns or CIF structures', self.importRequested)
        self.auto_search_button = self._button(
            'Identify phases', 'search', 'Identify candidate phases from the active XRD pattern; scores are not probabilities', self.autoSearchRequested)
        self.auto_search_button.setProperty('searchMode', 'auto')
        self.auto_search_button.setCheckable(True)
        self.peak_search_button = self._button(
            'Peak search', 'peaks', 'Select peaks on the active pattern: left-click to mark, right-click to remove. '
            'Then run Peak search in the element panel.', self.peakSearchRequested)
        self.peak_search_button.setCheckable(True)
        self.peak_search_button.setProperty('searchMode', 'peaks')
        self.reset_data_button = self._button(
            'Reset processing', 'reset', 'Restore the active original pattern; clear smoothing, background removal and crop history. Loaded data and selected phases are kept', self.resetDataRequested)
        self.reset_view_button = self._button(
            'Fit plot', 'fit', 'Show the full XRD range and reset plot zoom', self.resetViewRequested)
        self.database_button = self._button(
            'Manage databases', 'database', 'Manage phase databases, local library and data sources', self.databaseSettingsRequested)
        self.view_button = self._button(
            'Plot settings', 'plot', 'Set plot appearance, curves, markers and labels', self.plotAppearanceRequested)
        self.instrument_button = self._button(
            'Instrument settings', 'instrument', 'Set the instrument profile, radiation and peak widths', self.instrumentSettingsRequested)

        self._groups = [
            self._group(layout, [self.new_button, self.open_button, self.save_button, self.import_button]),
            self._group(layout, [self.auto_search_button, self.peak_search_button, self.reset_data_button, self.reset_view_button]),
        ]
        layout.addStretch(1)
        self._groups.append(self._group(layout, [self.database_button, self.view_button, self.instrument_button]))
        self.more_button = self._button('More', 'more', 'More commands')
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.more_button)
        self.more_button.setMenu(menu)
        self._secondary = [self.new_button, self.open_button, self.save_button,
                           self.reset_data_button, self.reset_view_button, self.view_button]
        self._compact = [self.new_button, self.open_button, self.save_button,
                         self.reset_data_button, self.reset_view_button]
        self._fallback = [self.import_button, self.peak_search_button,
                          self.database_button, self.instrument_button]
        self._overflow_actions: dict[QToolButton, QAction] = {}
        for button in self._buttons:
            if button in (self.auto_search_button, self.more_button):
                continue
            action = menu.addAction(button.text())
            action.triggered.connect(lambda _checked=False, source=button: source.click())
            self._overflow_actions[button] = action
        menu.aboutToShow.connect(self._sync_overflow_actions)
        layout.addWidget(self.more_button)
        self.more_button.hide()
        self._apply_style()

    def attach_layout_controls(self,edit_button,help_button):
        self.layout_button=edit_button
        self.help_button=help_button
        help_button.setText('Help')
        row=self._groups[-1].layout()
        for button,icon in ((edit_button,'layout'),(help_button,'help')):
            button.setProperty('toolbarIcon',icon)
            button.setIconSize(QSize(20,20))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setFixedHeight(34)
            button.setAutoRaise(True)
            row.addWidget(button)
            self._buttons.append(button)
            self._fallback.append(button)
            action=self.more_button.menu().addAction(button.text())
            action.triggered.connect(lambda _checked=False,source=button:source.click())
            self._overflow_actions[button]=action
        self._apply_style()
        self._adapt_width()

    def _button(self, text: str, icon: str, tooltip: str, signal=None) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(f'{text}\n{tooltip}')
        button.setProperty('toolbarIcon', icon)
        button.setIconSize(QSize(20, 20))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setFixedHeight(34)
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        if signal is not None:
            button.clicked.connect(signal)
        self._buttons.append(button)
        return button

    def _group(self, layout: QHBoxLayout, buttons: list[QToolButton]) -> QFrame:
        group = QFrame(self)
        group.setObjectName('toolbarGroup')
        row = QHBoxLayout(group)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        for button in buttons:
            row.addWidget(button)
        layout.addWidget(group)
        return group

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 56)

    def _required_width(self) -> int:
        visible = [group for group in self._groups if not group.isHidden()]
        width = sum(group.layout().sizeHint().width() for group in visible)
        more = int(not self.more_button.isHidden())
        if more:
            width += self.more_button.sizeHint().width()
        return width + 16 + 10 * max(0, len(visible) - 1 + more)

    def _adapt_width(self) -> None:
        if not hasattr(self, '_secondary'):
            return
        for button in self._buttons:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for button in self._secondary + self._fallback:
            button.show()
        self._refresh_groups()
        self.more_button.hide()
        for group in self._groups:
            group.layout().invalidate()
        if self._required_width() > self.width():
            for button in self._compact:
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            for group in self._groups:
                group.layout().invalidate()
        if self._required_width() > self.width():
            for button in self._secondary:
                button.hide()
            self.more_button.show()
            self.import_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self._refresh_groups()
            # Very narrow or large-font hosts still retain every command.
            for button in self._fallback:
                if self._required_width() <= self.width():
                    break
                button.hide()
                self._refresh_groups()
        self._sync_overflow_actions()
        self.layout().invalidate()
        self.layout().activate()

    def _refresh_groups(self) -> None:
        for group in self._groups:
            row = group.layout()
            group.setVisible(any(not row.itemAt(index).widget().isHidden() for index in range(row.count())))
            row.invalidate()
            group.updateGeometry()
        self.layout().invalidate()

    def _sync_overflow_actions(self) -> None:
        for button, action in self._overflow_actions.items():
            action.setIcon(button.icon())
            action.setEnabled(button.isEnabled())
            action.setVisible(button.isHidden())
            action.setToolTip(button.toolTip())
            action.setCheckable(button.isCheckable())
            action.setChecked(button.isChecked())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adapt_width()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            if hasattr(self, '_overflow_actions') and not self._restyling:
                self._adapt_width()
        elif event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
                              QEvent.Type.ParentChange):
            if hasattr(self, '_overflow_actions') and not self._restyling:
                self._apply_style()
                self._adapt_width()

    def _apply_style(self) -> None:
        self._restyling = True
        try:
            dark = is_dark_theme(self)
            colors = theme_colors(dark)
            bg, group, border, text, hover, muted = (
                (colors['bg'], colors['panel'], colors['border'], colors['text'], colors['hover'], '#82909f') if dark else
                ('#f4f7fa', '#ffffff', '#dce3eb', '#334155', '#edf2f7', '#94a3b8'))
            self.setStyleSheet(
                f'QWidget#finderTopToolBar {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}'
                f'QFrame#toolbarGroup {{ background: {group}; border: 1px solid {border}; border-radius: 8px; }}'
                f'QWidget#finderTopToolBar QToolButton {{ background: transparent; color: {text}; '
                'border: 1px solid transparent; border-radius: 6px; padding: 4px 9px; font-weight: 500; }'
                f'QWidget#finderTopToolBar QToolButton:hover {{ background: {hover}; }}'
                f'QWidget#finderTopToolBar QToolButton:pressed {{ background: {hover}; border-color: #21b99a; }}'
                'QWidget#finderTopToolBar QToolButton:checked { background: #176b5b; color: #ffffff; border-color: #37b89c; }'
                'QWidget#finderTopToolBar QToolButton:focus { border-color: #21b99a; }'
                'QWidget#finderTopToolBar QToolButton#editLayoutButton:checked { background: #a62e45; color: #ffffff; border-color: #d05b70; }'
                f'QWidget#finderTopToolBar QToolButton:disabled {{ background: transparent; color: {muted}; border-color: transparent; }}'
                'QWidget#finderTopToolBar QToolButton::menu-indicator { image: none; width: 0px; }'
                + search_mode_button_style('QWidget#finderTopToolBar QToolButton', checked=True)
            )
            self.more_button.menu().setStyleSheet(
                f'QMenu {{ background: {group}; color: {text}; border: 1px solid {border}; padding: 5px; }}'
                f'QMenu::item {{ color: {text}; padding: 7px 22px 7px 30px; border-radius: 4px; }}'
                f'QMenu::item:selected {{ background: {hover}; }}'
                f'QMenu::item:disabled {{ color: {muted}; }}'
            )
            for button in self._buttons:
                mode = button.property('searchMode')
                color = SEARCH_MODE_COLORS[mode][2] if mode in SEARCH_MODE_COLORS and button.isChecked() else text
                button.setIcon(toolbar_icon(button.property('toolbarIcon'), color, muted))
            self._sync_overflow_actions()
        finally:
            self._restyling = False

    def set_auto_search_busy(self, busy: bool) -> None:
        self.auto_search_button.setEnabled(not busy)

    def set_search_mode(self, mode: str) -> None:
        self.auto_search_button.setChecked(mode == 'auto')
        self.peak_search_button.setChecked(mode == 'peaks')
        text = '#e3eaf2' if is_dark_theme(self) else '#334155'
        for button in (self.auto_search_button, self.peak_search_button):
            color = SEARCH_MODE_COLORS[mode][2] if button.isChecked() else text
            button.setIcon(toolbar_icon(button.property('toolbarIcon'), color, '#82909f'))
        self._sync_overflow_actions()
