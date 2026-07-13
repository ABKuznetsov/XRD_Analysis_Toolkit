from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from xrd_finder.services.preprocessing_service import (
    auto_background_plan,
    auto_smoothing_plan,
    smooth_observed_curve,
)
from xrd_finder.services.background_model_selection import select_background_model
from xrd_finder.ui.observed_patterns import observed_pattern_data
from xrd_finder.ui.preprocessing_dialogs import BackgroundRemovalPanel, SmoothPanel, XrdCropPanel, background_method_label
from xrd_finder.ui.theme import preprocessing_panel_style


class PhaseFinderPreprocessingActionsMixin:
    def _close_preprocessing_panel(self) -> None:
        panel = getattr(self, "_preprocessing_panel", None)
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
    ) -> None:
        if getattr(self, "_preprocessing_panel", None) is not None:
            if getattr(self, "_preprocessing_panel_key", None) == key:
                self._close_preprocessing_panel()
                return
            self._close_preprocessing_panel()

        panel.setParent(self)
        panel.setWindowFlags(Qt.WindowType.Widget)
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setAutoFillBackground(True)
        panel.setStyleSheet(preprocessing_panel_style(self._is_dark_theme()))
        panel.adjustSize()
        position = button.mapTo(self, button.rect().bottomLeft())
        max_x = max(0, self.width() - panel.width() - 8)
        max_y = max(0, self.height() - panel.height() - 8)
        panel.move(min(max(position.x(), 8), max_x), min(max(position.y() + 4, 8), max_y))
        panel.raise_()

        def accept_panel() -> None:
            preview_callback()
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
        plan = auto_smoothing_plan(x, y)
        panel = SmoothPanel(plan.window, auto_plan=plan, parent=self)

        def preview_smoothing() -> None:
            window = panel.window_size()
            method = panel.method()
            smooth_y = np.asarray(y, dtype=float)
            for _ in range(panel.passes()):
                smooth_y = smooth_observed_curve(smooth_y, method, window, panel.polyorder(), panel.gaussian_sigma())
            label_method = {
                "savgol": "Savitzky-Golay",
                "moving": "moving average",
                "gaussian": "Gaussian",
            }.get(method, method)
            pass_text = "pass" if panel.passes() == 1 else "passes"
            self._set_preprocessed_observed_curve(
                x,
                smooth_y,
                f"{source_label} smoothed ({label_method}, window {window}, {panel.passes()} {pass_text})",
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
        plan = auto_background_plan(x, y)
        auto_model = select_background_model(x, y)
        panel = BackgroundRemovalPanel(
            default_degree=plan.degree,
            auto_plan=plan,
            auto_model=auto_model,
            initial_state=getattr(self, "_background_removal_panel_state", None),
            parent=self,
        )

        def save_background_panel_state() -> None:
            self._background_removal_panel_state = panel.export_state()

        def settings_model_curve(settings: dict[str, int | str]) -> np.ndarray:
            method = str(settings["method"])
            if method == "exponential":
                method = f"exponential_{int(settings['exponential_terms'])}"
            elif method == "snip":
                method = f"snip_{int(settings['snip_window'])}"
            if method == "constant":
                return np.full_like(y, float(np.nanpercentile(y, int(settings["floor_percentile"]))))
            return self._estimate_background(x, y, degree=int(settings["degree"]), method=method)

        def estimate_components() -> tuple[np.ndarray, np.ndarray]:
            save_background_panel_state()
            background = np.asarray(settings_model_curve(panel.settings_for("physical")), dtype=float)
            combined = np.asarray(settings_model_curve(panel.settings_for("total")), dtype=float)
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
            return np.asarray(background, dtype=float), np.asarray(combined, dtype=float)

        def preview_background_components() -> None:
            background, combined = estimate_components()
            pattern.estimated_background_points = (
                np.column_stack([x, background]).astype(float).tolist() if panel.estimate_background() else []
            )
            pattern.estimated_background_with_halo_points = (
                np.column_stack([x, combined]).astype(float).tolist() if panel.estimate_amorphous() else []
            )
            self.project.touch()
            self.project_changed.emit()
            self._clear_probability_caches()
            if hasattr(self, "_invalidate_match_profile_cache"):
                self._invalidate_match_profile_cache(pattern.id)
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation()

        def subtract_background_components() -> None:
            save_background_panel_state()
            background, combined = estimate_components()
            baseline = combined if panel.target() == "total" else background
            current_settings = panel.settings_for(panel.target())
            label_method = background_method_label(str(current_settings["method"]), int(current_settings["degree"]))
            component = {
                "physical": "physical background",
                "total": "background + amorphous phase",
            }.get(panel.target(), "background")
            preview_background_components()
            self._set_preprocessed_observed_curve(
                x,
                y - baseline,
                f"{source_label} - {component} ({label_method})",
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

        self._show_preprocessing_panel(
            "background",
            self.finder_action_bar.background_button,
            panel,
            preview_background_components,
            cancel_background_removal,
            subtract_background_components,
        )

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
            self._rerun_active_calculation()

        def cancel_ranges() -> None:
            for pattern in self.project.patterns:
                pattern.crop_ranges = [list(item[:2]) for item in original_ranges.get(pattern.id, [])]
            self.project.touch()
            self.project_changed.emit()
            self.match_plot_view_initialized = False
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation()

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

    def _rerun_active_calculation(self) -> None:
        has_profile_candidates = bool(self.match_candidates)
        if self.show_all_selected_patterns and hasattr(self, "_profile_candidates_for_pattern"):
            has_profile_candidates = has_profile_candidates or any(
                self._profile_candidates_for_pattern(pattern)
                for pattern in self._patterns_to_display()
            )
        if has_profile_candidates:
            self._recalculate_match_profile()
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
