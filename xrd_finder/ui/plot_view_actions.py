from __future__ import annotations

from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog
from xrd_finder.ui.interface_scaling import load_workspace_preferences,PERSISTED_PLOT_FIELDS

import math

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QSizePolicy, QVBoxLayout, QWidget

from xrd_finder.ui.plot_view_settings import PLOT_ASPECTS, PlotViewSettings, PlotViewSettingsWidget, plot_style_from_view_settings
from xrd_finder.ui.plot_layer_items import sync_plot_export_tags
from xrd_finder.ui.styled_grid_item import StyledGridItem


def _axis_label(label: str, unit: str) -> str:
    unit = unit.strip()
    return f"{label} [{unit}]" if unit else label


def _x_unit_for_scale(scale: str, unit: str) -> str:
    unit = str(unit or "").strip()
    if not unit:
        return ""
    if scale == "d" and unit.lower() in {"deg", "degree", "degrees"}:
        return "A"
    if scale == "2theta" and unit.lower() in {"a", "angstrom", "angstroms"}:
        return "deg"
    return unit


def _apply_axis_appearance(
    axis,
    *,
    color: str,
    width: float,
    font: QFont,
    tick_length: int,
    visible: bool,
    values_visible: bool,
) -> None:
    axis_pen = pg.mkPen(color, width=width)
    axis.setPen(axis_pen)
    axis.setTickPen(axis_pen)
    axis.setTextPen(pg.mkPen(color))
    axis.setTickFont(font)
    axis.setStyle(
        showValues=bool(visible and values_visible),
        tickLength=abs(int(tick_length)) if visible else 0,
    )


