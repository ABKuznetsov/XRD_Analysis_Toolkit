from __future__ import annotations

import numpy as np

from xrd_finder.finder.service import FinderService
from xrd_finder.ui.analysis_windows import PhaseFinderWindow


def _peak(x: np.ndarray, center: float, width: float = 0.12) -> np.ndarray:
    return np.exp(-0.5 * ((x - center) / width) ** 2)


def test_later_phase_fits_positive_residual_without_stealing_existing_signal() -> None:
    x = np.linspace(10.0, 60.0, 4000)
    primary = 5.0 * _peak(x, 24.0) + 3.0 * _peak(x, 38.0)
    impurity = 1.2 * _peak(x, 31.0) + 0.8 * _peak(x, 47.0)
    target = primary + impurity

    scales = FinderService()._fit_incremental_scales(target, [primary, impurity])

    assert np.isclose(scales[0], 1.0, atol=0.02)
    assert np.isclose(scales[1], 1.0, atol=0.08)


def test_later_phase_is_rejected_when_it_only_duplicates_covered_peaks() -> None:
    x = np.linspace(10.0, 60.0, 4000)
    primary = 5.0 * _peak(x, 24.0) + 3.0 * _peak(x, 38.0)
    duplicate = 4.0 * _peak(x, 24.0) + 2.0 * _peak(x, 38.0)

    scales = FinderService()._fit_incremental_scales(primary, [primary, duplicate])

    assert np.isclose(scales[0], 1.0, atol=0.02)
    assert scales[1] == 0.0


def test_later_phase_cannot_trade_covered_intensity_for_one_small_residual_peak() -> None:
    x = np.linspace(10.0, 60.0, 4000)
    primary = 5.0 * _peak(x, 24.0) + 3.0 * _peak(x, 38.0)
    residual = 0.35 * _peak(x, 47.0)
    misleading = 4.0 * _peak(x, 24.0) + 0.5 * _peak(x, 47.0)

    scales = FinderService()._fit_incremental_scales(primary + residual, [primary, misleading])

    assert np.isclose(scales[0], 1.0, atol=0.02)
    assert scales[1] < 0.08


def test_later_phase_refits_primary_when_they_share_a_strong_reflection() -> None:
    x = np.linspace(10.0, 60.0, 4000)
    primary = 5.0 * _peak(x, 24.0) + 3.0 * _peak(x, 38.0)
    secondary = 5.0 * _peak(x, 24.0) + 2.0 * _peak(x, 31.0) + 1.5 * _peak(x, 47.0)
    target = 0.8 * primary + 0.25 * secondary

    scales = FinderService()._fit_incremental_scales(target, [primary, secondary])

    assert np.isclose(scales[0], 0.8, atol=0.02)
    assert np.isclose(scales[1], 0.25, atol=0.02)


def test_gain_context_jointly_refits_overlapping_selected_phases() -> None:
    x = np.linspace(10.0, 60.0, 4000)
    primary = 5.0 * _peak(x, 24.0) + 3.0 * _peak(x, 38.0)
    secondary = 5.0 * _peak(x, 24.0) + 2.0 * _peak(x, 31.0) + 1.5 * _peak(x, 47.0)
    target = 0.8 * primary + 0.25 * secondary

    window = PhaseFinderWindow.__new__(PhaseFinderWindow)
    scales = PhaseFinderWindow._fit_nonnegative_scales(
        window,
        target,
        [primary, secondary],
        np.ones_like(target),
    )

    assert np.isclose(scales[0], 0.8, atol=0.02)
    assert np.isclose(scales[1], 0.25, atol=0.02)


def test_direct_stick_gain_survives_underdetermined_profile_fit() -> None:
    class GainHarness:
        _candidate_cached_json_peaks = staticmethod(lambda _candidate: [object()])
        _aligned_candidate_gain_peaks = staticmethod(lambda _candidate, peaks, _context: peaks)
        _candidate_residual_line_gain = staticmethod(lambda _peaks, _context: 8.0)
        _candidate_gain_profile = staticmethod(lambda _candidate, _peaks, _context: np.ones(4))
        _candidate_gain_value_for_profile = staticmethod(lambda _profile, _context: 0.0)

    gain = PhaseFinderWindow._candidate_row_integral_gain(
        GainHarness(),
        ["COD", "1", "A", "phase", "", "", "", ""],
        {"gain_stage": "direct"},
    )

    assert np.isclose(gain, 2.8)


def test_overlap_stage_detects_underfit_at_an_already_assigned_peak() -> None:
    x = np.linspace(20.0, 40.0, 4001)
    observed = 10.0 * _peak(x, 30.0, 0.10) + 4.0 * _peak(x, 35.0, 0.12)
    selected = 6.0 * _peak(x, 30.0, 0.10) + 4.0 * _peak(x, 35.0, 0.12)
    residual = np.clip(observed - selected, 0.0, None)
    window = PhaseFinderWindow.__new__(PhaseFinderWindow)
    context = {
        "x": x,
        "target": observed,
        "selected_total": selected,
        "residual_target": residual,
        "selected_peak_positions": np.asarray([30.0, 35.0]),
        "fwhm": 0.24,
    }

    records = PhaseFinderWindow._gain_stage_records(window, context, "overlap", limit=10)

    assert len(records) == 1
    assert np.isclose(records[0].two_theta, 30.0, atol=0.03)
    assert records[0].height > 3.0


def test_overlap_stage_ignores_an_already_well_fitted_peak() -> None:
    x = np.linspace(20.0, 40.0, 4001)
    observed = 10.0 * _peak(x, 30.0, 0.10) + 4.0 * _peak(x, 35.0, 0.12)
    selected = 9.7 * _peak(x, 30.0, 0.10) + 3.9 * _peak(x, 35.0, 0.12)
    residual = np.clip(observed - selected, 0.0, None)
    window = PhaseFinderWindow.__new__(PhaseFinderWindow)
    context = {
        "x": x,
        "target": observed,
        "selected_total": selected,
        "residual_target": residual,
        "selected_peak_positions": np.asarray([30.0, 35.0]),
        "fwhm": 0.24,
    }

    records = PhaseFinderWindow._gain_stage_records(window, context, "overlap", limit=10)

    assert records == []
