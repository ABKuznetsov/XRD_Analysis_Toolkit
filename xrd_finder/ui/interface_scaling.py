"""Compact controls with independently fitted workspace panels."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QLayout, QWidgetAction
from xrd_finder.ui.ui_density import UiDensity
from xrd_finder.ui.system_theme import SystemThemeObserver
from xrd_finder.ui.workspace_preferences import load_workspace_preferences
PERSISTED_PLOT_FIELDS = ('aspect_ratio', 'custom_aspect_width', 'custom_aspect_height', 'label_font_size', 'tick_font_size', 'title_font_size', 'legend_font_size', 'multi_phase_legend_mode', 'multi_legend_phase_names_visible')

class InterfaceScalingMixin:

    def _init_interface_scaling(self):
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumSize(360, 300)
        self._interface_base_style = self.styleSheet() + '\nQWidget { font-size: 13px; }'
        self.setStyleSheet(self._interface_base_style)
        self._density = UiDensity()
        self._ui_density_factor = 1.0
        self._interface_scaling = False
        self._interface_scale_timer = QTimer(self)
        self._interface_scale_timer.setSingleShot(True)
        self._interface_scale_timer.timeout.connect(self._update_interface_scaling)
        self._system_theme_observer = SystemThemeObserver(self)
        self._system_theme_observer.changed.connect(self._apply_interface_theme)
        self._applied_density = None
        stored = load_workspace_preferences()
        for name, splitter in self._layout_state._splitters.items():
            splitter.splitterMoved.connect(lambda _position, _index, key=name, target=splitter: self._remember_splitter_ratios(key, target))
        self._ui_scale_percent = stored.get('ui_scale', 100)
        if self._ui_scale_percent not in (75, 85, 100, 115, 125, 150):
            self._ui_scale_percent = 100
        view_menu = next((menu for menu in self.menu_bar._owned_menus if menu.title() == 'View'))
        scale_menu = view_menu.addMenu('Interface scale')
        self._interface_scale_menu = scale_menu
        self.ui_scale_combo = QComboBox()
        self.ui_scale_combo.addItems([f'UI {value}%' for value in (75, 85, 100, 115, 125, 150)])
        self.ui_scale_combo.setCurrentText(f'UI {self._ui_scale_percent}%')
        self.ui_scale_combo.setAccessibleName('Interface scale')
        self.ui_scale_combo.setToolTip('Adjust control size in addition to the Windows display scale')
        self.ui_scale_combo.currentTextChanged.connect(self._set_interface_scale)
        action = QWidgetAction(scale_menu)
        action.setDefaultWidget(self.ui_scale_combo)
        scale_menu.addAction(action)
        self.finder_top_toolbar.attach_layout_controls(self._layout_state.pin_button, self._layout_state.help_button)
        self._layout_state.pin_button.toggled.connect(lambda _checked: self._save_workspace_preferences())
        self._update_interface_scaling()

    def _apply_interface_theme(self, dark, previous_dark):
        from xrd_finder.ui.theme import window_style, settings_panel_style, preprocessing_panel_style, theme_colors
        from PySide6.QtWidgets import QWidget
        import re

        self._interface_base_style = window_style(dark) + '\nQWidget { font-size: 13px; }'
        self.setStyleSheet(self._interface_base_style)
        self.finder_top_toolbar._apply_style()
        self.finder_action_bar.setStyleSheet(settings_panel_style(dark))
        plot_panel = getattr(self, 'plot_settings_panel', None)
        if plot_panel is not None:
            plot_panel.setStyleSheet(window_style(dark) + settings_panel_style(dark))

        # The reference card has local section/table styles. Only recolor that
        # card's chrome, never plot colors, swatches or chemical-state controls.
        card = getattr(self, 'compound_card', None)
        if card is not None:
            old, new = theme_colors(previous_dark), theme_colors(dark)
            roles = ('bg', 'panel', 'alt', 'text', 'muted', 'border', 'selected', 'header', 'link', 'cell_border')
            replacements = {old[key]: new[key] for key in roles}
            pattern = re.compile('|'.join(re.escape(color) for color in replacements))
            for widget in [card, *card.findChildren(QWidget)]:
                cached = self._density._styles.get(widget)
                base = cached[0] if cached is not None else widget.styleSheet()
                if base:
                    widget.setStyleSheet(pattern.sub(lambda match: replacements[match.group()], base))
        for panel in self.findChildren(QWidget, 'preprocessingPanel'):
            panel.setStyleSheet(preprocessing_panel_style(dark))
        database = getattr(self, 'database_panel', None)
        if database is not None:
            from PySide6.QtWidgets import QPushButton
            for button in database.findChildren(QPushButton):
                button.setStyleSheet(database._button_style(button.text()))
        bar = getattr(self, 'candidate_status_bar', None)
        if bar is not None:
            state = bar.property('activityState') or 'idle'
            bar.setProperty('activityState', None)
            self._set_candidate_status_state(state)
        self._applied_density = None
        self._update_interface_scaling()

    def _update_interface_scaling(self):
        if not hasattr(self, '_density') or self._interface_scaling:
            return
        self._interface_scaling = True
        try:
            # Qt already accounts for the screen's DPI. Extra workspace must
            # grow the panels, not magnify every button and font on a 2K screen.
            compact_factor = min(1.0, self.width() / 1600, self.height() / 900)
            factor = max(0.3, compact_factor * self._ui_scale_percent / 100)
            if factor != self._applied_density:
                self._applied_density = factor
                self._ui_density_factor = factor
                self._density.apply(self, factor)
                self._layout_state.apply_lock()
                self._sync_plot_canvas_margins(self.plot_view_settings, self.plot_view_settings.title_visible)
                self._plot_aspect_timer.start(0)
            self.layout().activate()
            self._layout_state.apply_proportions()
            self.cursor_status_panel._update_control_layout()
            self.element_table._fit_cells_to_area()
        finally:
            self._interface_scaling = False

    def _remember_splitter_ratios(self, name, splitter):
        if not self._interface_scaling and (not self._layout_state.pinned):
            self._layout_state.remember_splitter_proportions(name, splitter)

    def _set_interface_scale(self, text):
        self._ui_scale_percent = int(text.removeprefix('UI ').rstrip('%'))
        self._applied_density = None
        self._update_interface_scaling()
        self._save_workspace_preferences()

    def _save_workspace_preferences(self):
        if not hasattr(self, '_ui_scale_percent'):
            return
        plot = getattr(self, 'plot_view_settings', None)
        data = {'ui_scale': self._ui_scale_percent, 'plot': {key: getattr(plot, key) for key in PERSISTED_PLOT_FIELDS} if plot else {}}
        self._layout_state.save(workspace_updates=data)
