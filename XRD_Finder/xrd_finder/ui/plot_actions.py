from __future__ import annotations

import re
from pathlib import Path

import pyqtgraph as pg

from xrd_finder.ui.pattern_plot_helpers import ensure_right_legend
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox


class PhaseFinderPlotActionsMixin:
    def _show_plot_context_menu(self, point) -> None:
        menu = QMenu(self)
        menu.addAction("Export image...", self._export_plot_image)
        menu.addSeparator()
        menu.addAction("Show full pattern", self._full_pattern_range)
        menu.addSeparator()
        menu.addAction(self._layer_action("Experimental pattern", "observed", enabled=True))
        menu.addAction(self._layer_action("Candidate preview sticks", "preview_peak_positions", enabled=True))
        menu.addAction(self._layer_action("Calculated total", "total_profile", enabled=True))
        menu.addAction(self._layer_action("Individual profiles", "phase_profiles", enabled=True))
        menu.addAction(self._layer_action("Background", "background", enabled=True))
        menu.addAction(self._layer_action("Difference curve", "difference", enabled=True))
        menu.addAction(self._layer_action("Phase tick marks", "phase_ticks", enabled=True))
        menu.addAction(self._layer_action("Assignment markers", "coverage_markers", enabled=True))
        hkl_action = menu.addAction("HKL labels")
        hkl_action.setCheckable(True)
        hkl_action.setChecked(self._plot_layer_setting("hkl"))
        hkl_action.toggled.connect(self._set_hkl_labels_enabled)
        peak_label_action = menu.addAction("Peak labels")
        peak_label_action.setCheckable(True)
        peak_label_action.setChecked(self._plot_layer_setting("peak_labels"))
        peak_label_action.toggled.connect(self._set_peak_labels_enabled)
        menu.addAction(self._layer_action("Unknown peaks", "unknown_peaks", enabled=True))
        menu.addSeparator()
        menu.addAction("Hide profile overlays", lambda: self._set_profile_overlays_visible(False))
        menu.addAction("Show profile overlays", lambda: self._set_profile_overlays_visible(True))
        menu.addAction("Clear profile overlays", self._clear_calculated_overlay)
        menu.exec(self.match_plot.mapToGlobal(point))

    def _export_plot_image(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export image",
            str(Path(self._last_directory()) / "xrd_finder_plot.png"),
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg)",
        )
        if not path:
            return
        self._remember_directory(path)
        if not re.search(r"\.(png|jpe?g)$", path, flags=re.IGNORECASE):
            path += ".png"
        try:
            from pyqtgraph.exporters import ImageExporter

            exporter = ImageExporter(self.match_plot.plotItem)
            params = exporter.parameters()
            current_width = max(float(self.match_plot.width()), 1.0)
            target_width = max(3200.0, current_width * 2.0)
            params["width"] = target_width
            exporter.export(path)
        except Exception as exc:
            if not self.match_plot.grab().save(path):
                QMessageBox.warning(self, "Export image", f"Could not save current plot image:\n{exc}")

    def _layer_action(self, label: str, layer: str, checked: bool | None = None, enabled: bool = True):
        action = self._make_action(label)
        action.setCheckable(True)
        has_items = bool(self.plot_layers.get(layer, []))
        action.setEnabled(bool(enabled))
        saved_visible = self._plot_layer_setting(layer)
        action.setChecked(saved_visible if checked is None else checked)
        if enabled:
            action.toggled.connect(lambda visible, key=layer: self._set_layer_visible(key, visible))
        if not has_items:
            action.setToolTip("The setting will be applied when this layer is drawn.")
        return action

    def _make_action(self, label: str):
        return QAction(label, self)

    _PLOT_LAYER_FIELDS = {
        "observed": ("layer_observed_visible", "layer_observed_checkbox"),
        "preview_peak_positions": ("layer_preview_peak_positions_visible", "layer_preview_peak_positions_checkbox"),
        "preview_profile": ("layer_preview_peak_positions_visible", "layer_preview_peak_positions_checkbox"),
        "preview_peak_links": ("layer_preview_peak_positions_visible", "layer_preview_peak_positions_checkbox"),
        "peak_positions": ("layer_preview_peak_positions_visible", "layer_preview_peak_positions_checkbox"),
        "peak_links": ("layer_preview_peak_positions_visible", "layer_preview_peak_positions_checkbox"),
        "total_profile": ("layer_total_profile_visible", "layer_total_profile_checkbox"),
        "calculated_profile": ("layer_total_profile_visible", "layer_total_profile_checkbox"),
        "phase_profiles": ("layer_phase_profiles_visible", "layer_phase_profiles_checkbox"),
        "background": ("layer_background_visible", "layer_background_checkbox"),
        "difference": ("layer_difference_visible", "layer_difference_checkbox"),
        "phase_ticks": ("layer_phase_ticks_visible", "layer_phase_ticks_checkbox"),
        "coverage_markers": ("layer_coverage_markers_visible", "layer_coverage_markers_checkbox"),
        "peak_labels": ("layer_peak_labels_visible", "layer_peak_labels_checkbox"),
        "hkl": ("hkl_labels_visible", "hkl_labels_checkbox"),
        "preview_hkl": ("hkl_labels_visible", "hkl_labels_checkbox"),
        "unknown_peaks": ("layer_unknown_peaks_visible", "layer_unknown_peaks_checkbox"),
    }
    _HKL_LAYER_FIELDS = ("hkl_labels_visible",)

    def _active_layer_pattern_id(self) -> str | None:
        pattern = self._active_pattern() if hasattr(self, "_active_pattern") else None
        return getattr(pattern, "id", None) if pattern is not None else None

    def _active_profile_layer_state(self) -> dict[str, bool]:
        pattern_id = self._active_layer_pattern_id()
        if not pattern_id:
            return {}
        state = self.profile_states.setdefault(pattern_id, {}) if hasattr(self, "profile_states") else {}
        layer_state = state.setdefault("layer_visibility", {}) if isinstance(state, dict) else {}
        if not isinstance(layer_state, dict):
            state["layer_visibility"] = {}
            layer_state = state["layer_visibility"]
        return layer_state

    def _layer_setting_fields(self, layer: str) -> tuple[str, ...]:
        if layer in {"hkl", "preview_hkl"}:
            return self._HKL_LAYER_FIELDS
        field = self._PLOT_LAYER_FIELDS.get(layer, (None, None))[0]
        return (field,) if field else ()

    def _field_setting_value(self, field: str, default: bool = True) -> bool:
        if hasattr(self, "plot_view_settings"):
            return bool(getattr(self.plot_view_settings, field, default))
        return bool(default)

    def _plot_layer_setting(self, layer: str) -> bool:
        state = self._active_profile_layer_state() if getattr(self, "show_all_selected_patterns", False) else {}
        if layer in {"hkl", "preview_hkl"}:
            return bool(state.get("hkl_labels_visible", self._field_setting_value("hkl_labels_visible", False)))
        fields = self._layer_setting_fields(layer)
        for field in fields:
            if field in state:
                return bool(state[field])
        if fields:
            return self._field_setting_value(fields[0], True)
        return self._layer_visible(layer)

    def _active_hkl_labels_requested(self) -> bool:
        if getattr(self, "show_all_selected_patterns", False):
            state = self._active_profile_layer_state()
            return bool(state.get("hkl_labels_visible", self._field_setting_value("hkl_labels_visible", False)))
        return bool(self._field_setting_value("hkl_labels_visible", False))

    def _active_peak_labels_requested(self) -> bool:
        if getattr(self, "show_all_selected_patterns", False):
            state = self._active_profile_layer_state()
            return bool(state.get("layer_peak_labels_visible", self._field_setting_value("layer_peak_labels_visible", False)))
        return bool(self._field_setting_value("layer_peak_labels_visible", False))

    def _active_peak_text_requested(self) -> bool:
        return self._active_hkl_labels_requested() or self._active_peak_labels_requested()

    def _item_visible_for_layer(self, layer: str, item, fallback_visible: bool) -> bool:
        pattern_id = getattr(item, "_xrd_pattern_id", None)
        if getattr(self, "show_all_selected_patterns", False) and pattern_id and hasattr(self, "profile_states"):
            state = self.profile_states.get(pattern_id, {}).get("layer_visibility", {})
            if isinstance(state, dict):
                if layer in {"hkl", "preview_hkl"}:
                    return bool(state.get("hkl_labels_visible", self._field_setting_value("hkl_labels_visible", False)))
                for field in self._layer_setting_fields(layer):
                    if field in state:
                        return bool(state[field])
        return bool(fallback_visible)

    def _scoped_layer_items(self, layer: str):
        items = self.plot_layers.get(layer, [])
        if not getattr(self, "show_all_selected_patterns", False):
            return items
        active_id = self._active_layer_pattern_id()
        if not active_id:
            return []
        return [item for item in items if getattr(item, "_xrd_pattern_id", None) == active_id]

    def _sync_plot_layer_control(self, layer: str, visible: bool) -> None:
        visible = bool(visible)
        fields = self._layer_setting_fields(layer)
        if getattr(self, "show_all_selected_patterns", False):
            state = self._active_profile_layer_state()
            for field in fields:
                state[field] = visible
        elif hasattr(self, "plot_view_settings"):
            for field in fields:
                setattr(self.plot_view_settings, field, visible)
        if layer in {"hkl", "preview_hkl"}:
            self.show_hkl_labels = self._active_hkl_labels_requested() if hasattr(self, "_active_hkl_labels_requested") else visible
            self._sync_view_checkbox("hkl_labels_checkbox", visible)
            return
        checkbox_name = self._PLOT_LAYER_FIELDS.get(layer, (None, None))[1]
        if checkbox_name:
            self._sync_view_checkbox(checkbox_name, visible)

    def _capture_active_profile_layer_changes(self, previous_settings, settings) -> None:
        if not getattr(self, "show_all_selected_patterns", False):
            return
        state = self._active_profile_layer_state()
        fields = {
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
        for field in fields:
            if getattr(previous_settings, field, None) != getattr(settings, field, None):
                state[field] = bool(getattr(settings, field))

    def _sync_profile_layer_controls_to_active(self) -> None:
        if not getattr(self, "show_all_selected_patterns", False):
            return
        state = self._active_profile_layer_state()
        for layer, (field, checkbox_name) in self._PLOT_LAYER_FIELDS.items():
            if layer in {"preview_profile", "preview_peak_links", "peak_positions", "peak_links", "calculated_profile", "preview_hkl"}:
                continue
            if checkbox_name is None:
                continue
            visible = self._plot_layer_setting(layer)
            self._sync_view_checkbox(checkbox_name, visible)
        self._sync_view_checkbox("hkl_labels_checkbox", bool(state.get("hkl_labels_visible", self._field_setting_value("hkl_labels_visible", False))))
        self._sync_view_checkbox("layer_peak_labels_checkbox", bool(state.get("layer_peak_labels_visible", self._field_setting_value("layer_peak_labels_visible", False))))

    def _layer_visible(self, layer: str) -> bool:
        items = self._scoped_layer_items(layer)
        return bool(items) and all(item.isVisible() for item in items)

    def _set_layer_visible(self, layer: str, visible: bool) -> None:
        visible = bool(visible)
        self._sync_plot_layer_control(layer, visible)
        for item in self._scoped_layer_items(layer):
            item.setVisible(visible)
        self._rebuild_visible_legend()

    def _set_profile_overlays_visible(self, visible: bool) -> None:
        for layer in (
            "preview_peak_positions",
            "total_profile",
            "phase_profiles",
            "background",
            "phase_ticks",
            "coverage_markers",
            "peak_labels",
            "unknown_peaks",
            "hkl",
            "preview_hkl",
        ):
            self._set_layer_visible(layer, visible)

    def _set_calculated_visible(self, visible: bool) -> None:
        self._set_layer_visible("calculated_profile", visible)
        self._set_layer_visible("total_profile", visible)
        self._set_layer_visible("phase_profiles", visible)
        self._set_layer_visible("background", visible)
        self._set_layer_visible("difference", visible)
        self._set_layer_visible("peak_positions", visible)
        self._set_layer_visible("phase_ticks", visible)
        self._set_layer_visible("peak_links", visible)
        self._set_layer_visible("coverage_markers", visible)
        self._set_layer_visible("peak_labels", visible)
        self._set_layer_visible("unknown_peaks", visible)
        self._set_layer_visible("hkl", visible)
        self._set_layer_visible("preview_profile", visible)
        self._set_layer_visible("preview_peak_positions", visible)
        self._set_layer_visible("preview_peak_links", visible)
        self._set_layer_visible("preview_hkl", visible)

    _PROFILE_OVERLAY_LAYERS = (
        "calculated_profile",
        "total_profile",
        "phase_profiles",
        "background",
        "difference",
        "peak_positions",
        "phase_ticks",
        "peak_links",
        "coverage_markers",
        "peak_labels",
        "unknown_peaks",
        "hkl",
        "candidate_markers",
        "preview_profile",
        "preview_peak_positions",
        "preview_peak_links",
        "preview_hkl",
        "legend_info",
    )

    _PREVIEW_OVERLAY_LAYERS = (
        "preview_profile",
        "preview_peak_positions",
        "preview_peak_links",
        "preview_hkl",
    )

    _TRANSIENT_CANDIDATE_PREVIEW_LAYERS = (
        "calculated_profile",
        "preview_profile",
        "preview_peak_positions",
        "preview_peak_links",
        "preview_hkl",
    )

    def _remove_plot_layer_items(self, layers, *, rebuild_legend: bool = True) -> None:
        for layer in layers:
            for item in list(self.plot_layers.get(layer, [])):
                try:
                    self.match_plot.removeItem(item)
                except Exception:
                    pass
            self.plot_layers[layer] = []
        if rebuild_legend:
            self._rebuild_visible_legend()

    def _clear_profile_plot_layers(self, *, include_observed: bool = False, rebuild_legend: bool = True) -> None:
        layers = list(self._PROFILE_OVERLAY_LAYERS)
        if include_observed:
            layers.insert(0, "observed")
        self._remove_plot_layer_items(layers, rebuild_legend=rebuild_legend)

    def _clear_calculated_overlay(self) -> None:
        self._clear_profile_plot_layers(rebuild_legend=False)
        self.active_overlay_entry_id = None
        self._rebuild_visible_legend()

    def _clear_preview_overlay(self) -> None:
        self._remove_plot_layer_items(self._PREVIEW_OVERLAY_LAYERS)

    def _transient_candidate_preview_counts(self) -> dict[str, int]:
        return {layer: len(self.plot_layers.get(layer, [])) for layer in self._TRANSIENT_CANDIDATE_PREVIEW_LAYERS}

    def _tag_transient_candidate_preview_items(self, before_counts: dict[str, int]) -> None:
        for layer, count in before_counts.items():
            for item in self.plot_layers.get(layer, [])[count:]:
                try:
                    item._xrd_transient_candidate_preview = True
                except Exception:
                    pass

    def _clear_transient_candidate_preview(self) -> None:
        for layer in self._TRANSIENT_CANDIDATE_PREVIEW_LAYERS:
            kept = []
            for item in list(self.plot_layers.get(layer, [])):
                if getattr(item, "_xrd_transient_candidate_preview", False):
                    try:
                        self.match_plot.removeItem(item)
                    except Exception:
                        pass
                else:
                    kept.append(item)
            self.plot_layers[layer] = kept
        self._rebuild_visible_legend()

    def _set_hkl_labels_enabled(self, visible: bool) -> None:
        visible = bool(visible)
        if getattr(self, "show_all_selected_patterns", False):
            state = self._active_profile_layer_state()
            state["hkl_labels_visible"] = visible
        elif hasattr(self, "plot_view_settings"):
            self.plot_view_settings.hkl_labels_visible = visible
        self.show_hkl_labels = self._active_hkl_labels_requested() if hasattr(self, "_active_hkl_labels_requested") else visible
        self._sync_view_checkbox("hkl_labels_checkbox", visible)
        self._refresh_profile_label_layers()

    def _set_peak_labels_enabled(self, visible: bool) -> None:
        visible = bool(visible)
        if getattr(self, "show_all_selected_patterns", False):
            state = self._active_profile_layer_state()
            state["layer_peak_labels_visible"] = visible
        elif hasattr(self, "plot_view_settings"):
            self.plot_view_settings.layer_peak_labels_visible = visible
        self._sync_view_checkbox("layer_peak_labels_checkbox", visible)
        self._refresh_profile_label_layers()

    def _refresh_profile_label_layers(self) -> None:
        displayed_patterns = self._patterns_to_display() if self.show_all_selected_patterns else [self._active_pattern()]
        has_profile_candidates = any(self._profile_candidates_for_pattern(pattern) for pattern in displayed_patterns if pattern is not None)
        if has_profile_candidates:
            self._recalculate_match_profile()
            row = self.candidate_table.currentRow()
            if row >= 0:
                self._preview_candidate_row(row)
        elif self.active_overlay_entry_id:
            row = self.candidate_table.currentRow()
            if row >= 0:
                self.active_overlay_entry_id = None
                self._preview_candidate_row(row)
        else:
            self._apply_plot_layer_visibility_settings(self.plot_view_settings)

    def _sync_view_checkbox(self, name: str, visible: bool) -> None:
        panel = getattr(self, "plot_settings_panel", None)
        checkbox = getattr(panel, name, None)
        if checkbox is not None and checkbox.isChecked() != bool(visible):
            previous = checkbox.blockSignals(True)
            checkbox.setChecked(bool(visible))
            checkbox.blockSignals(previous)

    def _plot_item_label(self, item) -> str:
        custom_label = getattr(item, "_xrd_legend_label", "")
        if custom_label:
            return str(custom_label).strip()
        opts = getattr(item, "opts", None)
        if isinstance(opts, dict):
            label = opts.get("name") or ""
            if label:
                return str(label).strip()
        name = getattr(item, "name", None)
        if callable(name):
            try:
                return str(name() or "").strip()
            except Exception:
                return ""
        return ""

    def _legend_label_for_layer(self, layer: str, label: str) -> str:
        if layer in {
            "preview_peak_positions",
            "peak_positions",
            "preview_peak_links",
            "peak_links",
            "phase_ticks",
            "coverage_markers",
            "peak_labels",
            "hkl",
            "preview_hkl",
        }:
            return ""
        if label.startswith("preview peaks "):
            return ""
        if label.startswith("phase "):
            return label[6:].strip() or label
        if label.startswith("PDF-2 reference "):
            return label.replace("PDF-2 reference ", "PDF-2 ", 1).strip()
        if label.startswith("RRUFF reference "):
            return label.replace("RRUFF reference ", "RRUFF ", 1).strip()
        return label

    def _legend_sample_item(self, layer: str, item):
        if layer != "phase_profiles":
            return item
        opts = getattr(item, "opts", {}) or {}
        pen = opts.get("pen") if isinstance(opts, dict) else None
        if pen is None:
            return item
        try:
            color = pen.color()
        except Exception:
            color = "#ffffff"
        try:
            width = max(float(pen.widthF()), 2.8)
        except Exception:
            width = 2.8
        return pg.PlotDataItem(
            [0.0, 1.0],
            [0.0, 0.0],
            pen=pg.mkPen(color, width=width),
            symbol="o",
            symbolSize=8,
            symbolBrush=color,
            symbolPen=pg.mkPen(color, width=1.4),
        )

    def _rebuild_visible_legend(self) -> None:
        settings = getattr(self, "plot_view_settings", None)
        if settings is not None and not bool(getattr(settings, "legend_visible", True)):
            if getattr(self, "legend_item", None) is not None:
                self.legend_item.setVisible(False)
            return
        if not hasattr(self, "match_plot"):
            return
        legend = ensure_right_legend(self.match_plot, clear=True)
        self.legend_item = legend
        ordered_layers = [
            "observed",
            "phase_profiles",
            "preview_profile",
            "preview_peak_positions",
            "background",
            "total_profile",
            "calculated_profile",
            "difference",
            "unknown_peaks",
            "legend_info",
        ]
        seen: set[str] = set()
        for layer in ordered_layers + [key for key in self.plot_layers if key not in ordered_layers]:
            for item in self.plot_layers.get(layer, []):
                try:
                    if not item.isVisible():
                        continue
                except Exception:
                    continue
                label = self._plot_item_label(item)
                label = self._legend_label_for_layer(layer, label)
                if not label or label in seen:
                    continue
                try:
                    legend.addItem(self._legend_sample_item(layer, item), label)
                    seen.add(label)
                except Exception:
                    pass
        legend.setVisible(bool(seen))
        settings = getattr(self, "plot_view_settings", None)
        if settings is not None:
            try:
                legend.setLabelTextSize(f"{settings.legend_font_size}pt")
            except Exception:
                pass

    def _set_grid_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.grid_visible = visible
        if hasattr(self, "plot_view_settings"):
            self.plot_view_settings.grid_visible = visible
            self._apply_grid_settings(self.plot_view_settings)
        else:
            self.match_plot.showGrid(x=False, y=False)
        self._sync_view_checkbox("grid_checkbox", visible)

    def _set_legend_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if hasattr(self, "plot_view_settings"):
            self.plot_view_settings.legend_visible = visible
        self._sync_view_checkbox("legend_checkbox", visible)
        if visible:
            self._rebuild_visible_legend()
            return
        if self.legend_item is not None:
            self.legend_item.setVisible(False)

    def _add_legend_info(self, text: str) -> None:
        item = self.match_plot.plot([], [], pen=pg.mkPen("#00000000", width=0.1), name=text)
        self.plot_layers["legend_info"].append(item)

    def _full_pattern_range(self) -> None:
        self._reset_match_plot_view()

    def _set_cursor_vertical_line_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self.cursor_vertical_line_enabled = enabled
        if hasattr(self, "plot_view_settings"):
            self.plot_view_settings.cursor_vertical_line_visible = enabled
        self._sync_view_checkbox("cursor_line_checkbox", enabled)
        self._ensure_cursor_position_items()
        self.cursor_position_line.setVisible(enabled)

    def _ensure_cursor_position_items(self) -> None:
        if getattr(self, "cursor_position_line", None) is None:
            pen = pg.mkPen("#5f6368", width=1.2, style=Qt.PenStyle.SolidLine)
            self.cursor_position_line = pg.InfiniteLine(angle=90, movable=False, pen=pen)
            self.cursor_position_line.setZValue(5000)
            self.cursor_position_line.setVisible(False)
            self.match_plot.addItem(self.cursor_position_line, ignoreBounds=True)
        if getattr(self, "cursor_position_proxy", None) is None:
            self.cursor_position_proxy = pg.SignalProxy(
                self.match_plot.scene().sigMouseMoved,
                rateLimit=60,
                slot=self._update_cursor_position_readout,
            )

    def _update_cursor_position_readout(self, event) -> None:
        if not getattr(self, "cursor_position_enabled", False):
            return
        scene_pos = event[0] if isinstance(event, tuple) else event
        view_box = self.match_plot.plotItem.vb
        if not view_box.sceneBoundingRect().contains(scene_pos):
            if getattr(self, "cursor_position_status_label", None) is not None:
                self.cursor_position_status_label.setText("2theta: -    I: -")
            return
        view_pos = view_box.mapSceneToView(scene_pos)
        two_theta = float(view_pos.x())
        intensity = float(view_pos.y())
        self.cursor_position_line.setPos(two_theta)
        self.cursor_position_line.setVisible(bool(getattr(self, "cursor_vertical_line_enabled", False)))
        if getattr(self, "cursor_position_status_label", None) is not None:
            self.cursor_position_status_label.setText(f"2theta: {two_theta:.3f} deg    I: {intensity:.3g}")
