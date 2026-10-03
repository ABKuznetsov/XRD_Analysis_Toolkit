from __future__ import annotations

from dataclasses import replace
import hashlib

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from scipy.signal import find_peaks

from xrd_finder.services.preprocessing_service import (
    adjust_background_components,
    auto_background_plan,
    auto_smoothing_plan,
    estimate_amorphous_snip_component,
    peak_preserving_smooth,
    restore_amorphous_contribution,
)
from xrd_finder.services.background_model_selection import BackgroundModelSelection, select_background_model
from xrd_finder.ui.observed_patterns import observed_pattern_data
from xrd_finder.ui.preprocessing_dialogs import BackgroundRemovalPanel, SmoothPanel, XrdCropPanel
from xrd_finder.ui.theme import preprocessing_panel_style


_PREPROCESSING_ANALYSIS_MAX_POINTS = 2048


def _preprocessing_analysis_sample(
    x: np.ndarray,
    y: np.ndarray,
    *,
    max_points: int = _PREPROCESSING_ANALYSIS_MAX_POINTS,
) -> tuple[np.ndarray, np.ndarray]:
    """Return an evenly spaced analysis view without copying the full trace."""
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    if len(x_values) != len(y_values):
        raise ValueError("X and Y arrays must have the same length")
    limit = max(32, int(max_points))
    if len(x_values) <= limit:
        return x_values, y_values
    indices = np.linspace(0, len(x_values) - 1, limit, dtype=np.int64)
    indices = np.unique(indices)
    return x_values[indices], y_values[indices]


def _median_positive_step(values: np.ndarray) -> float:
    differences = np.diff(np.asarray(values, dtype=float))
    differences = differences[np.isfinite(differences) & (differences > 0.0)]
    return float(np.nanmedian(differences)) if len(differences) else 0.03


def _smoothing_plan_for_full_signal(
    sampled_plan,
    sampled_x: np.ndarray,
    full_x: np.ndarray,
):
    if len(full_x) < 3 or len(sampled_x) < 3:
        return sampled_plan
    width_degrees = float(sampled_plan.window) * _median_positive_step(sampled_x)
    full_window = max(5, int(round(width_degrees / max(_median_positive_step(full_x), 1.0e-9))))
    full_window = min(full_window, 21, len(full_x) if len(full_x) % 2 else len(full_x) - 1)
    if full_window % 2 == 0:
        full_window = max(5, full_window - 1)
    return replace(sampled_plan, window=full_window)


def _expand_background_model(
    model: BackgroundModelSelection,
    sampled_x: np.ndarray,
    full_x: np.ndarray,
) -> BackgroundModelSelection:
    sampled_x = np.asarray(sampled_x, dtype=float)
    full_x = np.asarray(full_x, dtype=float)
    if len(sampled_x) == len(full_x) and np.array_equal(sampled_x, full_x):
        return model
    if len(sampled_x) < 2:
        physical = np.full_like(full_x, float(model.physical_background[0]) if len(model.physical_background) else 0.0)
        amorphous = np.full_like(full_x, float(model.amorphous_component[0]) if len(model.amorphous_component) else 0.0)
    else:
        physical = np.interp(full_x, sampled_x, np.asarray(model.physical_background, dtype=float))
        amorphous = np.interp(full_x, sampled_x, np.asarray(model.amorphous_component, dtype=float))
    return replace(model, physical_background=physical, amorphous_component=amorphous)


def _expand_sampled_signal(
    sampled_x: np.ndarray,
    sampled_y: np.ndarray,
    full_x: np.ndarray,
) -> np.ndarray:
    """Interpolate a sampled working signal onto the original XRD grid."""
    sampled_x = np.asarray(sampled_x, dtype=float)
    sampled_y = np.asarray(sampled_y, dtype=float)
    full_x = np.asarray(full_x, dtype=float)
    if len(sampled_x) != len(sampled_y):
        raise ValueError("Sampled X and Y arrays must have the same length")
    if len(sampled_x) == len(full_x) and np.array_equal(sampled_x, full_x):
        return sampled_y
    if len(sampled_x) < 2:
        return np.full_like(full_x, float(sampled_y[0]) if len(sampled_y) else 0.0)
    return np.interp(full_x, sampled_x, sampled_y)


