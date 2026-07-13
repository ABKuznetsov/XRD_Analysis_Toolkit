from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from xrd_finder.core.pattern import Pattern
from xrd_finder.services.preprocessing_service import auto_preprocess_for_scoring
from xrd_finder.ui.observed_patterns import apply_pattern_offsets, load_observed_patterns, normalize_intensity, observed_pattern_data, processed_pattern_data
from xrd_finder.ui.pattern_plot_helpers import (
    calculate_profile_for_structure,
    ensure_right_legend,
    plot_hkl_sticks,
    plot_profile,
    scale_profile_to_reference,
)


class PhaseFinderObservedPatternActionsMixin:
    def _set_pattern_display_mode(self, mode: str) -> None:
        if hasattr(self, "_save_active_profile_state"):
            self._save_active_profile_state()
        self.show_all_selected_patterns = mode == "All selected"
        if hasattr(self, "_clear_profile_plot_layers"):
            self._clear_profile_plot_layers(include_observed=True, rebuild_legend=False)
            self.active_overlay_entry_id = None
        else:
            if hasattr(self, "_clear_calculated_overlay"):
                self._clear_calculated_overlay()
            if hasattr(self, "_clear_preview_overlay"):
                self._clear_preview_overlay()
        self._refresh_observed_pattern_plot()
        self._rerun_active_calculation()
        if hasattr(self, "_update_profile_view_context"):
            self._update_profile_view_context()

    def _set_pattern_stack_offset(self, percent: int) -> None:
        self.pattern_stack_offset_percent = max(0, int(percent))
        if self.show_all_selected_patterns:
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation()

    def _set_pattern_normalization(self, enabled: bool) -> None:
        self.normalize_observed_patterns = bool(enabled)
        if hasattr(self, "_auto_scoring_cache"):
            self._auto_scoring_cache.clear()
        if hasattr(self, "_invalidate_match_profile_cache"):
            self._invalidate_match_profile_cache()
        self._clear_probability_caches()
        self._refresh_observed_pattern_plot()
        self._rerun_active_calculation()

    def _normalized_observed_data(self, data: np.ndarray | None) -> np.ndarray | None:
        if data is None or not self.normalize_observed_patterns:
            return data
        return normalize_intensity(data)

    def _pattern_processed_observed_data(self, pattern: Pattern | None) -> np.ndarray | None:
        processed = processed_pattern_data(pattern)
        if processed is not None:
            return self._normalized_observed_data(processed)
        if not self.normalize_observed_patterns:
            return None
        return self._normalized_observed_data(observed_pattern_data(pattern))

    def _active_processed_observed_data(self) -> np.ndarray | None:
        return self._pattern_processed_observed_data(self._active_pattern())

    def _pattern_scoring_background_removed(self, pattern: Pattern | None) -> bool:
        if getattr(self, "_scoring_source", "Auto") == "Auto":
            return True
        return bool(pattern is not None and pattern.processed_background_removed)

    def _pattern_scoring_observed_data(self, pattern: Pattern | None) -> np.ndarray | None:
        if pattern is None:
            return None
        if getattr(self, "_scoring_source", "Auto") != "Auto":
            processed = self._pattern_processed_observed_data(pattern)
            return processed if processed is not None else self._normalized_observed_data(observed_pattern_data(pattern))
        result = self._pattern_auto_preprocessing_result(pattern)
        if result is None:
            return None
        return np.column_stack([result.x, result.corrected_y])

    def _pattern_finder_observed_data(self, pattern: Pattern | None) -> np.ndarray | None:
        if pattern is None or getattr(self, "_scoring_source", "Auto") != "Auto":
            return self._pattern_scoring_observed_data(pattern)
        result = self._pattern_auto_preprocessing_result(pattern)
        if result is None:
            return None
        return np.column_stack([result.x, result.y])

    def _pattern_finder_background_removed(self, pattern: Pattern | None) -> bool:
        if getattr(self, "_scoring_source", "Auto") == "Auto":
            return False
        return bool(pattern is not None and pattern.processed_background_removed)

    def _pattern_auto_preprocessing_result(self, pattern: Pattern | None):
        if pattern is None:
            return None
        raw = self._normalized_observed_data(observed_pattern_data(pattern))
        if raw is None or not len(raw):
            return None
        key = self._auto_scoring_cache_key(pattern, raw)
        cache = getattr(self, "_auto_scoring_cache", {})
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = auto_preprocess_for_scoring(raw[:, 0], raw[:, 1])
        cache[key] = result
        self._auto_scoring_cache = cache
        self._trim_auto_scoring_cache()
        return result

    def _active_scoring_observed_data(self) -> np.ndarray | None:
        return self._pattern_scoring_observed_data(self._active_pattern())

    def _auto_scoring_cache_key(self, pattern: Pattern, raw: np.ndarray) -> tuple[object, ...]:
        x = np.asarray(raw[:, 0], dtype=float)
        y = np.asarray(raw[:, 1], dtype=float)
        return (
            pattern.id,
            str(getattr(pattern, "source_path", "")),
            int(len(raw)),
            round(float(x[0]), 6),
            round(float(x[-1]), 6),
            round(float(np.nanpercentile(y, 1)), 5),
            round(float(np.nanpercentile(y, 50)), 5),
            round(float(np.nanpercentile(y, 99)), 5),
            bool(self.normalize_observed_patterns),
            "auto-scoring-components-v2",
        )

    def _trim_auto_scoring_cache(self, limit: int = 32) -> None:
        cache = getattr(self, "_auto_scoring_cache", {})
        while len(cache) > limit:
            cache.pop(next(iter(cache)), None)

    def _active_background_removed(self) -> bool:
        pattern = self._active_pattern()
        return bool(pattern is not None and pattern.processed_background_removed)

    def _active_observed_data(self):
        return self._normalized_observed_data(observed_pattern_data(self._active_pattern()))

    def _refresh_observed_pattern_plot(self) -> None:
        self._draw_observed_patterns()

    def _patterns_to_display(self):
        if self.show_all_selected_patterns:
            checked = set(self.tree.checked_pattern_ids())
            patterns = [pattern for pattern in self.project.patterns if pattern.id in checked]
            if patterns:
                return patterns
        pattern = self._active_pattern()
        return [pattern] if pattern is not None else []

    def _draw_observed_patterns(self, active_override=None) -> None:
        if hasattr(self, "_clear_profile_plot_layers"):
            self._clear_profile_plot_layers(include_observed=True, rebuild_legend=False)
        else:
            for item in self.plot_layers.get("observed", []):
                self.match_plot.removeItem(item)
            self.plot_layers["observed"] = []
        legend_visible = bool(getattr(getattr(self, "plot_view_settings", None), "legend_visible", True))
        self.legend_item = ensure_right_legend(self.match_plot, clear=True)
        self.legend_item.setVisible(legend_visible)
        self.observed_pattern_plot_context = {}

        patterns = self._patterns_to_display()
        active_pattern = self._active_pattern()
        active_id = active_pattern.id if active_pattern is not None else ""
        x_values = []
        y_values = []
        loaded_patterns = apply_pattern_offsets(
            load_observed_patterns(patterns, active_override, normalize=self.normalize_observed_patterns),
            self.show_all_selected_patterns,
            self.pattern_stack_offset_percent,
        )

        for item in loaded_patterns:
            crop_ranges = self._valid_crop_ranges(item.pattern)
            x_plot, y = self._crop_curve_to_ranges(item.x, item.plotted_y, crop_ranges)
            if len(x_plot) == 0:
                continue
            plot_style = getattr(self, "plot_style", None)
            active = item.pattern.id == active_id
            color = self._observed_pattern_color(item.pattern.id)
            base_width = float(getattr(getattr(plot_style, "observed", None), "width", 1.35))
            width = base_width + 0.75 if active else max(base_width, 0.5)
            curve_item = self.match_plot.plot(x_plot, y, pen=pg.mkPen(color, width=width))
            try:
                curve_item._xrd_pattern_id = item.pattern.id
            except Exception:
                pass
            self._make_observed_curve_selectable(curve_item, item.pattern.id)
            legend_proxy = self.match_plot.plot(
                [],
                [],
                pen=pg.mkPen(color, width=width),
                symbol="o" if active else None,
                symbolSize=int(getattr(getattr(plot_style, "marker", None), "size", 7)) + (2 if active else 0),
                symbolBrush=pg.mkBrush(color) if active else None,
                symbolPen=pg.mkPen("#111111", width=1.2) if active else None,
                name=(f"* {item.name}" if active else item.name),
            )
            try:
                legend_proxy._xrd_pattern_id = item.pattern.id
            except Exception:
                pass
            self.plot_layers["observed"].extend([curve_item, legend_proxy])
            self.observed_pattern_plot_context[item.pattern.id] = item.context
            x_values.append(x_plot)
            y_values.append(y)

        self._draw_estimated_background_components(loaded_patterns)
        self._draw_checked_phase_profiles(loaded_patterns)
        if hasattr(self, "_apply_plot_layer_visibility_settings"):
            self._apply_plot_layer_visibility_settings(self.plot_view_settings)

        if x_values and y_values and not self.match_plot_view_initialized:
            self._reset_match_plot_view()

    def _draw_estimated_background_components(self, loaded_patterns) -> None:
        for item in loaded_patterns:
            pattern = item.pattern
            if getattr(pattern, "processed_background_removed", False):
                continue
            components = (
                (getattr(pattern, "estimated_background_points", []), "#202124", "physical background"),
                (
                    getattr(pattern, "estimated_background_with_halo_points", []),
                    "#1a73e8",
                    "background + amorphous phase",
                ),
            )
            for points, color, label in components:
                if not points:
                    continue
                values = np.asarray(points, dtype=float)
                if values.ndim != 2 or values.shape[1] < 2 or len(values) < 2:
                    continue
                y = np.interp(item.x, values[:, 0], values[:, 1]) + float(item.offset)
                x_plot, y_plot = self._crop_curve_to_ranges(item.x, y, self._valid_crop_ranges(pattern))
                if len(x_plot) == 0:
                    continue
                curve = self.match_plot.plot(x_plot, y_plot, pen=pg.mkPen(color, width=1.8), name=label)
                try:
                    curve._xrd_pattern_id = pattern.id
                except Exception:
                    pass
                self.plot_layers["background"].append(curve)


    def _observed_pattern_color(self, pattern_id: str) -> str:
        palette = [
            getattr(getattr(getattr(self, "plot_style", None), "observed", None), "color", None) or "#202124",
            "#d93025",
            "#1a73e8",
            "#188038",
            "#f9ab00",
            "#8e24aa",
            "#00acc1",
            "#c5221f",
            "#6d4c41",
            "#5f6368",
        ]
        colors = getattr(self, "observed_pattern_colors", None)
        if colors is None:
            self.observed_pattern_colors = {}
            colors = self.observed_pattern_colors
        if pattern_id not in colors:
            used = len(colors)
            colors[pattern_id] = palette[used % len(palette)]
        return colors[pattern_id]

    def _make_observed_curve_selectable(self, curve_item, pattern_id: str) -> None:
        try:
            curve_item.curve.setClickable(True, width=10)
        except Exception:
            pass
        signal = getattr(curve_item, "sigClicked", None) or getattr(getattr(curve_item, "curve", None), "sigClicked", None)
        if signal is None:
            return
        try:
            signal.connect(lambda *_args, pid=pattern_id: self._set_active_pattern_from_plot(pid))
        except Exception:
            pass

    def _set_active_pattern_from_plot(self, pattern_id: str) -> None:
        if not pattern_id:
            return
        current = self.tree.current_pattern_id() if hasattr(self, "tree") else None
        if current == pattern_id:
            return
        self.tree.select_object("pattern", pattern_id)
        if hasattr(self, "_update_profile_view_context"):
            self._update_profile_view_context()

    def _draw_checked_phase_profiles(self, loaded_patterns) -> None:
        for layer in ["calculated_profile", "hkl"]:
            for item in self.plot_layers.get(layer, []):
                self.match_plot.removeItem(item)
            self.plot_layers[layer] = []
        checked = set(self.tree.checked_phase_ids())
        if not checked:
            return
        phases = [phase for phase in self.project.phases if phase.id in checked]
        if not phases:
            return
        structures = {structure.id: structure for structure in self.project.structures}
        if loaded_patterns:
            x_grid = loaded_patterns[0].x
            reference_max = max((float(np.nanmax(item.y)) for item in loaded_patterns if len(item.y)), default=100.0)
            y_offset = max((float(np.nanmax(item.plotted_y)) for item in loaded_patterns if len(item.plotted_y)), default=0.0)
            y_offset += max(reference_max * 0.12, 1.0) if self.show_all_selected_patterns else 0.0
        else:
            x_grid = np.linspace(5.0, 120.0, 5000)
            reference_max = 100.0
            y_offset = 0.0
        colors = ["#d93025", "#1a73e8", "#188038", "#f9ab00", "#8e24aa"]
        for index, phase in enumerate(phases):
            structure = structures.get(phase.structure_id or "") or next(
                (item for item in self.project.structures if item.phase_id == phase.id),
                None,
            )
            if structure is None:
                continue
            try:
                structure.wavelength = self._active_wavelength()
                x, y, peaks = calculate_profile_for_structure(
                    self.calculated_pattern_service,
                    structure,
                    x_grid,
                    fwhm=0.18,
                )
            except Exception:
                continue
            y = scale_profile_to_reference(y, reference_max)
            if self.show_all_selected_patterns:
                y = y + y_offset
                y_offset += max(float(np.nanmax(y) - np.nanmin(y)), reference_max, 1.0) * (self.pattern_stack_offset_percent / 100.0)
            color = colors[index % len(colors)]
            item = plot_profile(self.match_plot, x, y, color, f"calc: {phase.name}", width=1.35)
            self.plot_layers["calculated_profile"].append(item)
            if self.show_hkl_labels:
                baseline = float(np.nanmin(y))
                top = baseline + max(reference_max * 0.18, 1.0)
                self.plot_layers["hkl"].extend(plot_hkl_sticks(self.match_plot, peaks, color, baseline, top, label=f"hkl: {phase.name}"))

    def _plot_view_range(self) -> tuple[tuple[float, float], tuple[float, float]]:
        view_range = self.match_plot.plotItem.vb.viewRange()
        return (tuple(view_range[0]), tuple(view_range[1]))

    def _restore_plot_view_range(self, view_range: tuple[tuple[float, float], tuple[float, float]] | None) -> None:
        if view_range is None:
            return
        (xmin, xmax), (ymin, ymax) = view_range
        self.match_plot.setXRange(float(xmin), float(xmax), padding=0.0)
        self.match_plot.setYRange(float(ymin), float(ymax), padding=0.0)

    def _active_pattern_plot_context(self) -> dict[str, float]:
        pattern = self._active_pattern()
        if pattern is None:
            return {"offset": 0.0, "raw_min": 0.0, "raw_max": 1.0, "plot_min": 0.0, "plot_max": 1.0, "height": 1.0}
        return self.observed_pattern_plot_context.get(
            pattern.id,
            {"offset": 0.0, "raw_min": 0.0, "raw_max": 1.0, "plot_min": 0.0, "plot_max": 1.0, "height": 1.0},
        )

    def _valid_crop_ranges(self, pattern: Pattern | None) -> list[tuple[float, float]]:
        ranges = []
        for item in getattr(pattern, "crop_ranges", []) if pattern is not None else []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            try:
                start = float(item[0])
                end = float(item[1])
            except (TypeError, ValueError):
                continue
            if np.isfinite(start) and np.isfinite(end) and end > start:
                ranges.append((start, end))
        ranges.sort(key=lambda value: value[0])
        return ranges

    def _crop_curve_to_ranges(
        self,
        x_values,
        y_values,
        ranges: list[tuple[float, float]],
    ) -> tuple[np.ndarray, np.ndarray]:
        x = np.asarray(x_values, dtype=float)
        y = np.asarray(y_values, dtype=float)
        if not ranges or len(x) == 0 or len(y) == 0 or len(x) != len(y):
            return x, y
        x_parts = []
        y_parts = []
        for start, end in ranges:
            mask = (x >= start) & (x <= end)
            if not np.any(mask):
                continue
            if x_parts:
                x_parts.append(np.asarray([np.nan], dtype=float))
                y_parts.append(np.asarray([np.nan], dtype=float))
            x_parts.append(x[mask])
            y_parts.append(y[mask])
        if not x_parts:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        return np.concatenate(x_parts), np.concatenate(y_parts)

    def _plot_item_data_arrays(self, item) -> tuple[np.ndarray, np.ndarray] | None:
        x = getattr(item, "xData", None)
        y = getattr(item, "yData", None)
        if x is None or y is None:
            return None
        try:
            x_values = np.asarray(x, dtype=float)
            y_values = np.asarray(y, dtype=float)
        except Exception:
            return None
        if len(x_values) == 0 or len(y_values) == 0 or len(x_values) != len(y_values):
            return None
        finite = np.isfinite(x_values) & np.isfinite(y_values)
        if not np.any(finite):
            return None
        return x_values[finite], y_values[finite]

    def _plot_data_bounds(self, x_range: tuple[float, float] | None = None) -> tuple[float, float, float, float] | None:
        xmin_values = []
        xmax_values = []
        ymin_values = []
        ymax_values = []
        for items in self.plot_layers.values():
            for item in items:
                try:
                    if not item.isVisible():
                        continue
                except Exception:
                    pass
                arrays = self._plot_item_data_arrays(item)
                if arrays is None:
                    continue
                x_values, y_values = arrays
                if x_range is not None:
                    left, right = x_range
                    mask = (x_values >= left) & (x_values <= right)
                    if not np.any(mask):
                        continue
                    x_values = x_values[mask]
                    y_values = y_values[mask]
                xmin_values.append(float(np.nanmin(x_values)))
                xmax_values.append(float(np.nanmax(x_values)))
                ymin_values.append(float(np.nanmin(y_values)))
                ymax_values.append(float(np.nanmax(y_values)))
        if not xmin_values:
            return None
        return min(xmin_values), max(xmax_values), min(ymin_values), max(ymax_values)

    def _plot_xrd_crop_range(self, full_bounds: tuple[float, float, float, float]) -> tuple[float, float]:
        xmin, xmax, _ymin, _ymax = full_bounds
        ranges = []
        for pattern in self._patterns_to_display():
            ranges.extend(self._valid_crop_ranges(pattern))
        if ranges:
            crop_min = min(start for start, _end in ranges)
            crop_max = max(end for _start, end in ranges)
            return max(xmin, crop_min), min(xmax, crop_max)
        return xmin, xmax

    def _reset_match_plot_view(self) -> None:
        full_bounds = self._plot_data_bounds()
        if full_bounds is None:
            self.match_plot.autoRange(padding=0.0)
            self.match_plot_view_initialized = True
            return
        xmin, xmax = self._plot_xrd_crop_range(full_bounds)
        if xmax <= xmin:
            xmin, xmax = full_bounds[0], full_bounds[1]
        visible_bounds = self._plot_data_bounds((xmin, xmax)) or full_bounds
        ymin, ymax = visible_bounds[2], visible_bounds[3]
        if ymax <= ymin:
            delta = max(abs(ymax) * 0.01, 1.0)
            ymin -= delta
            ymax += delta
        self.match_plot.setXRange(float(xmin), float(xmax), padding=0.0)
        self.match_plot.setYRange(float(ymin), float(ymax), padding=0.0)
        self.match_plot_view_initialized = True
