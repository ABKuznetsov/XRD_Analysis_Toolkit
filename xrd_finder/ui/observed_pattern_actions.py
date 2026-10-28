from __future__ import annotations

from html import escape

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, QTimer, Qt

from xrd_finder.core.pattern import Pattern
from xrd_finder.finder.profile_calculator import array_fingerprint
from xrd_finder.services.preprocessing_service import auto_preprocess_for_scoring
from xrd_finder.services.runtime_diagnostics import traced_operation
from xrd_finder.ui.observed_patterns import apply_pattern_offsets, load_observed_patterns, normalize_intensity, observed_pattern_data, processed_pattern_data
from xrd_finder.ui.pattern_plot_helpers import (
    calculate_profile_for_structure,
    ensure_right_legend,
    plot_hkl_sticks,
    plot_profile,
    scale_profile_to_reference,
)
from xrd_finder.plot_export.metadata import CanvasLayer
from xrd_finder.ui.plot_layer_items import tag_xrd_plot_item
from xrd_finder.ui.formula_display import formula_html


def _processed_amorphous_fill_values(
    physical_y: np.ndarray,
    restored_total_y: np.ndarray,
    local_minimum_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the display-space bounds of a restored amorphous component."""

    physical = np.asarray(physical_y, dtype=float)
    total = np.asarray(restored_total_y, dtype=float)
    lower = np.asarray(local_minimum_y, dtype=float)
    if physical.shape != total.shape or total.shape != lower.shape:
        raise ValueError("Background and local-minimum arrays must have the same shape")
    restored = np.maximum(total - physical, 0.0)
    return lower, lower + restored


def _minimum_peak_baseline(y: np.ndarray) -> np.ndarray:
    """Return one robust lower signal level without clipping negatives."""

    y_values = np.asarray(y, dtype=float)
    if len(y_values) == 0:
        return np.array(y_values, dtype=float, copy=True)
    finite = y_values[np.isfinite(y_values)]
    if not finite.size:
        return np.zeros_like(y_values)
    level = float(np.nanpercentile(finite, 10.0))
    return np.full_like(y_values, level)


def _pattern_has_amorphous_fill(pattern: Pattern | object) -> bool:
    if not bool(getattr(pattern, "processed_background_removed", False)):
        return False
    try:
        physical = np.asarray(getattr(pattern, "estimated_background_points", []), dtype=float)
        total = np.asarray(getattr(pattern, "estimated_background_with_halo_points", []), dtype=float)
    except Exception:
        return False
    if (
        physical.ndim != 2
        or total.ndim != 2
        or physical.shape[1] < 2
        or total.shape[1] < 2
        or len(physical) < 2
        or len(total) < 2
    ):
        return False
    total_y = np.interp(physical[:, 0], total[:, 0], total[:, 1])
    return bool(np.nanmax(np.maximum(total_y - physical[:, 1], 0.0)) > 1.0e-9)


def _processed_amorphous_background_data(pattern: Pattern | object) -> np.ndarray | None:
    """Return the displayed amorphous upper curve for profile fitting."""

    if not _pattern_has_amorphous_fill(pattern):
        return None
    try:
        processed = np.asarray(getattr(pattern, "processed_points", []), dtype=float)
        physical = np.asarray(getattr(pattern, "estimated_background_points", []), dtype=float)
        total = np.asarray(getattr(pattern, "estimated_background_with_halo_points", []), dtype=float)
    except Exception:
        return None
    if processed.ndim != 2 or processed.shape[1] < 2 or len(processed) < 2:
        return None
    x = np.asarray(processed[:, 0], dtype=float)
    y = np.asarray(processed[:, 1], dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if np.count_nonzero(mask) < 2:
        return None
    x = x[mask]
    y = y[mask]
    physical_y = np.interp(x, physical[:, 0], physical[:, 1])
    total_y = np.interp(x, total[:, 0], total[:, 1])
    restored = np.maximum(total_y - physical_y, 0.0)
    baseline = _minimum_peak_baseline(y)
    return np.column_stack([x, baseline + restored])


class DraggableLegendTextItem(pg.TextItem):
    def __init__(self, *args, moved_callback=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._moved_callback = moved_callback
        self._drag_offset = None
        self.textItem.document().setDocumentMargin(1.0)
        self.setAcceptHoverEvents(True)

    def mouseDragEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        parent = self.parentItem()
        point = parent.mapFromScene(event.scenePos()) if parent is not None else event.scenePos()
        if event.isStart() or self._drag_offset is None:
            self._drag_offset = self.pos() - point
        self.setPos(point + self._drag_offset)
        if event.isFinish():
            self._drag_offset = None
            if self._moved_callback is not None:
                self._moved_callback(self)
        event.accept()


class PhaseFinderObservedPatternActionsMixin:
    def _phase_legend_entries(self, pattern: Pattern) -> list[tuple[str, str, str]]:
        """Use accepted cards and their actual per-pattern marker colours."""
        candidates = self._profile_candidates_for_pattern(pattern) if hasattr(self, "_profile_candidates_for_pattern") else []
        entries = []
        seen = set()
        for index, candidate in enumerate(candidates):
            key = self._candidate_key(candidate) if hasattr(self, "_candidate_key") else str(index)
            color = self._phase_color(candidate, index) if hasattr(self, "_phase_color") else candidate.get("_Color", "#d93025")
            name = self._phase_legend_label(candidate) if hasattr(self, "_phase_legend_label") else candidate.get("Phase", "")
            entry = (key, str(color), str(name))
            if name and entry not in seen:
                seen.add(entry)
                entries.append(entry)
        return entries

    def _phase_legend_labels(self, entries) -> str:
        font_size = max(int(getattr(self.plot_view_settings, "legend_font_size", 10) or 10), 7)
        return " &nbsp; ".join(
            f'<span style="white-space:nowrap;"><span style="color:{escape(color)}; '
            f'font-size:{font_size + 2}pt;">&#9679;</span>'
            f'&nbsp;<span style="color:#111111;">{formula_html(name)}</span></span>'
            for _key, color, name in entries
        )

    def _multi_pattern_legend_html(self, pattern: Pattern, observed_color: str) -> str:
        settings = getattr(self, "plot_view_settings", None)
        font_size = max(int(getattr(settings, "legend_font_size", 10) or 10), 7)
        lines = [
            f'<span style="color:{escape(observed_color)}; font-weight:600;">'
            f'{escape(str(pattern.name))}</span>'
        ] if bool(getattr(settings, "legend_visible", True)) else []
        if bool(getattr(settings, "legend_visible", True)) and _pattern_has_amorphous_fill(pattern):
            lines.append(
                '<span style="color:#1a73e8; font-size:'
                f'{font_size + 2}pt;">&#9632;</span>'
                '&nbsp;<span style="color:#111111;">Amorphous phase</span>'
            )
        if (bool(getattr(settings, "multi_legend_phase_names_visible", True))
                and getattr(settings, "multi_phase_legend_mode", "individual") == "individual"):
            phases = self._phase_legend_labels(self._phase_legend_entries(pattern))
            if phases:
                lines.append(phases)
        return (
            f'<div style="font-family:Segoe UI; font-size:{font_size}pt;">'
            + "<br>".join(lines)
            + "</div>"
        )

    def _refresh_multi_pattern_legends(self) -> None:
        if not getattr(self, "show_all_selected_patterns", False):
            for item in self.plot_layers.get("phase_legend", []):
                item.hide()
            return
        patterns = {pattern.id: pattern for pattern in getattr(self.project, "patterns", [])}
        displayed = []
        for item in self.plot_layers.get("pattern_legends", []):
            pattern_id = getattr(item, "_xrd_pattern_id", "")
            pattern = patterns.get(pattern_id)
            if pattern is None:
                continue
            displayed.append(pattern)
            color = self._observed_pattern_color(pattern_id)
            html = self._multi_pattern_legend_html(pattern, color)
            if html != getattr(item, "_xrd_legend_html", None):
                item.setHtml(html)
                item._xrd_legend_html = html
            item.setVisible(bool(item.textItem.toPlainText().strip()))
        self._refresh_common_phase_legend(displayed)
        self._schedule_multi_pattern_legend_layout()

    def _refresh_common_phase_legend(self, patterns) -> None:
        settings = self.plot_view_settings
        items = self.plot_layers.setdefault("phase_legend", [])
        if not settings.multi_legend_phase_names_visible or settings.multi_phase_legend_mode != "common":
            for item in items:
                item.hide()
            return
        entries = []
        seen = set()
        for pattern in patterns:
            for entry in self._phase_legend_entries(pattern):
                if entry not in seen:
                    seen.add(entry)
                    entries.append(entry)
        visible = bool(entries)
        if not items and visible:
            item = pg.TextItem(anchor=(0, 0), fill=pg.mkBrush(255, 255, 255, 230),
                               border=pg.mkPen("#c5c5c5", width=0.6))
            item.textItem.document().setDocumentMargin(4.0)
            item.setZValue(100)
            tag_xrd_plot_item(item, layer=CanvasLayer.LEGENDS, object_id="common-phase-legend")
            self.match_plot.addItem(item, ignoreBounds=True)
            items.append(item)
        if items:
            font_size = max(int(settings.legend_font_size or 10), 7)
            html = (f'<div style="font-family:Segoe UI; font-size:{font_size}pt;">'
                    + self._phase_legend_labels(entries) + "</div>")
            if html != getattr(items[0], "_xrd_legend_html", None):
                items[0].setHtml(html)
                items[0]._xrd_legend_html = html
            items[0].setVisible(visible)

    def _layout_common_phase_legend(self) -> float:
        """Reserve room above the data for a wrapping strip inside the frame."""
        view = self.match_plot.getViewBox()
        visible = [item for item in self.plot_layers.get("phase_legend", []) if item.isVisible()]
        for item in visible:
            width = max(float(view.width()) - 8.0, 1.0)
            if abs(item.textItem.textWidth() - width) > 0.1:
                item.setTextWidth(width)
        header_pixels = max((item.boundingRect().height() + 16.0 for item in visible), default=0.0)
        self._reserve_common_phase_legend_space(header_pixels)
        (x_min, x_max), (y_min, y_max) = view.viewRange()
        x_per_pixel = (x_max - x_min) / max(float(view.width()), 1.0)
        y_per_pixel = (y_max - y_min) / max(float(view.height()), 1.0)
        reserved = 0.0
        for item in visible:
            item.setPos(x_min + 4.0*x_per_pixel, y_max - 4.0*y_per_pixel)
            reserved = header_pixels*y_per_pixel
        return reserved

    def _reserve_common_phase_legend_space(self, header_pixels: float) -> None:
        """Add reversible screen-space headroom, leaving all measured data intact."""
        view = self.match_plot.getViewBox()
        current = tuple(view.viewRange()[1])
        previous = getattr(self, "_common_phase_legend_range", None)
        # Resize/reflow must start from the unpadded range. A new range from
        # fitting, panning or zooming instead becomes the new display baseline.
        baseline = previous[0] if previous and np.allclose(current, previous[1], rtol=1e-10, atol=1e-10) else current
        fraction = min(max(float(header_pixels), 0.0) / max(float(view.height()), 1.0), 0.8)
        padded = (baseline[0], baseline[0] + (baseline[1] - baseline[0]) / (1.0 - fraction))
        self._common_phase_legend_range = (baseline, padded) if fraction else None
        if not np.allclose(current, padded, rtol=1e-10, atol=1e-10):
            view.setYRange(*padded, padding=0.0)

    def _remember_common_legend_manual_range(self, axes) -> None:
        previous = getattr(self, "_common_phase_legend_range", None)
        if not previous or not axes[1]:
            return
        baseline, padded = previous
        # Mouse navigation already transforms the padded viewport. Keep that
        # fraction instead of adding another header at every drag/wheel event.
        fraction = (baseline[1] - baseline[0]) / max(padded[1] - padded[0], np.finfo(float).eps)
        current = tuple(self.match_plot.getViewBox().viewRange()[1])
        baseline = (current[0], current[0] + (current[1] - current[0])*fraction)
        self._common_phase_legend_range = (baseline, current)

    def _schedule_multi_pattern_legend_layout(self, *_args) -> None:
        if not getattr(self, 'show_all_selected_patterns', False) or getattr(self, '_multi_legend_layout_pending', False):
            return
        self._multi_legend_layout_pending = True

        def finish() -> None:
            self._multi_legend_layout_pending = False
            self._fit_multi_pattern_legends_to_canvas()

        QTimer.singleShot(0, finish)

    def _fit_multi_pattern_legends_to_canvas(self) -> None:
        if not getattr(self, "show_all_selected_patterns", False):
            return
        common_height = self._layout_common_phase_legend()
        labels = [
            item
            for item in self.plot_layers.get("pattern_legends", [])
            if item is not None and item.isVisible()
        ]
        if not labels:
            return
        manual_positions = getattr(self, "_multi_legend_manual_positions", {})
        view = self.match_plot.getViewBox()
        (x_min, x_max), (y_min, y_max) = view.viewRange()
        span = max(float(y_max) - float(y_min), np.finfo(float).eps)
        x_span = max(float(x_max) - float(x_min), np.finfo(float).eps)
        data_per_pixel = span / max(float(view.height()), 1.0)
        x_per_pixel = x_span / max(float(view.width()), 1.0)
        y_max -= common_height
        clearance = 3.0 * data_per_pixel
        x_clearance = 3.0 * x_per_pixel
        entries = []
        for item in labels:
            item.setScale(1.0)
            item._xrd_screen_scale = 1.0
            item.setTextWidth(-1)
            available_width = max(float(view.width()) - 6.0, 1.0)
            if item.boundingRect().width() > available_width:
                item.setTextWidth(available_width)
            pattern_id = getattr(item, "_xrd_pattern_id", "")
            context = self.observed_pattern_plot_context.get(pattern_id, {})
            x = np.asarray(context.get("display_x", []), dtype=float)
            y = np.asarray(context.get("display_y", []), dtype=float)
            if self.profile_states.get(pattern_id, {}).get("correct_zero", False):
                x = x - self._pattern_display_zero_shift_deg(pattern_id)
            finite = np.isfinite(x) & np.isfinite(y) if x.size == y.size else np.zeros(0, dtype=bool)
            x = x[finite]
            y = y[finite]
            baseline = float(np.nanpercentile(y, 8)) if y.size else float(item.pos().y())
            entries.append({"item": item, "x": x, "y": y, "baseline": baseline})
        entries.sort(key=lambda entry: float(entry["baseline"]), reverse=True)

        occupied = []
        placements = []
        alignment = str(
            getattr(getattr(self, "plot_view_settings", None), "multi_legend_alignment", "Right")
            or "Right"
        )
        for index, entry in enumerate(entries):
            item = entry["item"]
            previous_entry = entries[index - 1] if index > 0 else None
            upper = min(float(y_max) - clearance, (
                float(previous_entry["baseline"]) - clearance
                if previous_entry is not None
                else float(y_max) - clearance
            ))
            current_x = entry["x"]
            label_width = float(item.boundingRect().width()) * x_per_pixel
            label_height = float(item.boundingRect().height()) * data_per_pixel
            half_height = label_height * 0.5
            minimum_anchor = min(float(x_min) + label_width + x_clearance, float(x_max) - x_clearance)
            maximum_anchor = float(x_max) - x_clearance
            minimum_center = float(y_min) + clearance + half_height
            maximum_center = float(y_max) - clearance - half_height
            manual = manual_positions.get(getattr(item, '_xrd_pattern_id', ''))
            if manual is not None:
                anchors = np.asarray([np.clip(float(manual[0]), minimum_anchor, maximum_anchor)])
            elif alignment == "Left":
                anchors = np.asarray([minimum_anchor])
            elif alignment == "Center":
                anchors = np.asarray([(minimum_anchor + maximum_anchor) * 0.5])
            elif alignment == "Right":
                anchors = np.asarray([maximum_anchor])
            else:
                anchors = np.linspace(minimum_anchor, maximum_anchor, 28)
            best = None
            for anchor in anchors:
                lower = max(float(entry["baseline"]), float(y_min)) + clearance
                if current_x.size:
                    current_y = entry["y"]
                    mask = (current_x >= float(anchor) - label_width) & (current_x <= float(anchor))
                    if np.any(mask):
                        lower = max(lower, float(np.nanmax(current_y[mask])) + clearance)
                free_height = upper - lower
                if manual is not None:
                    center = float(manual[1])
                    if free_height >= label_height:
                        center = float(np.clip(center, lower + half_height, upper - half_height))
                else:
                    band_bottom = max(float(entry['baseline']), float(y_min)) + clearance
                    center = ((lower if free_height >= label_height else band_bottom) + upper) * 0.5
                    if index == 0 and alignment == 'Right':
                        center = maximum_center
                if minimum_center <= maximum_center:
                    center = float(np.clip(center, minimum_center, maximum_center))
                else:
                    center = (float(y_min) + float(y_max)) * 0.5
                box = QRectF(float(anchor) - label_width, center - half_height, label_width, label_height)
                collisions = sum(box.intersects(previous) for previous in occupied)
                score = (-collisions, free_height >= label_height, free_height, float(anchor))
                if best is None or score > best[0]:
                    best = (score, float(anchor), center, box)
            if best is not None:
                item.setPos(best[1], best[2])
                occupied.append(best[3])
                placements.append([item, best[1], best[2], half_height])

        # Keep the fixed-size right column readable even when stacked curves
        # are closer together than the text height.
        needed_height = sum(2.0 * placement[3] for placement in placements)
        needed_height += max(len(placements) - 1, 0) * clearance
        if alignment == 'Right' and placements and needed_height <= span - 2.0 * clearance:
            for index in range(1, len(placements)):
                previous, current = placements[index - 1], placements[index]
                current[2] = min(current[2], previous[2] - previous[3] - clearance - current[3])
            placements[-1][2] = max(placements[-1][2], float(y_min) + clearance + placements[-1][3])
            for index in range(len(placements) - 2, -1, -1):
                current, following = placements[index], placements[index + 1]
                current[2] = max(current[2], following[2] + following[3] + clearance + current[3])
            overflow = max(0.0, placements[0][2] + placements[0][3] + clearance - float(y_max))
            for item, anchor, center, _half_height in placements:
                item.setPos(anchor, center - overflow)

    def _remember_multi_legend_position(self, item) -> None:
        pattern_id = getattr(item, "_xrd_pattern_id", "")
        if not pattern_id:
            return
        positions = dict(getattr(self, "_multi_legend_manual_positions", {}))
        positions[pattern_id] = (float(item.pos().x()), float(item.pos().y()))
        self._multi_legend_manual_positions = positions

    def _set_pattern_display_mode(self, mode: str) -> None:
        if hasattr(self, "_save_active_profile_state"):
            self._save_active_profile_state()
        self.show_all_selected_patterns = mode == "All selected"
        if self.show_all_selected_patterns and hasattr(self, "_ensure_multi_profile_layer_defaults"):
            for pattern in self._patterns_to_display():
                self._ensure_multi_profile_layer_defaults(pattern.id)
        if hasattr(self, "_clear_profile_plot_layers"):
            self._clear_profile_plot_layers(include_observed=True, rebuild_legend=False)
            self.active_overlay_entry_id = None
        else:
            if hasattr(self, "_clear_calculated_overlay"):
                self._clear_calculated_overlay()
            if hasattr(self, "_clear_preview_overlay"):
                self._clear_preview_overlay()
        self._refresh_observed_pattern_plot()
        self._rerun_active_calculation(active_only=False)
        if hasattr(self, "_update_profile_view_context"):
            self._update_profile_view_context()

    def _set_pattern_stack_offset(self, percent: int) -> None:
        self.pattern_stack_offset_percent = max(0, int(percent))
        if self.show_all_selected_patterns:
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation(active_only=False)

    def _set_pattern_normalization(self, enabled: bool) -> None:
        self.normalize_observed_patterns = bool(enabled)
        self.match_plot_view_initialized = False
        if hasattr(self, "_auto_scoring_cache"):
            self._auto_scoring_cache.clear()
        if hasattr(self, "_invalidate_match_profile_cache"):
            self._invalidate_match_profile_cache()
        self._clear_probability_caches()
        self._refresh_observed_pattern_plot()
        self._rerun_active_calculation(active_only=False)

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
            data = processed if processed is not None else self._normalized_observed_data(observed_pattern_data(pattern))
            return self._crop_pattern_data(pattern, data)
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

    @traced_operation("preprocess.auto")
    def _pattern_auto_preprocessing_result(self, pattern: Pattern | None):
        if pattern is None:
            return None
        raw = self._crop_pattern_data(
            pattern,
            self._normalized_observed_data(observed_pattern_data(pattern)),
        )
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
            array_fingerprint(x),
            array_fingerprint(y),
            bool(self.normalize_observed_patterns),
            "auto-scoring-components-v3",
        )

    def _trim_auto_scoring_cache(self, limit: int = 32) -> None:
        cache = getattr(self, "_auto_scoring_cache", {})
        while len(cache) > limit:
            cache.pop(next(iter(cache)), None)

    def _active_background_removed(self) -> bool:
        pattern = self._active_pattern()
        return bool(pattern is not None and pattern.processed_background_removed)

    def _active_observed_data(self):
        pattern = self._active_pattern()
        return self._crop_pattern_data(
            pattern,
            self._normalized_observed_data(observed_pattern_data(pattern)),
        )

    def _crop_pattern_data(self, pattern: Pattern | None, data: np.ndarray | None) -> np.ndarray | None:
        if data is None or pattern is None:
            return data
        values = np.asarray(data, dtype=float)
        if values.ndim != 2 or values.shape[1] < 2 or not len(values):
            return values
        ranges = self._valid_crop_ranges(pattern)
        if not ranges:
            return values
        mask = np.zeros(len(values), dtype=bool)
        x = values[:, 0]
        for start, end in ranges:
            mask |= (x >= float(start)) & (x <= float(end))
        cropped = values[mask]
        return cropped if len(cropped) else values[:0]

    def _refresh_observed_pattern_plot(self) -> None:
        self._draw_observed_patterns()

    def _patterns_to_display(self):
        if self.show_all_selected_patterns:
            checked = set(self.tree.checked_pattern_ids())
            patterns_by_id = {pattern.id: pattern for pattern in self.project.patterns}
            display_order = self._normalized_pattern_display_order()
            patterns = [
                patterns_by_id[pattern_id]
                for pattern_id in display_order
                if pattern_id in checked and pattern_id in patterns_by_id
            ]
            if patterns:
                return patterns
        pattern = self._active_pattern()
        return [pattern] if pattern is not None else []

    @traced_operation("plot.observed")
    def _draw_observed_patterns(self, active_override=None) -> None:
        self._close_manual_calibration()
        if getattr(self, '_manual_peak_input_armed', False) and (
            getattr(self._active_pattern(), 'id', None) != self._manual_peak_pattern_id
            or self.show_all_selected_patterns
        ):
            self._close_manual_peak_editor()
        if getattr(self, '_find_peaks_busy', False):
            self._cancel_find_peaks()
        if getattr(self, '_peak_info_armed', False):
            self._cancel_peak_information(close_card=True)
        if hasattr(self, "_clear_profile_plot_layers"):
            self._clear_profile_plot_layers(include_observed=True, rebuild_legend=False)
        else:
            for item in self.plot_layers.get("observed", []):
                self.match_plot.removeItem(item)
            self.plot_layers["observed"] = []
        legend_visible = bool(getattr(getattr(self, "plot_view_settings", None), "legend_visible", True))
        self.legend_item = ensure_right_legend(self.match_plot, clear=True)
        self.legend_item.setVisible(legend_visible and not self.show_all_selected_patterns)
        self.observed_pattern_plot_context = {}

        patterns = self._patterns_to_display()
        signature = (self.show_all_selected_patterns, tuple(pattern.id for pattern in patterns),
                     self.pattern_stack_offset_percent if self.show_all_selected_patterns else None)
        previous_signature = getattr(self, '_plot_display_signature', None)
        if signature != previous_signature and (
            self.show_all_selected_patterns or previous_signature is not None and previous_signature[0]
        ):
            self.match_plot_view_initialized = False
        self._plot_display_signature = signature
        active_pattern = self._active_pattern()
        kind = getattr(active_pattern, 'input_kind', 'profile')
        previous_kind = getattr(self, '_plot_input_kind', None)
        if previous_kind is not None and previous_kind != kind:
            self.match_plot_view_initialized = False
        self._plot_input_kind = kind
        active_id = active_pattern.id if active_pattern is not None else ""
        x_values = []
        y_values = []
        loaded_patterns = apply_pattern_offsets(
            load_observed_patterns(patterns, active_override, normalize=self.normalize_observed_patterns),
            self.show_all_selected_patterns,
            self.pattern_stack_offset_percent,
        )

        for item in loaded_patterns:
            if self.show_all_selected_patterns and hasattr(self, "_ensure_multi_profile_layer_defaults"):
                self._ensure_multi_profile_layer_defaults(item.pattern.id)
            crop_ranges = self._valid_crop_ranges(item.pattern)
            x_plot, y = self._crop_curve_to_ranges(item.x, item.plotted_y, crop_ranges)
            manual = getattr(item.pattern, 'input_kind', '') == 'peak_list'
            if len(x_plot) == 0 and not manual:
                continue
            from xrd_finder.ui.xrd_range_warning import warn_outside_xrd_range
            warn_outside_xrd_range(self, item.pattern, item.x)
            plot_style = getattr(self, "plot_style", None)
            active = item.pattern.id == active_id
            color = self._observed_pattern_color(item.pattern.id)
            base_width = float(getattr(getattr(plot_style, "observed", None), "width", 1.35))
            width = base_width + 0.75 if active else max(base_width, 0.5)
            settings = getattr(self, "plot_view_settings", None)
            draw_mode = str(getattr(settings, "observed_draw_mode", "Line") or "Line")
            show_line = draw_mode in {"Line", "Line + scatter"}
            show_scatter = draw_mode in {"Scatter", "Line + scatter"}
            marker_size = int(getattr(getattr(plot_style, "marker", None), "size", 7)) + (2 if active else 0)
            curve_x, curve_y = x_plot, y
            if manual:
                curve_x = np.repeat(x_plot, 3)
                curve_y = np.column_stack([np.full(len(y), item.offset), y, np.full(len(y), np.nan)]).ravel()
                show_line = True
            curve_item = self.match_plot.plot(
                curve_x,
                curve_y,
                connect='finite' if manual else 'auto',
                pen=pg.mkPen(color, width=width) if show_line else None,
                symbol="o" if show_scatter else None,
                symbolSize=marker_size if show_scatter else None,
                symbolBrush=pg.mkBrush(color) if show_scatter else None,
                symbolPen=pg.mkPen(color, width=1.0) if show_scatter else None,
            )
            tag_xrd_plot_item(
                curve_item,
                layer=CanvasLayer.OBSERVED,
                pattern_id=item.pattern.id,
                object_id="observed-profile",
            )
            self._make_observed_curve_selectable(curve_item, item.pattern.id)
            legend_proxy = self.match_plot.plot(
                [],
                [],
                pen=pg.mkPen(color, width=width) if show_line else None,
                symbol="o" if show_scatter or active else None,
                symbolSize=marker_size if show_scatter or active else None,
                symbolBrush=pg.mkBrush(color) if show_scatter or active else None,
                symbolPen=pg.mkPen(color, width=1.0) if show_scatter else pg.mkPen("#111111", width=1.2) if active else None,
                name=None if self.show_all_selected_patterns else (f"* {item.name}" if active else item.name),
            )
            tag_xrd_plot_item(
                legend_proxy,
                layer=CanvasLayer.OBSERVED,
                pattern_id=item.pattern.id,
                object_id="observed-legend-proxy",
            )
            self.plot_layers["observed"].extend([curve_item, legend_proxy])
            if manual:
                dots = self.match_plot.plot(x_plot, y, pen=None, symbol='o', symbolSize=6,
                    symbolBrush=color, symbolPen=color)
                tag_xrd_plot_item(dots, layer=CanvasLayer.OBSERVED, pattern_id=item.pattern.id, object_id='manual-peak-tops')
                self.plot_layers['observed'].append(dots)
            if self.show_all_selected_patterns:
                finite_x = np.asarray(x_plot, dtype=float)
                curve_y = np.asarray(y, dtype=float)
                finite_mask = np.isfinite(finite_x) & np.isfinite(curve_y)
                finite_curve_x = finite_x[finite_mask]
                finite_curve_y = curve_y[finite_mask]
                label_x = float(np.nanmax(finite_curve_x)) if finite_curve_x.size else 0.0
                if finite_curve_y.size:
                    x_min = float(np.nanmin(finite_curve_x))
                    right_start = x_min + (label_x - x_min) * 0.72
                    right_y = finite_curve_y[finite_curve_x >= right_start]
                    if not right_y.size:
                        right_y = finite_curve_y
                    # The label occupies most of the rightmost quarter of the
                    # plot. Use the actual maximum below that whole text box,
                    # then reserve enough vertical clearance for a 12 pt label.
                    local_top = float(np.nanmax(right_y))
                    local_span = max(
                        float(np.nanpercentile(right_y, 95) - np.nanpercentile(right_y, 10)),
                        1.0,
                    )
                    label_clearance = max(
                        local_span * 0.35,
                        float(item.height) * 0.060,
                        12.0,
                    )
                    label_y = local_top + label_clearance
                    label = DraggableLegendTextItem(
                        "",
                        anchor=(1.0, 0.5),
                        fill=pg.mkBrush(255, 255, 255, 205),
                        border=pg.mkPen(color, width=0.8),
                        moved_callback=self._remember_multi_legend_position,
                    )
                    label.setHtml(self._multi_pattern_legend_html(item.pattern, color))
                    manual_position = getattr(self, "_multi_legend_manual_positions", {}).get(
                        item.pattern.id
                    )
                    if manual_position is not None:
                        label.setPos(float(manual_position[0]), float(manual_position[1]))
                    else:
                        label.setPos(label_x, label_y)
                    label.setVisible(legend_visible)
                    tag_xrd_plot_item(
                        label,
                        layer=CanvasLayer.LEGENDS,
                        pattern_id=item.pattern.id,
                        object_id="pattern-legend",
                    )
                    self.match_plot.addItem(label, ignoreBounds=True)
                    self.plot_layers.setdefault("pattern_legends", []).append(label)
            plot_context = item.context
            # Marker placement must use the curve exactly as it is displayed,
            # after normalization, cropping, and multi-pattern stacking.
            plot_context["display_x"] = np.asarray(x_plot, dtype=float)
            plot_context["display_y"] = np.asarray(y, dtype=float)
            plot_context['peak_list'] = manual
            self.observed_pattern_plot_context[item.pattern.id] = plot_context
            x_values.append(x_plot)
            y_values.append(y)

        manual_active = getattr(active_pattern, 'input_kind', '') == 'peak_list'
        self.finder_plot_control_bar.normalize_patterns_checkbox.setEnabled(not manual_active)
        label = 'Intensity (0–100)' if manual_active else getattr(self.plot_view_settings, 'left_axis_label', 'I rel.')
        self.match_plot.setLabel('left', label)
        self._draw_estimated_background_components(loaded_patterns)
        self._draw_checked_phase_profiles(loaded_patterns)
        if hasattr(self, "_redraw_selected_search_peaks"):
            self._redraw_selected_search_peaks()
        if hasattr(self, "_apply_plot_layer_visibility_settings"):
            self._apply_plot_layer_visibility_settings(self.plot_view_settings)

        if x_values and y_values and not self.match_plot_view_initialized:
            self._reset_match_plot_view()
        if self.show_all_selected_patterns:
            self._refresh_multi_pattern_legends()

    def _redraw_estimated_background_components_for_current_view(
        self,
        pattern_id: str | None = None,
    ) -> None:
        patterns = self._patterns_to_display()
        loaded_patterns = apply_pattern_offsets(
            load_observed_patterns(patterns, None, normalize=self.normalize_observed_patterns),
            self.show_all_selected_patterns,
            self.pattern_stack_offset_percent,
        )
        if pattern_id:
            loaded_patterns = [
                item for item in loaded_patterns if item.pattern.id == pattern_id
            ]
        self._draw_estimated_background_components(loaded_patterns)

    def _draw_estimated_background_components(self, loaded_patterns) -> None:
        for item in loaded_patterns:
            pattern = item.pattern
            physical = self._background_component_plot_values(
                item,
                getattr(pattern, "estimated_background_points", []),
            )
            total = self._background_component_plot_values(
                item,
                getattr(pattern, "estimated_background_with_halo_points", []),
            )
            if getattr(pattern, "processed_background_removed", False):
                if physical is not None and total is not None:
                    local_minimum = self._processed_amorphous_floor_plot_values(item)
                    self._draw_amorphous_background_fill(
                        pattern.id,
                        physical,
                        total,
                        processed=True,
                        local_minimum=local_minimum,
                    )
                continue
            if physical is not None and total is not None:
                self._draw_amorphous_background_fill(pattern.id, physical, total)
            for component, color, label, width in (
                (physical, "#202124", "physical background", 1.8),
                (total, "#1a73e8", "background + amorphous phase", 2.0),
            ):
                if component is None:
                    continue
                x_plot, y_plot = component
                curve = self.match_plot.plot(x_plot, y_plot, pen=pg.mkPen(color, width=width), name=label)
                tag_xrd_plot_item(
                    curve,
                    layer=CanvasLayer.PHYSICAL_BACKGROUND,
                    pattern_id=pattern.id,
                    object_id=f"background-{label.replace(' ', '-')}",
                )
                curve._xrd_profile_render_stage = 0
                self.plot_layers["background"].append(curve)

    def _background_component_plot_values(self, item, points) -> tuple[np.ndarray, np.ndarray] | None:
        if not points:
            return None
        values = np.asarray(points, dtype=float)
        if values.ndim != 2 or values.shape[1] < 2 or len(values) < 2:
            return None
        y = (
            np.interp(item.x, values[:, 0], values[:, 1]) * float(item.intensity_scale)
            + float(item.offset)
        )
        x_plot, y_plot = self._crop_curve_to_ranges(item.x, y, self._valid_crop_ranges(item.pattern))
        if len(x_plot) == 0:
            return None
        return x_plot, y_plot

    def _processed_amorphous_floor_plot_values(self, item) -> tuple[np.ndarray, np.ndarray] | None:
        floor = _minimum_peak_baseline(item.y) + float(item.offset)
        x_plot, y_plot = self._crop_curve_to_ranges(
            item.x,
            floor,
            self._valid_crop_ranges(item.pattern),
        )
        if len(x_plot) == 0:
            return None
        return x_plot, y_plot

    def _draw_amorphous_background_fill(
        self,
        pattern_id: str,
        physical: tuple[np.ndarray, np.ndarray],
        total: tuple[np.ndarray, np.ndarray],
        *,
        processed: bool = False,
        local_minimum: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> None:
        physical_x, physical_y = physical
        total_x, total_y = total
        if len(physical_x) < 2 or len(total_x) < 2:
            return
        if len(physical_x) != len(total_x) or not np.allclose(physical_x, total_x, rtol=0.0, atol=1.0e-9):
            total_y = np.interp(physical_x, total_x, total_y)
            total_x = physical_x
        if processed:
            if local_minimum is None:
                return
            floor_x, floor_y = local_minimum
            if len(floor_x) != len(physical_x) or not np.allclose(floor_x, physical_x, rtol=0.0, atol=1.0e-9):
                floor_y = np.interp(physical_x, floor_x, floor_y)
            lower, upper = _processed_amorphous_fill_values(
                physical_y,
                total_y,
                floor_y,
            )
        else:
            lower = np.minimum(physical_y, total_y)
            upper = np.maximum(physical_y, total_y)
        lower_curve = pg.PlotDataItem(physical_x, lower, pen=pg.mkPen((0, 0, 0, 0)))
        upper_curve = pg.PlotDataItem(
            total_x,
            upper,
            pen=pg.mkPen(26, 115, 232, 150, width=1.2) if processed else pg.mkPen((0, 0, 0, 0)),
            name="Amorphous phase" if processed else None,
        )
        fill = pg.FillBetweenItem(lower_curve, upper_curve, brush=pg.mkBrush(26, 115, 232, 64))
        layer_key = "amorphous" if processed else "background"
        export_layer = CanvasLayer.AMORPHOUS_PHASE if processed else CanvasLayer.PHYSICAL_BACKGROUND
        for index, item in enumerate((lower_curve, upper_curve, fill)):
            tag_xrd_plot_item(
                item,
                layer=export_layer,
                pattern_id=pattern_id,
                object_id=f"amorphous-background-{index}",
            )
            item._xrd_profile_render_stage = 0
            self.match_plot.addItem(item)
            self.plot_layers.setdefault(layer_key, []).append(item)


    def _observed_pattern_color(self, pattern_id: str) -> str:
        observed_color = getattr(getattr(getattr(self, "plot_style", None), "observed", None), "color", None) or "#202124"
        active_pattern = self._active_pattern()
        if not getattr(self, "show_all_selected_patterns", False):
            return observed_color
        if active_pattern is not None and pattern_id == getattr(active_pattern, "id", ""):
            return observed_color
        palette = [
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
            signal.connect(lambda *_args, pid=pattern_id: self._queue_active_pattern_from_plot(pid))
        except Exception:
            pass

    def _queue_active_pattern_from_plot(self, pattern_id: str) -> None:
        if getattr(self, '_peak_info_armed', False):
            return
        if getattr(self, "_search_mode", "search") == "peaks":
            return
        if not pattern_id:
            return
        # Selecting a tree item redraws the plot. Wait until pyqtgraph has
        # finished dispatching the mouse release to the curve being replaced.
        QTimer.singleShot(0, lambda pid=pattern_id: self._set_active_pattern_from_plot(pid))

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
        profiles = [item for item in loaded_patterns if getattr(item.pattern, 'input_kind', '') != 'peak_list']
        if loaded_patterns and not profiles:
            return
        loaded_patterns = profiles
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
            plot_style = getattr(self, "plot_style", None)
            phase_scale = max(float(getattr(plot_style, "phase_profile_scale", 1.0)) if plot_style is not None else 1.0, 0.0)
            y = scale_profile_to_reference(y, reference_max * phase_scale)
            if self.show_all_selected_patterns:
                y = y + y_offset
                y_offset += max(float(np.nanmax(y) - np.nanmin(y)), reference_max, 1.0) * (self.pattern_stack_offset_percent / 100.0)
            color = colors[index % len(colors)]
            width = float(getattr(getattr(plot_style, "phase", None), "width", 1.35)) if plot_style is not None else 1.35
            item = plot_profile(self.match_plot, x, y, color, f"calc: {phase.name}", width=width)
            tag_xrd_plot_item(
                item,
                layer=CanvasLayer.CANDIDATE_PREVIEW,
                candidate_id=phase.id,
                object_id="checked-phase-profile",
            )
            self.plot_layers["calculated_profile"].append(item)
            if self.show_hkl_labels:
                baseline = float(np.nanmin(y))
                tick_height = max(reference_max * 0.18, 1.0)
                tick_width = float(getattr(getattr(plot_style, "stick", None), "width", 1.6)) if plot_style is not None else 1.6
                hkl_items = plot_hkl_sticks(
                        self.match_plot,
                        peaks,
                        color,
                        baseline,
                        tick_height,
                        label=f"hkl: {phase.name}",
                        width=tick_width,
                    )
                for hkl_index, hkl_item in enumerate(hkl_items):
                    tag_xrd_plot_item(
                        hkl_item,
                        layer=CanvasLayer.LABELS,
                        candidate_id=phase.id,
                        object_id=f"checked-phase-hkl-{hkl_index}",
                    )
                self.plot_layers["hkl"].extend(hkl_items)

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
        shift = float(getattr(item, "_finder_zero_display_shift", 0.))
        return x_values[finite] - shift, y_values[finite]

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
            state = self.profile_states.get(pattern.id, {})
            shift = self._pattern_display_zero_shift_deg(pattern.id) if state.get("correct_zero", False) else 0.
            context = self.observed_pattern_plot_context.get(pattern.id, {})
            x = np.asarray(context.get('display_x', []), dtype=float)
            finite_x = x[np.isfinite(x)]
            if finite_x.size:
                ranges.append((float(np.min(finite_x)) - shift, float(np.max(finite_x)) - shift))
            else:
                crop_ranges = self._valid_crop_ranges(pattern)
                ranges.extend((start - shift, end - shift) for start, end in crop_ranges)
                if not crop_ranges:
                    ranges.append((xmin, xmax))
        if ranges:
            crop_min = min(start for start, _end in ranges)
            crop_max = max(end for _start, end in ranges)
            return max(xmin, crop_min), min(xmax, crop_max)
        return xmin, xmax

    def _reset_match_plot_view(self) -> None:
        if getattr(self._active_pattern(), 'input_kind', '') == 'peak_list' and not self.show_all_selected_patterns:
            self.match_plot.setRange(xRange=(0., 125.), yRange=(0., 100.), padding=0)
            self.match_plot_view_initialized = True
            return
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