class PhaseFinderPreprocessingActionsMixin:
    def _close_preprocessing_panel(self) -> None:
        panel = getattr(self, "_preprocessing_panel", None)
        action_bar = getattr(self, "finder_action_bar", None)
        close_embedded = getattr(action_bar, "close_preprocessing_panel", None)
        if callable(close_embedded):
            close_embedded()
            self._preprocessing_panel = None
            self._preprocessing_panel_key = None
            return
        if panel is not None:
            panel.hide()
            panel.deleteLater()
        self._preprocessing_panel = None
        self._preprocessing_panel_key = None

    def _show_preprocessing_panel(
        self,
        key: str,
        button: QWidget,
        panel: QWidget,
        preview_callback,
        cancel_callback,
        subtract_callback=None,
        apply_callback=None,
    ) -> None:
        if getattr(self, "_preprocessing_panel", None) is not None:
            if getattr(self, "_preprocessing_panel_key", None) == key:
                return
            self._close_preprocessing_panel()

        action_bar = getattr(self, "finder_action_bar", None)
        embedded_host = getattr(action_bar, "show_preprocessing_panel", None)
        panel_parent = action_bar if callable(embedded_host) else self
        panel.setParent(panel_parent)
        panel.setWindowFlags(Qt.WindowType.Widget)
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setAutoFillBackground(True)
        panel.setStyleSheet(preprocessing_panel_style(self._is_dark_theme()))

        def accept_panel() -> None:
            (apply_callback or preview_callback)()
            self._close_preprocessing_panel()

        def cancel_panel() -> None:
            cancel_callback()
            self._close_preprocessing_panel()

        panel.previewRequested.connect(preview_callback)
        panel.applyRequested.connect(accept_panel)
        if subtract_callback is not None and hasattr(panel, "subtractRequested"):
            panel.subtractRequested.connect(lambda: (subtract_callback(), self._close_preprocessing_panel()))
        panel.cancelRequested.connect(cancel_panel)
        self._preprocessing_panel = panel
        self._preprocessing_panel_key = key
        if callable(embedded_host):
            title = {
                "smooth": "Smoothing",
                "background": "Background",
                "xrd_crop": "Crop XRD",
            }.get(key, "Preprocessing")
            embedded_host(key, panel, title)
            return
        panel.adjustSize()
        position = button.mapTo(self, button.rect().bottomLeft())
        max_x = max(0, self.width() - panel.width() - 8)
        max_y = max(0, self.height() - panel.height() - 8)
        panel.move(min(max(position.x(), 8), max_x), min(max(position.y() + 4, 8), max_y))
        panel.raise_()
        panel.show()

    def _smooth_active_pattern_plot(self) -> None:
        data = self._active_processed_observed_data()
        if data is None:
            data = self._active_observed_data()
        if data is None:
            return
        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)
        pattern = self._active_pattern()
        if pattern is None:
            return
        original_processed_points = [list(point) for point in pattern.processed_points]
        original_processed_label = pattern.processed_label
        original_background_removed = pattern.processed_background_removed
        source_label = pattern.processed_label or "Observed"
        analysis_x, analysis_y = _preprocessing_analysis_sample(x, y)
        sampled_plan = auto_smoothing_plan(analysis_x, analysis_y)
        plan = _smoothing_plan_for_full_signal(sampled_plan, analysis_x, x)
        panel = SmoothPanel(plan.window, auto_plan=plan, parent=self)

        def smoothed_curve() -> tuple[np.ndarray, str]:
            window = panel.window_size()
            strength = panel.noise_reduction()
            smooth_y = peak_preserving_smooth(y, window=window, strength=strength)
            label = f"{source_label} noise reduced ({strength:.0%}, peak-preserving SG w{window})"
            return smooth_y, label

        def preview_smoothing() -> None:
            smooth_y, label = smoothed_curve()
            self._replace_observed_curve(x, smooth_y, label)

        def apply_smoothing() -> None:
            smooth_y, label = smoothed_curve()
            self._set_preprocessed_observed_curve(
                x,
                smooth_y,
                label,
                pattern.processed_background_removed,
            )

        def cancel_smoothing() -> None:
            pattern.processed_points = original_processed_points
            pattern.processed_label = original_processed_label
            pattern.processed_background_removed = original_background_removed
            self._clear_probability_caches()
            if hasattr(self, "_invalidate_match_profile_cache"):
                self._invalidate_match_profile_cache(pattern.id if pattern is not None else None)
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation()

        self._show_preprocessing_panel(
            "smooth",
            self.finder_action_bar.smooth_button,
            panel,
            preview_smoothing,
            cancel_smoothing,
            apply_callback=apply_smoothing,
        )
    def _subtract_active_background_plot(self) -> None:
        data = self._active_processed_observed_data()
        if data is None:
            data = self._active_observed_data()
        if data is None:
            return
        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)
        pattern = self._active_pattern()
        if pattern is None:
            return
        original_processed_points = [list(point) for point in pattern.processed_points]
        original_processed_label = pattern.processed_label
        original_background_removed = pattern.processed_background_removed
        original_background_points = [list(point) for point in pattern.estimated_background_points]
        original_background_with_halo_points = [list(point) for point in pattern.estimated_background_with_halo_points]
        source_label = pattern.processed_label or "Observed"
        analysis_x, analysis_y = _preprocessing_analysis_sample(x, y)
        sampled_background_fit_y = self._background_estimation_signal(pattern, analysis_x, analysis_y)
        preview_background_fit_y = _expand_sampled_signal(analysis_x, sampled_background_fit_y, x)
        fit_signature = hashlib.blake2b(
            np.asarray(sampled_background_fit_y, dtype="<f8").tobytes(),
            digest_size=12,
        ).hexdigest()
        preparation_key = (
            str(getattr(pattern, "id", "")),
            len(x),
            round(float(x[0]), 6) if len(x) else 0.0,
            round(float(x[-1]), 6) if len(x) else 0.0,
            fit_signature,
        )
        cached_preparation = getattr(self, "_background_panel_preparation_cache", None)
        if cached_preparation is not None and cached_preparation[0] == preparation_key:
            plan, sampled_auto_model = cached_preparation[1], cached_preparation[2]
        else:
            plan = auto_background_plan(analysis_x, sampled_background_fit_y)
            sampled_auto_model = select_background_model(analysis_x, sampled_background_fit_y)
            self._background_panel_preparation_cache = (
                preparation_key,
                plan,
                sampled_auto_model,
            )
        auto_model = _expand_background_model(
            sampled_auto_model,
            analysis_x,
            x,
        )
        panel = BackgroundRemovalPanel(
            default_degree=plan.degree,
            auto_plan=plan,
            auto_model=auto_model,
            initial_state=getattr(self, "_background_removal_panel_state", None),
            parent=self,
        )
        preview_amorphous_component = estimate_amorphous_snip_component(
            x,
            preview_background_fit_y,
            np.asarray(auto_model.physical_background, dtype=float),
        )

        def save_background_panel_state() -> None:
            self._background_removal_panel_state = panel.export_state()

        def estimate_components(*, exact: bool = False) -> tuple[np.ndarray, np.ndarray]:
            save_background_panel_state()
            selected_model = auto_model
            background = np.asarray(selected_model.physical_background, dtype=float)
            combined = background + preview_amorphous_component
            combined = np.maximum(combined, background)
            if panel.low_angle_cuvette():
                halo = np.clip(combined - background, 0.0, None)
                end = float(panel.low_angle_end())
                width = max(float(panel.low_angle_width()), 1.0)
                start = end - width
                transition = np.clip((x - start) / width, 0.0, 1.0)
                transition = transition * transition * (3.0 - 2.0 * transition)
                strength = float(panel.low_angle_strength())
                keep_fraction = (1.0 - strength) + strength * transition
                combined = background + halo * keep_fraction
            level = float(getattr(panel, "background_level", lambda: 0.0)())
            background, combined = adjust_background_components(
                x,
                y,
                background,
                combined,
                level,
            )
            return np.asarray(background, dtype=float), np.asarray(combined, dtype=float)

        def processed_background_result(
            background: np.ndarray,
            combined: np.ndarray,
        ) -> tuple[np.ndarray, np.ndarray, str]:
            include_amorphous = bool(getattr(panel, "include_amorphous", lambda: False)())
            strength = float(getattr(panel, "amorphous_strength", lambda: 1.0)()) if include_amorphous else 0.0
            corrected, restored = restore_amorphous_contribution(
                y,
                background,
                combined,
                strength,
            )
            if include_amorphous:
                label = f"{source_label} - background; amorphous phase restored {strength:.0%}"
            else:
                label = f"{source_label} - background - amorphous contribution"
            return corrected, background + restored, label

        def preview_background_components() -> None:
            background, combined = estimate_components()
            corrected, displayed_total, processed_label = processed_background_result(background, combined)
            pattern.estimated_background_points = (
                np.column_stack([x, background]).astype(float).tolist() if panel.estimate_background() else []
            )
            pattern.estimated_background_with_halo_points = (
                np.column_stack([x, displayed_total]).astype(float).tolist() if panel.estimate_amorphous() else []
            )
            pattern.processed_background_removed = True
            self._replace_observed_curve(
                x,
                corrected,
                processed_label,
            )

        def apply_background_components() -> None:
            save_background_panel_state()
            background, combined = estimate_components(exact=True)
            corrected, displayed_total, processed_label = processed_background_result(background, combined)
            pattern.estimated_background_points = (
                np.column_stack([x, background]).astype(float).tolist() if panel.estimate_background() else []
            )
            pattern.estimated_background_with_halo_points = (
                np.column_stack([x, displayed_total]).astype(float).tolist() if panel.estimate_amorphous() else []
            )
            self._set_preprocessed_observed_curve(
                x,
                corrected,
                processed_label,
                True,
            )

        def cancel_background_removal() -> None:
            pattern.processed_points = original_processed_points
            pattern.processed_label = original_processed_label
            pattern.processed_background_removed = original_background_removed
            pattern.estimated_background_points = original_background_points
            pattern.estimated_background_with_halo_points = original_background_with_halo_points
            self._clear_probability_caches()
            if hasattr(self, "_invalidate_match_profile_cache"):
                self._invalidate_match_profile_cache(pattern.id if pattern is not None else None)
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation()

        preview_background_components()
        self._show_preprocessing_panel(
            "background",
            self.finder_action_bar.background_button,
            panel,
            preview_background_components,
            cancel_background_removal,
            apply_background_components,
            apply_callback=apply_background_components,
        )

    def _background_estimation_signal(self, pattern, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        fit_y = np.array(y, dtype=float, copy=True)
        if len(x) < 12 or len(x) != len(y):
            return fit_y

        finite = np.isfinite(x) & np.isfinite(fit_y)
        if int(np.count_nonzero(finite)) < max(8, len(x) // 5):
            return fit_y

        step_values = np.diff(x[finite])
        step_values = step_values[np.isfinite(step_values) & (step_values > 0.0)]
        step = float(np.nanmedian(step_values)) if len(step_values) else 0.03
        mask = np.zeros(len(x), dtype=bool)
        known_positions: list[float] = []
        fwhm = 0.18

        try:
            candidates = self._profile_candidates_for_pattern(pattern) if hasattr(self, "_profile_candidates_for_pattern") else []
            if candidates and hasattr(self, "_finder_result_for_pattern"):
                result, _ = self._finder_result_for_pattern(pattern, candidates)
                if result is not None:
                    fwhm = float(getattr(result, "fwhm", fwhm) or fwhm)
                    for candidate_result in getattr(result, "candidates", []) or []:
                        for value in getattr(candidate_result, "peak_two_theta", []) or []:
                            position = float(value)
                            if np.isfinite(position) and float(x[0]) <= position <= float(x[-1]):
                                known_positions.append(position)
        except Exception:
            known_positions = []

        known_radius = max(0.12, min(0.75, fwhm * 2.6))
        for position in known_positions:
            mask |= np.abs(x - position) <= known_radius

        local_y = fit_y[finite]
        span = max(float(np.nanpercentile(local_y, 99) - np.nanpercentile(local_y, 5)), 1.0)
        noise = self._background_signal_noise(local_y)
        try:
            peak_indices, _ = find_peaks(
                fit_y,
                prominence=max(4.5 * noise, 0.025 * span, 1.0),
                distance=max(3, int(round(0.10 / max(step, 1.0e-6)))),
            )
            observed_radius = max(2, int(round(max(0.12, min(0.45, fwhm * 2.0)) / max(step, 1.0e-6))))
            for peak_index in peak_indices:
                left = max(0, int(peak_index) - observed_radius)
                right = min(len(mask), int(peak_index) + observed_radius + 1)
                mask[left:right] = True
        except Exception:
            pass

        valid = finite & ~mask
        if int(np.count_nonzero(valid)) < max(8, int(0.18 * len(x))):
            return fit_y

        interpolated = np.interp(x, x[valid], fit_y[valid])
        suppressed = np.array(fit_y, copy=True)
        suppressed[mask & finite] = interpolated[mask & finite]
        return np.minimum(suppressed, fit_y)

    @staticmethod
    def _background_signal_noise(y: np.ndarray) -> float:
        differences = np.diff(np.asarray(y, dtype=float))
        if len(differences) == 0:
            return 1.0
        median = float(np.nanmedian(differences))
        mad = float(np.nanmedian(np.abs(differences - median)))
        return max(1.4826 * mad / np.sqrt(2.0), 1.0)

    def _crop_xrd_patterns_plot(self) -> None:
        patterns = []
        ranges_by_pattern = {}
        for pattern in self.project.patterns:
            data = observed_pattern_data(pattern)
            if data is None or not len(data):
                continue
            x = np.asarray(data[:, 0], dtype=float)
            finite = x[np.isfinite(x)]
            if not len(finite):
                continue
            patterns.append((pattern.id, pattern.name, float(np.nanmin(finite)), float(np.nanmax(finite))))
            ranges_by_pattern[pattern.id] = [list(item[:2]) for item in getattr(pattern, "crop_ranges", [])]
        if not patterns:
            return
        active = self._active_pattern()
        active_id = active.id if active is not None else patterns[0][0]
        original_ranges = {
            pattern.id: [list(item[:2]) for item in getattr(pattern, "crop_ranges", [])]
            for pattern in self.project.patterns
        }
        panel = XrdCropPanel(patterns, ranges_by_pattern, active_pattern_id=active_id, parent=self)

        def apply_ranges() -> None:
            ranges = panel.ranges_by_pattern()
            for pattern in self.project.patterns:
                pattern.crop_ranges = [list(item[:2]) for item in ranges.get(pattern.id, [])]
            self.project.touch()
            self.project_changed.emit()
            self.match_plot_view_initialized = False
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation(active_only=False)

        def cancel_ranges() -> None:
            for pattern in self.project.patterns:
                pattern.crop_ranges = [list(item[:2]) for item in original_ranges.get(pattern.id, [])]
            self.project.touch()
            self.project_changed.emit()
            self.match_plot_view_initialized = False
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation(active_only=False)

        self._show_preprocessing_panel(
            "xrd_crop",
            self.finder_action_bar.crop_button,
            panel,
            apply_ranges,
            cancel_ranges,
        )

    def _reset_observed_preprocessing(self) -> None:
        pattern = self._active_pattern()
        if pattern is not None:
            pattern.processed_points.clear()
            pattern.processed_label = ""
            pattern.processed_background_removed = False
            pattern.estimated_background_points.clear()
            pattern.estimated_background_with_halo_points.clear()
            pattern.crop_ranges.clear()
            self.project.touch()
            self.project_changed.emit()
        if hasattr(self, "_set_scoring_source_status"):
            self._set_scoring_source_status("Auto")
        if hasattr(self, "_auto_scoring_cache"):
            self._auto_scoring_cache.clear()
        self._clear_probability_caches()
        if hasattr(self, "_invalidate_match_profile_cache"):
            self._invalidate_match_profile_cache(pattern.id if pattern is not None else None)
        self._refresh_observed_pattern_plot()
        self._rerun_active_calculation()

    def _set_preprocessed_observed_curve(
        self,
        x: np.ndarray,
        y: np.ndarray,
        name: str,
        background_removed: bool,
    ) -> None:
        pattern = self._active_pattern()
        if pattern is None:
            return
        processed = np.column_stack([x, y])
        pattern.processed_points = processed.astype(float).tolist()
        pattern.processed_label = name
        pattern.processed_background_removed = background_removed
        if hasattr(self, "_set_scoring_source_status"):
            self._set_scoring_source_status("Visible")
        if hasattr(self, "_auto_scoring_cache"):
            self._auto_scoring_cache.clear()
        self.project.touch()
        self.project_changed.emit()
        self._clear_probability_caches()
        if hasattr(self, "_invalidate_match_profile_cache"):
            self._invalidate_match_profile_cache(pattern.id)
        self._replace_observed_curve(x, y, name)
        self._rerun_active_calculation()

    def _rerun_active_calculation(self, *, active_only: bool = True) -> None:
        has_profile_candidates = bool(self.match_candidates)
        if self.show_all_selected_patterns and hasattr(self, "_profile_candidates_for_pattern"):
            has_profile_candidates = has_profile_candidates or any(
                self._profile_candidates_for_pattern(pattern)
                for pattern in self._patterns_to_display()
            )
        if has_profile_candidates:
            self._recalculate_match_profile(active_only=active_only)
        elif self.active_overlay_entry_id:
            candidate = self._selected_candidate_row()
            if candidate is not None:
                self.active_overlay_entry_id = None
                self._calculate_candidate_overlay(candidate, show_errors=False)

    def _replace_observed_curve(self, x: np.ndarray, y: np.ndarray, name: str) -> None:
        pattern = self._active_pattern()
        self._draw_observed_patterns(
            active_override=(pattern.id if pattern is not None else "", np.column_stack([x, y]), name)
        )
