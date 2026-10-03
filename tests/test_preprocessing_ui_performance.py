from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton, QSlider

from xrd_finder.services.background_model_selection import BackgroundModelSelection
from xrd_finder.services.preprocessing_service import (
    AutoSmoothingPlan,
    adjust_background_components,
    adjust_background_level,
    combine_amorphous_contribution,
    estimate_amorphous_snip_component,
    peak_preserving_smooth,
    restore_amorphous_contribution,
)
from xrd_finder.ui.observed_pattern_actions import (
    PhaseFinderObservedPatternActionsMixin,
    _minimum_peak_baseline,
    _pattern_has_amorphous_fill,
    _processed_amorphous_background_data,
    _processed_amorphous_fill_values,
)
from xrd_finder.ui.finder_action_bar import FinderActionBar
from xrd_finder.ui.preprocessing_dialogs import BackgroundRemovalPanel, SmoothPanel
from xrd_finder.ui.preprocessing_actions import (
    PhaseFinderPreprocessingActionsMixin,
    _expand_background_model,
    _expand_sampled_signal,
    _preprocessing_analysis_sample,
    _smoothing_plan_for_full_signal,
)


class PreprocessingUiPerformanceTests(unittest.TestCase):
    def test_smoothing_preview_is_live_but_commits_only_on_apply(self) -> None:
        x = np.linspace(10.0, 80.0, 1000)
        y = 100.0 + np.sin(x)
        pattern = SimpleNamespace(
            id="pattern-1",
            processed_points=[],
            processed_label="",
            processed_background_removed=False,
        )

        class FakePanel:
            def __init__(self, *_args, **_kwargs):
                pass

            def window_size(self):
                return 7

            def method(self):
                return "moving"

            def passes(self):
                return 1

            def polyorder(self):
                return 2

            def gaussian_sigma(self):
                return 0.2

            def noise_reduction(self):
                return 0.65

        class FakeWindow:
            finder_action_bar = SimpleNamespace(smooth_button=object())

            def __init__(self):
                self.previewed = None
                self.committed = None
                self.preview_did_not_commit = False

            def _active_processed_observed_data(self):
                return None

            def _active_observed_data(self):
                return np.column_stack([x, y])

            def _active_pattern(self):
                return pattern

            def _replace_observed_curve(self, full_x, values, label):
                self.previewed = (full_x, values, label)

            def _set_preprocessed_observed_curve(self, full_x, values, label, removed):
                self.committed = (full_x, values, label, removed)

            def _show_preprocessing_panel(
                self,
                _key,
                _button,
                _panel,
                preview,
                _cancel,
                _subtract=None,
                apply_callback=None,
            ):
                preview()
                self.preview_did_not_commit = self.committed is None
                apply_callback()

        window = FakeWindow()
        with (
            patch("xrd_finder.ui.preprocessing_actions.SmoothPanel", FakePanel),
            patch(
                "xrd_finder.ui.preprocessing_actions.auto_smoothing_plan",
                return_value=AutoSmoothingPlan("moving", 7),
            ),
        ):
            PhaseFinderPreprocessingActionsMixin._smooth_active_pattern_plot(window)

        self.assertIsNotNone(window.previewed)
        self.assertTrue(window.preview_did_not_commit)
        self.assertIsNotNone(window.committed)

    def test_smoothing_slider_changes_emit_debounced_preview(self) -> None:
        app = QApplication.instance() or QApplication([])
        panel = SmoothPanel(default_window=7)
        spy = QSignalSpy(panel.previewRequested)
        panel._noise_reduction.slider.setValue(75)
        self.assertEqual(spy.count(), 0)
        QTest.qWait(140)
        app.processEvents()
        self.assertEqual(spy.count(), 1)
        panel.deleteLater()

    def test_peak_preserving_smoothing_reduces_noise_without_moving_peak(self) -> None:
        rng = np.random.default_rng(42)
        x = np.linspace(20.0, 40.0, 2001)
        clean = 15.0 + 120.0 * np.exp(-0.5 * ((x - 30.0) / 0.12) ** 2)
        noisy = clean + rng.normal(0.0, 3.0, len(x))

        smoothed = peak_preserving_smooth(noisy, window=7, strength=1.0)

        outside = np.abs(x - 30.0) > 1.0
        before_noise = float(np.std(noisy[outside] - clean[outside]))
        after_noise = float(np.std(smoothed[outside] - clean[outside]))
        peak_shift = abs(float(x[np.argmax(smoothed)] - x[np.argmax(clean)]))
        peak_region = np.abs(x - 30.0) < 0.6
        clean_area = float(np.trapezoid(clean[peak_region] - 15.0, x[peak_region]))
        local_baseline = 0.5 * (
            float(np.mean(smoothed[(x > 29.4) & (x < 29.55)]))
            + float(np.mean(smoothed[(x > 30.45) & (x < 30.6)]))
        )
        smoothed_area = float(
            np.trapezoid(smoothed[peak_region] - local_baseline, x[peak_region])
        )
        self.assertLess(after_noise, before_noise * 0.7)
        self.assertLessEqual(peak_shift, float(x[1] - x[0]) + 1.0e-12)
        self.assertLess(abs(smoothed_area - clean_area) / clean_area, 0.03)

    def test_background_preview_immediately_updates_the_corrected_curve(self) -> None:
        x = np.linspace(10.0, 80.0, 1000)
        y = 100.0 + np.sin(x)
        pattern = SimpleNamespace(
            id="pattern-1",
            processed_points=[],
            processed_label="",
            processed_background_removed=False,
            estimated_background_points=[],
            estimated_background_with_halo_points=[],
        )

        class FakePanel:
            def __init__(self, *_args, **_kwargs):
                pass

            def export_state(self):
                return {}

            def settings_for(self, target):
                return {
                    "method": "auto",
                    "degree": 4,
                    "exponential_terms": 1,
                    "snip_window": 20,
                    "floor_percentile": 10,
                }

            def target(self):
                return "physical"

            def low_angle_cuvette(self):
                return False

            def estimate_background(self):
                return True

            def estimate_amorphous(self):
                return False

        class FakeWindow:
            finder_action_bar = SimpleNamespace(background_button=object())
            _background_removal_panel_state = None

            def __init__(self):
                self.corrected = None
                self.previewed = None
                self.preview_did_not_commit = False

            def _active_processed_observed_data(self):
                return None

            def _active_observed_data(self):
                return np.column_stack([x, y])

            def _active_pattern(self):
                return pattern

            def _background_estimation_signal(self, _pattern, _x, values):
                return np.asarray(values, dtype=float)

            def _estimate_background(self, full_x, fit_signal, **_kwargs):
                self.full_lengths = (len(full_x), len(fit_signal))
                return np.full_like(full_x, 25.0)

            def _set_preprocessed_observed_curve(self, full_x, corrected_y, label, removed):
                self.corrected = (full_x, corrected_y, label, removed)

            def _replace_observed_curve(self, full_x, corrected_y, label):
                self.previewed = (full_x, corrected_y, label)

            def _show_preprocessing_panel(
                self,
                _key,
                _button,
                _panel,
                preview,
                _cancel,
                _subtract=None,
                apply_callback=None,
            ):
                preview()
                self.preview_did_not_commit = self.preview_did_not_commit or self.corrected is None
                if apply_callback is not None:
                    apply_callback()

        model = BackgroundModelSelection(
            2, 1, 7.0, 4.0, 0.1,
            np.full_like(x, 25.0),
            np.zeros_like(x),
        )
        window = FakeWindow()
        with (
            patch("xrd_finder.ui.preprocessing_actions.BackgroundRemovalPanel", FakePanel),
            patch("xrd_finder.ui.preprocessing_actions.auto_background_plan", return_value=SimpleNamespace(degree=4)),
            patch("xrd_finder.ui.preprocessing_actions.select_background_model", return_value=model) as select_model,
            patch(
                "xrd_finder.ui.preprocessing_actions.estimate_amorphous_snip_component",
                return_value=np.zeros_like(x),
            ),
        ):
            PhaseFinderPreprocessingActionsMixin._subtract_active_background_plot(window)
            PhaseFinderPreprocessingActionsMixin._subtract_active_background_plot(window)
        self.assertIsNotNone(window.previewed)
        np.testing.assert_allclose(window.previewed[1], y - 25.0)
        self.assertTrue(window.preview_did_not_commit)
        self.assertIsNotNone(window.corrected)
        np.testing.assert_allclose(window.corrected[1], y - 25.0)
        self.assertTrue(window.corrected[3])
        self.assertEqual(select_model.call_count, 1)

    def test_background_slider_changes_emit_debounced_preview(self) -> None:
        app = QApplication.instance() or QApplication([])
        panel = BackgroundRemovalPanel(default_degree=4)
        spy = QSignalSpy(panel.previewRequested)
        panel._level.slider.setValue(25)
        self.assertEqual(spy.count(), 0)
        QTest.qWait(140)
        app.processEvents()
        self.assertEqual(spy.count(), 1)
        panel.deleteLater()

    def test_background_panel_exposes_two_levels_amorphous_toggle_apply_and_cancel(self) -> None:
        app = QApplication.instance() or QApplication([])
        panel = BackgroundRemovalPanel(default_degree=4)
        panel.show()
        app.processEvents()

        visible_sliders = [widget for widget in panel.findChildren(QSlider) if widget.isVisibleTo(panel)]
        visible_combos = [widget for widget in panel.findChildren(QComboBox) if widget.isVisibleTo(panel)]
        visible_checks = [widget for widget in panel.findChildren(QCheckBox) if widget.isVisibleTo(panel)]
        visible_buttons = {
            widget.text()
            for widget in panel.findChildren(QPushButton)
            if widget.isVisibleTo(panel)
        }

        self.assertEqual(len(visible_sliders), 2)
        self.assertEqual(visible_combos, [])
        self.assertEqual([widget.text() for widget in visible_checks], ["Include amorphous contribution"])
        self.assertEqual(visible_buttons, {"Apply", "Cancel"})
        panel.close()
        panel.deleteLater()

    def test_background_level_moves_curve_without_clipping_negative_values(self) -> None:
        x = np.linspace(10.0, 70.0, 1201)
        y = 5.0 + 0.3 * np.sin(x * 1.7)
        y += 20.0 * np.exp(-0.5 * ((x - 32.0) / 0.12) ** 2)
        candidate = np.full_like(y, -0.5)

        lower = adjust_background_level(x, y, candidate, -1.0)
        center = adjust_background_level(x, y, candidate, 0.0)
        higher = adjust_background_level(x, y, candidate, 1.0)

        self.assertTrue(np.all(lower <= center + 1.0e-12))
        self.assertTrue(np.all(center <= higher + 1.0e-12))
        self.assertLess(float(np.nanmin(lower)), 0.0)
        self.assertGreater(float(np.nanpercentile(y - higher, 1.0)), -1.0e-9)

    def test_amorphous_toggle_enables_snip_strength_slider_and_preview(self) -> None:
        app = QApplication.instance() or QApplication([])
        panel = BackgroundRemovalPanel(default_degree=4)
        spy = QSignalSpy(panel.previewRequested)

        self.assertFalse(panel.include_amorphous())
        self.assertFalse(panel._amorphous_strength.isEnabled())
        self.assertEqual(panel.settings_for("total")["method"], "snip")

        panel._include_amorphous.setChecked(True)
        QTest.qWait(140)
        app.processEvents()

        self.assertTrue(panel.include_amorphous())
        self.assertTrue(panel._amorphous_strength.isEnabled())
        self.assertGreaterEqual(spy.count(), 1)
        panel.deleteLater()

    def test_amorphous_strength_scales_snip_component(self) -> None:
        physical = np.array([2.0, 3.0, 4.0])
        snip_total = np.array([6.0, 2.0, 10.0])

        np.testing.assert_allclose(
            combine_amorphous_contribution(physical, snip_total, 0.0),
            physical,
        )
        np.testing.assert_allclose(
            combine_amorphous_contribution(physical, snip_total, 0.5),
            np.array([4.0, 3.0, 7.0]),
        )
        np.testing.assert_allclose(
            combine_amorphous_contribution(physical, snip_total, 1.0),
            np.array([6.0, 3.0, 10.0]),
        )

    def test_amorphous_strength_restores_snip_component_to_corrected_signal(self) -> None:
        observed = np.array([10.0, 10.0, 10.0])
        physical = np.array([2.0, 3.0, 4.0])
        snip_total = np.array([6.0, 2.0, 10.0])

        corrected, restored = restore_amorphous_contribution(
            observed,
            physical,
            snip_total,
            0.5,
        )

        np.testing.assert_allclose(corrected, np.array([6.0, 7.0, 3.0]))
        np.testing.assert_allclose(restored, np.array([2.0, 0.0, 3.0]))

    def test_background_level_adjustment_preserves_amorphous_component(self) -> None:
        x = np.linspace(10.0, 20.0, 101)
        y = 20.0 + np.sin(x)
        physical = np.full_like(x, 5.0)
        amorphous = 3.0 * np.exp(-0.5 * ((x - 15.0) / 1.5) ** 2)

        adjusted_physical, adjusted_total = adjust_background_components(
            x,
            y,
            physical,
            physical + amorphous,
            -1.0,
        )

        np.testing.assert_allclose(adjusted_total - adjusted_physical, amorphous)

    def test_snip_amorphous_estimate_recovers_a_broad_hump(self) -> None:
        x = np.linspace(10.0, 80.0, 2334)
        physical = 25.0 + 0.1 * (80.0 - x)
        broad = 45.0 * np.exp(-0.5 * ((x - 36.0) / 4.0) ** 2)
        narrow = 180.0 * np.exp(-0.5 * ((x - 42.0) / 0.08) ** 2)
        observed = physical + broad + narrow

        amorphous = estimate_amorphous_snip_component(x, observed, physical)

        self.assertGreater(float(np.max(amorphous)), 25.0)
        self.assertLess(float(amorphous[np.argmax(narrow)]), 65.0)

    def test_multi_pattern_legend_lists_saved_amorphous_phase(self) -> None:
        pattern = SimpleNamespace(
            name="sample",
            processed_background_removed=True,
            estimated_background_points=[[10.0, 2.0], [20.0, 2.0]],
            estimated_background_with_halo_points=[[10.0, 5.0], [20.0, 4.0]],
        )
        owner = SimpleNamespace(
            plot_view_settings=SimpleNamespace(
                legend_font_size=10,
                multi_legend_phase_names_visible=True,
            ),
            _profile_candidates_for_pattern=lambda _pattern: [],
        )

        self.assertTrue(_pattern_has_amorphous_fill(pattern))
        html = PhaseFinderObservedPatternActionsMixin._multi_pattern_legend_html(
            owner,
            pattern,
            "#202124",
        )
        self.assertIn("Amorphous phase", html)

    def test_processed_amorphous_fill_keeps_shape_and_uses_one_lower_baseline(self) -> None:
        physical = np.array([2.0, 3.0, 4.0])
        restored_total = np.array([4.0, 3.0, 7.0])
        local_minimum = np.array([25.0, 26.0, 24.0])

        lower, upper = _processed_amorphous_fill_values(
            physical,
            restored_total,
            local_minimum,
        )

        np.testing.assert_allclose(lower, local_minimum)
        np.testing.assert_allclose(upper, np.array([27.0, 26.0, 27.0]))

    def test_amorphous_fill_baseline_is_a_small_constant_lift(self) -> None:
        y = np.array([-4.0, 0.0, 3.0, 6.0, 12.0, 40.0])

        baseline = _minimum_peak_baseline(y)

        np.testing.assert_allclose(baseline, np.full_like(y, np.nanpercentile(y, 10.0)))

    def test_processed_amorphous_curve_is_available_as_finder_background(self) -> None:
        pattern = SimpleNamespace(
            processed_background_removed=True,
            processed_points=[[10.0, 25.0], [20.0, 30.0]],
            estimated_background_points=[[10.0, 2.0], [20.0, 2.0]],
            estimated_background_with_halo_points=[[10.0, 5.0], [20.0, 4.0]],
        )

        background = _processed_amorphous_background_data(pattern)

        self.assertIsNotNone(background)
        np.testing.assert_allclose(background[:, 0], np.array([10.0, 20.0]))
        np.testing.assert_allclose(background[:, 1], np.array([28.5, 27.5]))

    def test_analysis_sample_is_bounded_and_keeps_full_range(self) -> None:
        x = np.linspace(5.0, 120.0, 100_000)
        y = np.sin(x)
        sampled_x, sampled_y = _preprocessing_analysis_sample(x, y, max_points=2048)
        self.assertLessEqual(len(sampled_x), 2048)
        self.assertEqual(len(sampled_x), len(sampled_y))
        self.assertEqual(sampled_x[0], x[0])
        self.assertEqual(sampled_x[-1], x[-1])

    def test_sampled_smoothing_window_is_converted_to_full_grid(self) -> None:
        full_x = np.linspace(10.0, 80.0, 7001)
        sampled_x = full_x[::10]
        sampled_plan = AutoSmoothingPlan("savgol", 5, polyorder=2)
        plan = _smoothing_plan_for_full_signal(sampled_plan, sampled_x, full_x)
        self.assertEqual(plan.window, 21)
        self.assertEqual(plan.method, "savgol")

    def test_background_model_is_interpolated_back_to_full_signal(self) -> None:
        sampled_x = np.linspace(10.0, 80.0, 100)
        full_x = np.linspace(10.0, 80.0, 1000)
        model = BackgroundModelSelection(
            2, 3, 7.0, 4.0, 0.1,
            np.linspace(10.0, 20.0, len(sampled_x)),
            np.linspace(0.0, 5.0, len(sampled_x)),
        )
        expanded = _expand_background_model(model, sampled_x, full_x)
        self.assertEqual(len(expanded.physical_background), len(full_x))
        self.assertEqual(len(expanded.amorphous_component), len(full_x))
        self.assertAlmostEqual(expanded.physical_background[0], 10.0)
        self.assertAlmostEqual(expanded.physical_background[-1], 20.0)

    def test_sampled_background_working_signal_is_expanded_before_full_grid_estimation(self) -> None:
        sampled_x = np.linspace(10.0, 80.0, 128)
        sampled_y = 150.0 + 0.25 * sampled_x
        full_x = np.linspace(10.0, 80.0, 10_001)
        expanded = _expand_sampled_signal(sampled_x, sampled_y, full_x)
        self.assertEqual(len(expanded), len(full_x))
        np.testing.assert_allclose(expanded, 150.0 + 0.25 * full_x)

    def test_expand_emits_processing_request_on_next_event_turn(self) -> None:
        app = QApplication.instance() or QApplication([])
        bar = FinderActionBar()
        bar.show()
        spy = QSignalSpy(bar.smoothRequested)
        QTest.mouseClick(bar.smooth_button, Qt.MouseButton.LeftButton)
        self.assertEqual(spy.count(), 0)
        app.processEvents()
        self.assertEqual(spy.count(), 1)
        bar.close()
        bar.deleteLater()


if __name__ == "__main__":
    unittest.main()
