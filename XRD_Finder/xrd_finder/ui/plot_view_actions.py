from __future__ import annotations

import math

import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QSizePolicy, QWidget

from xrd_finder.ui.plot_view_settings import PlotViewSettings, PlotViewSettingsWidget, plot_style_from_view_settings


def _axis_label(label: str, unit: str) -> str:
    unit = unit.strip()
    return f"{label} [{unit}]" if unit else label


def _x_unit_for_scale(scale: str, unit: str) -> str:
    unit = unit.strip()
    if scale == "d" and unit.lower() in {"", "deg", "degree", "degrees"}:
        return "A"
    if scale == "2theta" and unit.lower() in {"", "a", "angstrom", "angstroms"}:
        return "deg"
    return unit


class PhaseFinderPlotViewActionsMixin:
    def _init_plot_view_state(self) -> None:
        self.plot_settings_panel: PlotViewSettingsWidget | None = None
        self.plot_view_settings = PlotViewSettings()
        self.plot_style = plot_style_from_view_settings(self.plot_view_settings)
        self.plot_marker_size = self.plot_style.marker.size
        self._plot_grid_item = None

    def _plot_view_tab(self) -> QWidget:
        self.plot_settings_panel = PlotViewSettingsWidget()
        self.plot_settings_panel.settingsChanged.connect(self._apply_plot_view_settings)
        self.plot_settings_panel.profileCandidateColorRequested.connect(self._change_profile_candidate_color)
        QTimer.singleShot(0, lambda: self._apply_plot_view_settings(self.plot_settings_panel.settings()))
        QTimer.singleShot(0, self._update_profile_view_context)
        return self.plot_settings_panel

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

    def _apply_plot_view_settings(self, settings: PlotViewSettings) -> None:
        previous_settings = getattr(self, "plot_view_settings", None)
        quick_fields = {
            "grid_visible",
            "grid_alpha",
            "grid_color",
            "grid_width",
            "legend_visible",
            "legend_font_size",
            "cursor_vertical_line_visible",
            "hkl_labels_visible",
            "layer_observed_visible",
            "layer_preview_peak_positions_visible",
            "layer_total_profile_visible",
            "layer_phase_profiles_visible",
            "layer_background_visible",
            "layer_phase_ticks_visible",
            "layer_coverage_markers_visible",
            "layer_peak_labels_visible",
            "layer_unknown_peaks_visible",
        }
        quick_only = previous_settings is not None and all(
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
                    "layer_phase_ticks_visible",
                    "layer_coverage_markers_visible",
                    "layer_peak_labels_visible",
                    "layer_unknown_peaks_visible",
                ):
                    setattr(settings, field, getattr(previous_settings, field))
        self.plot_view_settings = settings
        self.plot_style = plot_style_from_view_settings(settings)
        self.plot_marker_size = self.plot_style.marker.size
        if quick_only:
            self._set_grid_visible(settings.grid_visible)
            self._apply_grid_settings(settings)
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
                    self.legend_item.setLabelTextSize(f"{settings.legend_font_size}pt")
                except Exception:
                    pass
            return
        self.grid_visible = settings.grid_visible
        self.show_hkl_labels = self._active_hkl_labels_requested() if hasattr(self, "_active_hkl_labels_requested") else bool(settings.hkl_labels_visible)
        self.cursor_vertical_line_enabled = settings.cursor_vertical_line_visible
        self._apply_grid_settings(settings)
        self.match_plot.setBackground(settings.plot_background)
        if settings.plot_border_visible and settings.plot_border_width > 0:
            self.match_plot.setStyleSheet(
                f"border: {settings.plot_border_width}px solid {settings.plot_border_color};"
            )
        else:
            self.match_plot.setStyleSheet("border: 0;")
        title = settings.title_text if settings.title_visible else ""
        self.match_plot.setTitle(title, color=settings.title_color, size=f"{settings.title_font_size}pt")
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
        axis_font.setPointSize(settings.tick_font_size)
        axis_values_visible = {
            "bottom": settings.bottom_axis_values_visible,
            "top": settings.top_axis_values_visible,
            "left": settings.left_axis_values_visible,
            "right": settings.right_axis_values_visible,
        }
        tick_length = abs(int(settings.tick_length))
        for axis_name in ("bottom", "left", "top", "right"):
            axis = self.match_plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(settings.axis_color, width=settings.axis_width))
            axis.setTextPen(pg.mkPen(settings.axis_color))
            axis.setTickFont(axis_font)
            axis.setStyle(
                showValues=bool(axis_visible[axis_name] and axis_values_visible[axis_name]),
                tickLength=-tick_length if axis_visible[axis_name] else 0,
            )
            self._apply_tick_spacing(axis_name, axis, settings)
        self._apply_x_axis_scale(settings)
        self._set_legend_visible(settings.legend_visible)
        self._set_cursor_vertical_line_enabled(settings.cursor_vertical_line_visible)
        self._apply_plot_layer_visibility_settings(settings)
        if self.legend_item is not None and settings.legend_visible:
            try:
                self.legend_item.setLabelTextSize(f"{settings.legend_font_size}pt")
            except Exception:
                pass
        self._apply_plot_view_aspect()
        if self.project.patterns:
            self._refresh_observed_pattern_plot()

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
            "difference": settings.layer_difference_visible,
            "phase_ticks": settings.layer_phase_ticks_visible,
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

    def _apply_grid_settings(self, settings: PlotViewSettings) -> None:
        if self._plot_grid_item is not None:
            try:
                self.match_plot.removeItem(self._plot_grid_item)
            except Exception:
                pass
            self._plot_grid_item = None
        alpha = max(0.0, min(float(settings.grid_alpha), 1.0)) if settings.grid_visible else 0.0
        self.match_plot.showGrid(x=bool(settings.grid_visible), y=bool(settings.grid_visible), alpha=alpha)

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
            **{"font-size": f"{settings.label_font_size}pt"},
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
        aspect = getattr(self.plot_view_settings, "aspect_ratio", None)
        source = getattr(self, "plot_canvas", None) or getattr(self, "center_splitter", None)
        source_width = int(source.width()) if source is not None else 0
        source_height = int(source.height()) if source is not None else 0
        if source_width < 120 or source_height < 120:
            QTimer.singleShot(50, self._apply_plot_view_aspect)
            return
        canvas_width = max(source_width - 22, 260)
        canvas_height = max(source_height - 22, 220)
        if aspect is None:
            if hasattr(self, "plot_canvas_layout"):
                self.plot_canvas_layout.setAlignment(self.match_plot, Qt.Alignment())
            self.match_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.match_plot.setMinimumSize(260, 220)
            self.match_plot.setMaximumSize(16777215, 16777215)
            self.match_plot.updateGeometry()
            return
        if hasattr(self, "plot_canvas_layout"):
            self.plot_canvas_layout.setAlignment(self.match_plot, Qt.AlignmentFlag.AlignCenter)
        target_width = canvas_width
        target_height = int(target_width / max(float(aspect), 0.1))
        if target_height > canvas_height:
            target_height = canvas_height
            target_width = int(target_height * float(aspect))
        target_width = max(240, min(target_width, canvas_width))
        target_height = max(180, min(target_height, canvas_height))
        self.match_plot.setMinimumSize(240, 180)
        self.match_plot.setMaximumSize(16777215, 16777215)
        self.match_plot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.match_plot.setFixedSize(target_width, target_height)
        self.match_plot.updateGeometry()

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
        if hasattr(self, "match_plot"):
            QTimer.singleShot(0, self._apply_plot_view_aspect)