class PhaseFinderPlotViewActionsMixin:
    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "plot_canvas", None) and event.type() in (
            QEvent.Type.Resize, QEvent.Type.Show,
        ):
            # Splitter and startup layout changes can resize the canvas without
            # resizing the main window. Refit after the layout has settled.
            self._plot_aspect_timer.start(0)
        return super().eventFilter(watched, event)

    def _init_plot_view_state(self) -> None:
        self.plot_settings_panel: PlotViewSettingsWidget | None = None
        self.plot_view_settings = (
            PlotViewSettingsWidget.load_saved_default_settings()
            or PlotViewSettings()
        )
        stored=load_workspace_preferences().get('plot',{})
        if not isinstance(stored,dict):stored={}
        for key in PERSISTED_PLOT_FIELDS:
            if key not in stored:
                continue
            value=stored.get(key)
            if key == 'multi_phase_legend_mode' and value in ('common', 'individual'):
                self.plot_view_settings.multi_phase_legend_mode = value
            elif key == 'multi_legend_phase_names_visible' and isinstance(value, bool):
                self.plot_view_settings.multi_legend_phase_names_visible = value
            elif key=='aspect_ratio' and value is None:
                self.plot_view_settings.aspect_ratio=None
            elif isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<value<=100:
                setattr(self.plot_view_settings,key,value)
        self.plot_style = plot_style_from_view_settings(self.plot_view_settings)
        self.plot_marker_size = self.plot_style.marker.size
        self._plot_grid_item = None
        # An unowned singleShot can call this Python mixin after Qt has
        # destroyed the dialog. Owning the timer also coalesces resize bursts.
        self._plot_aspect_timer=QTimer(self)
        self._plot_aspect_timer.setSingleShot(True)
        self._plot_aspect_timer.timeout.connect(self._apply_plot_view_aspect)
        self._plot_initial_settings_timer=QTimer(self)
        self._plot_initial_settings_timer.setSingleShot(True)
        self._plot_initial_settings_timer.timeout.connect(self._apply_saved_plot_view_settings)
        self._plot_balance_timer = QTimer(self)
        self._plot_balance_timer.setSingleShot(True)
        self._plot_balance_timer.timeout.connect(self._balance_plot_canvas)

    def _plot_view_tab(self) -> QWidget:
        self.plot_settings_panel = PlotViewSettingsWidget()
        self.plot_settings_panel.set_settings(self.plot_view_settings, emit=False)
        self.plot_settings_panel.settingsChanged.connect(self._apply_plot_view_settings)
        self.plot_settings_panel.profileCandidateColorRequested.connect(self._change_profile_candidate_color)
        self._plot_panel_init_timer=QTimer(self.plot_settings_panel)
        self._plot_panel_init_timer.setSingleShot(True)
        self._plot_panel_init_timer.timeout.connect(lambda:self._apply_plot_view_settings(self.plot_settings_panel.settings()))
        self._plot_panel_init_timer.timeout.connect(self._update_profile_view_context)
        self._plot_panel_init_timer.start(0)
        return self.plot_settings_panel

    def _show_plot_view_settings_window(self) -> None:
        dialog = getattr(self, "_plot_view_settings_dialog", None)
        if dialog is None:
            dialog = ScreenBoundDialog(self)
            dialog.setWindowTitle("Plot appearance")
            dialog.setMinimumSize(680, 620)
            dialog.resize(780, 720)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(8,8,8,8)
            layout.addWidget(self._plot_view_tab())
            self._plot_view_settings_dialog = dialog
        self._update_profile_view_context()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _active_profile_label_text(self) -> str:
        pattern = self._active_pattern() if hasattr(self, "_active_pattern") else None
        checked = self.tree.checked_pattern_ids() if hasattr(self, "tree") else []
        if pattern is None:
            return "Active profile: none"
        suffix = ""
        if len(checked) > 1:
            suffix = f" | displayed profiles: {len(checked)}"
        return f"Active profile: {pattern.name}{suffix}"

    def _update_profile_view_context(self) -> None:
        panel = getattr(self, "plot_settings_panel", None)
        if panel is None:
            return
        if hasattr(panel, "set_active_profile_label"):
            panel.set_active_profile_label(self._active_profile_label_text())
        if hasattr(panel, "set_profile_candidates"):
            panel.set_profile_candidates(list(getattr(self, "match_candidates", [])))
        if hasattr(self, "_sync_profile_layer_controls_to_active"):
            self._sync_profile_layer_controls_to_active()

    def _set_plot_aspect_mode(self, mode: str) -> None:
        if mode == "Custom":
            height = max(float(self.plot_view_settings.custom_aspect_height), 0.1)
            aspect = max(float(self.plot_view_settings.custom_aspect_width), 0.1) / height
        else:
            aspect = PLOT_ASPECTS.get(mode)
        self.plot_view_settings.aspect_ratio = aspect
        panel = getattr(self, "plot_settings_panel", None)
        aspect_combo = getattr(panel, "aspect_combo", None)
        if aspect_combo is not None and aspect_combo.currentText() != mode:
            signals_were_blocked = aspect_combo.blockSignals(True)
            try:
                aspect_combo.setCurrentText(mode)
            finally:
                aspect_combo.blockSignals(signals_were_blocked)
        self._apply_plot_view_aspect()
        if hasattr(self,"_save_workspace_preferences"):
            self._save_workspace_preferences()
        if hasattr(self, "project"):
            self.project.touch()
        if hasattr(self, "project_changed"):
            self.project_changed.emit()

    def _sync_plot_aspect_control(self, settings: PlotViewSettings) -> None:
        control_bar = getattr(self, "finder_plot_control_bar", None)
        combo = getattr(control_bar, "plot_aspect_mode", None)
        if combo is None:
            return
        mode = "Custom"
        for name, aspect in PLOT_ASPECTS.items():
            if name == "Custom":
                continue
            if aspect is None and settings.aspect_ratio is None:
                mode = name
                break
            if aspect is not None and settings.aspect_ratio is not None and math.isclose(
                float(aspect),
                float(settings.aspect_ratio),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                mode = name
                break
        signals_were_blocked = combo.blockSignals(True)
        try:
            combo.setCurrentText(mode)
        finally:
            combo.blockSignals(signals_were_blocked)

    def _apply_plot_view_settings(self, settings: PlotViewSettings, *, force: bool = False) -> None:
        previous_settings = getattr(self, "plot_view_settings", None)
        quick_fields = {
            "grid_visible",
            "grid_alpha",
            "grid_color",
            "grid_width",
            "legend_visible",
            "legend_font_size",
            "multi_legend_alignment",
            "multi_legend_phase_names_visible",
            "multi_phase_legend_mode",
            "cursor_vertical_line_visible",
            "hkl_labels_visible",
            "layer_observed_visible",
            "layer_preview_peak_positions_visible",
            "layer_total_profile_visible",
            "layer_phase_profiles_visible",
            "layer_background_visible",
            "layer_difference_visible",
            "layer_phase_ticks_visible",
            "layer_phase_peak_sticks_visible",
            "layer_coverage_markers_visible",
            "layer_peak_labels_visible",
            "layer_unknown_peaks_visible",
        }
        quick_only = not force and previous_settings is not None and all(
            getattr(previous_settings, name) == getattr(settings, name)
            for name in settings.__dataclass_fields__
            if name not in quick_fields
        )
        active_labels_changed = False
        if previous_settings is not None and hasattr(self, "_capture_active_profile_layer_changes"):
            active_labels_changed = bool(
                getattr(self, "show_all_selected_patterns", False)
                and (
                    getattr(previous_settings, "hkl_labels_visible", None) != settings.hkl_labels_visible
                    or getattr(previous_settings, "layer_peak_labels_visible", None) != settings.layer_peak_labels_visible
                )
            )
            self._capture_active_profile_layer_changes(previous_settings, settings)
            if getattr(self, "show_all_selected_patterns", False):
                for field in (
                    "hkl_labels_visible",
                    "layer_observed_visible",
                    "layer_preview_peak_positions_visible",
                    "layer_total_profile_visible",
                    "layer_phase_profiles_visible",
                    "layer_background_visible",
                    "layer_difference_visible",
                    "layer_phase_ticks_visible",
                    "layer_phase_peak_sticks_visible",
                    "layer_coverage_markers_visible",
                    "layer_peak_labels_visible",
                    "layer_unknown_peaks_visible",
                ):
                    setattr(settings, field, getattr(previous_settings, field))
        self.plot_view_settings = settings
        if hasattr(self,"_save_workspace_preferences"):
            self._save_workspace_preferences()
        self._sync_plot_aspect_control(settings)
        self.plot_style = plot_style_from_view_settings(settings)
        self.plot_marker_size = self.plot_style.marker.size
        if quick_only:
            self._set_grid_visible(settings.grid_visible)
            self._apply_grid_settings(settings)
            if (
                getattr(self, "show_all_selected_patterns", False)
                and (
                    getattr(previous_settings, "legend_font_size", None) != settings.legend_font_size
                    or getattr(previous_settings, "multi_legend_alignment", None)
                    != settings.multi_legend_alignment
                    or getattr(previous_settings, "multi_legend_phase_names_visible", None)
                    != settings.multi_legend_phase_names_visible
                    or getattr(previous_settings, "multi_phase_legend_mode", None)
                    != settings.multi_phase_legend_mode
                )
                and hasattr(self, "_refresh_multi_pattern_legends")
            ):
                if (
                    getattr(previous_settings, "multi_legend_alignment", None)
                    != settings.multi_legend_alignment
                ):
                    self._multi_legend_manual_positions = {}
                self._refresh_multi_pattern_legends()
            self._set_legend_visible(settings.legend_visible)
            self._set_cursor_vertical_line_enabled(settings.cursor_vertical_line_visible)
            labels_changed = active_labels_changed or (
                getattr(previous_settings, "hkl_labels_visible", None) != settings.hkl_labels_visible
                or getattr(previous_settings, "layer_peak_labels_visible", None) != settings.layer_peak_labels_visible
            )
            self.show_hkl_labels = self._active_hkl_labels_requested() if hasattr(self, "_active_hkl_labels_requested") else bool(settings.hkl_labels_visible)
            if labels_changed and getattr(self, "match_candidates", None):
                self._recalculate_match_profile()
            self._apply_plot_layer_visibility_settings(settings)
            if self.legend_item is not None and settings.legend_visible:
                try:
                    self.legend_item.setLabelTextSize(f"{settings.legend_font_size*getattr(self,'_ui_density_factor',1.)}pt")
                except Exception:
                    pass
            self._sync_current_plot_export_tags()
            return
        self.grid_visible = settings.grid_visible
        self.show_hkl_labels = self._active_hkl_labels_requested() if hasattr(self, "_active_hkl_labels_requested") else bool(settings.hkl_labels_visible)
        self.cursor_vertical_line_enabled = settings.cursor_vertical_line_visible
        self.match_plot.setBackground(settings.plot_background)
        if settings.plot_border_visible and settings.plot_border_width > 0:
            self.match_plot.setStyleSheet(
                f"border: {settings.plot_border_width}px solid {settings.plot_border_color};"
            )
        else:
            self.match_plot.setStyleSheet("border: 0;")
        title = settings.title_text if settings.title_visible else ""
        self.match_plot.setTitle(title if title.strip() else None, color=settings.title_color, size=f"{settings.title_font_size*getattr(self,'_ui_density_factor',1.)}pt")
        self._sync_plot_canvas_margins(settings, bool(title.strip()))
        axis_visible = {
            "bottom": settings.bottom_axis_visible,
            "top": settings.top_axis_visible,
            "left": settings.left_axis_visible,
            "right": settings.right_axis_visible,
        }
        for axis_name, visible in axis_visible.items():
            self._set_axis_visible(axis_name, visible)
        self._set_axis_label(
            "bottom",
            settings.bottom_axis_label if settings.bottom_axis_visible and settings.bottom_axis_label_visible else "",
            _x_unit_for_scale(settings.bottom_axis_scale, settings.bottom_axis_unit)
            if settings.bottom_axis_visible and settings.bottom_axis_label_visible
            else "",
            settings,
        )
        self._set_axis_label(
            "top",
            settings.top_axis_label if settings.top_axis_visible and settings.top_axis_label_visible else "",
            _x_unit_for_scale(settings.top_axis_scale, settings.top_axis_unit)
            if settings.top_axis_visible and settings.top_axis_label_visible
            else "",
            settings,
        )
        self._set_axis_label(
            "left",
            settings.left_axis_label if settings.left_axis_visible and settings.left_axis_label_visible else "",
            settings.left_axis_unit if settings.left_axis_visible and settings.left_axis_label_visible else "",
            settings,
        )
        self._set_axis_label(
            "right",
            settings.right_axis_label if settings.right_axis_visible and settings.right_axis_label_visible else "",
            settings.right_axis_unit if settings.right_axis_visible and settings.right_axis_label_visible else "",
            settings,
        )
        axis_font = QFont()
        axis_font.setPointSizeF(settings.tick_font_size*getattr(self,"_ui_density_factor",1.))
        axis_values_visible = {
            "bottom": settings.bottom_axis_values_visible,
            "top": settings.top_axis_values_visible,
            "left": settings.left_axis_values_visible,
            "right": settings.right_axis_values_visible,
        }
        for axis_name in ("bottom", "left", "top", "right"):
            axis = self.match_plot.getAxis(axis_name)
            _apply_axis_appearance(
                axis,
                color=settings.axis_color,
                width=settings.axis_width,
                font=axis_font,
                tick_length=settings.tick_length,
                visible=axis_visible[axis_name],
                values_visible=axis_values_visible[axis_name],
            )
            self._apply_tick_spacing(axis_name, axis, settings)
        self._apply_grid_settings(settings)
        self._apply_x_axis_scale(settings)
        self._set_legend_visible(settings.legend_visible)
        self._set_cursor_vertical_line_enabled(settings.cursor_vertical_line_visible)
        self._apply_plot_layer_visibility_settings(settings)
        if self.legend_item is not None and settings.legend_visible:
            try:
                self.legend_item.setLabelTextSize(f"{settings.legend_font_size*getattr(self,'_ui_density_factor',1.)}pt")
            except Exception:
                pass
        self._apply_plot_view_aspect()
        if self.project.patterns:
            self._refresh_observed_pattern_plot()
            if getattr(self, "match_candidates", None):
                self._recalculate_match_profile()
        self._sync_current_plot_export_tags()

    def _sync_plot_canvas_margins(self, settings: PlotViewSettings, title_visible: bool) -> None:
        layout = getattr(self, "plot_canvas_layout", None)
        if layout is None:
            return
        # Reserve an actual inner gutter for axis text. Outer whitespace is
        # equal on all four sides as Qt measures labels and tick values.
        gutter=max(2,round(8*getattr(self,"_ui_density_factor",1.)))
        layout.setContentsMargins(gutter,gutter,gutter,gutter)
        plot_item = getattr(self.match_plot, 'plotItem', None)
        if plot_item is not None:
            inner=max(3,round(12*getattr(self,"_ui_density_factor",1.)))
            plot_item.layout.setContentsMargins(inner,inner,inner,inner)
        title_item = getattr(getattr(self.match_plot, "plotItem", None), "titleLabel", None)
        if title_item is not None:
            # Hiding LabelItem alone leaves PlotItem's fixed 30 px title row.
            if not title_visible:
                plot_item.setTitle(None)

    def _balance_plot_canvas(self) -> None:
        """Keep the plot frame centered with equal compact outer gutters.

        Axis labels and ticks are laid out inside the frame by pyqtgraph.
        The data rectangle does not need compensating whitespace outside it.
        """
        layout=getattr(self,'plot_canvas_layout',None)
        if layout is None:
            return
        gutter=max(2,round(8*getattr(self,'_ui_density_factor',1.)))
        previous=layout.contentsMargins()
        if (previous.left(),previous.top(),previous.right(),previous.bottom())==(gutter,)*4:
            return
        layout.setContentsMargins(gutter,gutter,gutter,gutter)
        layout.activate()
        self._apply_plot_view_aspect()

    def _sync_current_plot_export_tags(self) -> None:
        if not hasattr(self, "match_plot") or not hasattr(self, "plot_layers"):
            return
        sync_plot_export_tags(
            self.match_plot,
            self.plot_layers,
            grid_item=getattr(self, "_plot_grid_item", None),
            cursor_item=getattr(self, "cursor_position_line", None),
            legend_item=getattr(self, "legend_item", None),
        )

    def _apply_plot_layer_visibility_settings(self, settings: PlotViewSettings) -> None:
        layer_fields = {
            "observed": settings.layer_observed_visible,
            "preview_peak_positions": settings.layer_preview_peak_positions_visible,
            "preview_profile": settings.layer_preview_peak_positions_visible,
            "preview_peak_links": settings.layer_preview_peak_positions_visible,
            "peak_positions": settings.layer_preview_peak_positions_visible,
            "peak_links": settings.layer_preview_peak_positions_visible,
            "total_profile": settings.layer_total_profile_visible,
            "calculated_profile": settings.layer_total_profile_visible,
            "phase_profiles": settings.layer_phase_profiles_visible,
            "background": settings.layer_background_visible,
            "amorphous": True,
            "difference": settings.layer_difference_visible,
            "phase_ticks": settings.layer_phase_ticks_visible,
            "phase_peak_sticks": settings.layer_phase_peak_sticks_visible,
            "coverage_markers": settings.layer_coverage_markers_visible,
            "peak_labels": settings.layer_peak_labels_visible,
            "hkl": settings.hkl_labels_visible,
            "preview_hkl": settings.hkl_labels_visible,
            "unknown_peaks": settings.layer_unknown_peaks_visible,
        }
        for layer, visible in layer_fields.items():
            for item in self.plot_layers.get(layer, []):
                if hasattr(self, "_item_visible_for_layer"):
                    item.setVisible(self._item_visible_for_layer(layer, item, bool(visible)))
                else:
                    item.setVisible(bool(visible))
        if hasattr(self, "_rebuild_visible_legend"):
            self._rebuild_visible_legend()
        self._apply_zero_shift_display()

    def _apply_grid_settings(self, settings: PlotViewSettings) -> None:
        self.match_plot.showGrid(x=False, y=False)
        grid_item = getattr(self, "_plot_grid_item", None)
        if grid_item is None and settings.grid_visible:
            grid_item = StyledGridItem(
                self.match_plot.getViewBox(),
                self.match_plot.getAxis("bottom"),
                self.match_plot.getAxis("left"),
            )
            self._plot_grid_item = grid_item
        if grid_item is None:
            return
        grid_item.configure(
            color=settings.grid_color,
            width=settings.grid_width,
            alpha=settings.grid_alpha,
        )
        grid_item.setVisible(bool(settings.grid_visible))
        if settings.grid_visible:
            grid_item.refresh()

    def _set_axis_visible(self, axis_name: str, visible: bool) -> None:
        self.match_plot.showAxis(axis_name, visible)
        axis = self.match_plot.getAxis(axis_name)
        axis.setVisible(visible)
        if not visible:
            axis.setStyle(showValues=False, tickLength=0)
            self.match_plot.setLabel(axis_name, "")

    def _set_axis_label(self, axis_name: str, label: str, unit: str, settings: PlotViewSettings) -> None:
        self.match_plot.setLabel(
            axis_name,
            _axis_label(label, unit) if label else "",
            color=settings.axis_color,
            **{"font-size": f"{settings.label_font_size*getattr(self,'_ui_density_factor',1.)}pt"},
        )

    def _apply_tick_spacing(self, axis_name: str, axis, settings: PlotViewSettings) -> None:
        if axis_name in {"bottom", "top"}:
            major = float(settings.x_major_tick_spacing)
            minor = float(settings.x_minor_tick_spacing)
        else:
            major = float(settings.y_major_tick_spacing)
            minor = float(settings.y_minor_tick_spacing)
        try:
            if major > 0.0 or minor > 0.0:
                axis.setTickSpacing(major=major if major > 0.0 else None, minor=minor if minor > 0.0 else None)
            else:
                axis.setTickSpacing()
        except Exception:
            pass

    def _apply_plot_view_aspect(self) -> None:
        if not hasattr(self, "match_plot"):
            return
        self._update_plot_text_density()
        aspect = getattr(self.plot_view_settings, "aspect_ratio", None)
        source = getattr(self, "plot_canvas", None) or getattr(self, "center_splitter", None)
        source_width = int(source.width()) if source is not None else 0
        source_height = int(source.height()) if source is not None else 0
        if source_width < 60 or source_height < 40:
            self._plot_aspect_timer.start(50)
            return
        horizontal_margins = 0
        vertical_margins = 0
        layout = getattr(self, "plot_canvas_layout", None)
        if layout is not None:
            margins = layout.contentsMargins()
            horizontal_margins = margins.left() + margins.right()
            vertical_margins = margins.top() + margins.bottom()
        canvas_width = max(1, source_width - horizontal_margins)
        density=getattr(self,"_ui_density_factor",1.)
        minimum_height = round((120 if self.height()/density < 700 else 220)*density)
        canvas_height = max(1, source_height - vertical_margins)
        if aspect is None:
            if hasattr(self, "plot_canvas_layout"):
                self.plot_canvas_layout.setAlignment(self.match_plot, Qt.Alignment())
            self.match_plot.setMinimumSize(min(round(260*density),canvas_width),min(minimum_height,canvas_height))
            self.match_plot.setMaximumSize(16777215, 16777215)
            self.match_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.match_plot.updateGeometry()
            self._plot_balance_timer.start(0)
            return
        if hasattr(self, "plot_canvas_layout"):
            self.plot_canvas_layout.setAlignment(self.match_plot, Qt.AlignmentFlag.AlignCenter)
        target_width = canvas_width
        target_height = int(target_width / max(float(aspect), 0.1))
        if target_height > canvas_height:
            target_height = canvas_height
            target_width = int(target_height * float(aspect))
        target_width = max(1, min(target_width, canvas_width))
        target_height = max(1, min(target_height, canvas_height))
        self.match_plot.setMinimumSize(1, 1)
        self.match_plot.setMaximumSize(16777215, 16777215)
        self.match_plot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.match_plot.setFixedSize(target_width, target_height)
        self.match_plot.updateGeometry()
        self._plot_balance_timer.start(0)

    def _update_plot_text_density(self):
        settings=self.plot_view_settings
        factor=getattr(self,'_ui_density_factor',1.)
        title = settings.title_text if settings.title_visible and settings.title_text.strip() else None
        self.match_plot.setTitle(title, color=settings.title_color, size=f'{settings.title_font_size*factor}pt')
        font=QFont();font.setPointSizeF(max(3,settings.tick_font_size*factor))
        for side in ('left','right','top','bottom'):
            axis=self.match_plot.getAxis(side)
            axis.setTickFont(font)
            axis.setLabel(text=axis.labelText,units=axis.labelUnits,
                          unitPrefix=axis.labelUnitPrefix,
                          color=settings.axis_color,
                          **{'font-size':f'{max(3,settings.label_font_size*factor)}pt'})
        legend=getattr(self,'legend_item',None)
        if legend is not None:legend.setLabelTextSize(f'{max(3,settings.legend_font_size*factor)}pt')

    def _apply_x_axis_scale(self, settings: PlotViewSettings) -> None:
        axis_scales = {
            "bottom": settings.bottom_axis_scale,
            "top": settings.top_axis_scale,
        }
        for axis_name, scale in axis_scales.items():
            axis = self.match_plot.getAxis(axis_name)
            if not hasattr(axis, "_xrd_default_tick_strings"):
                axis._xrd_default_tick_strings = axis.tickStrings
            if scale == "d":
                axis.tickStrings = lambda values, scale, spacing, owner=self: owner._d_axis_tick_strings(
                    values,
                    scale,
                    spacing,
                )
            else:
                axis.tickStrings = axis._xrd_default_tick_strings
        self.match_plot.plotItem.update()

    def _d_axis_tick_strings(self, values, _scale, _spacing) -> list[str]:
        wavelength = self._active_wavelength()
        labels = []
        for value in values:
            try:
                two_theta = float(value)
                theta = math.radians(two_theta / 2.0)
                if theta <= 0.0:
                    labels.append("")
                    continue
                d_spacing = wavelength / (2.0 * math.sin(theta))
                labels.append(f"{d_spacing:.3g}")
            except Exception:
                labels.append("")
        return labels

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self,"_interface_scale_timer"):
            self._interface_scale_timer.start(30)
        if hasattr(self, "match_plot"):
            self._plot_aspect_timer.start(0)
