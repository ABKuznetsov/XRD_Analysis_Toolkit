from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.peak_matching import ObservedLineRecord


class _GainRecordHarness:
    def __init__(self, record: ObservedLineRecord):
        self.record = record

    def _observed_peak_records(self, _x, _y, limit=24, **_kwargs):
        return [self.record][:limit]

    def _refine_gain_records_on_signed_residual(self, _context, records):
        return list(records)

    @staticmethod
    def _record_position_value(record):
        return float(record.two_theta)


class GainUnknownPeakTests(unittest.TestCase):
    def test_overlap_stage_closes_peak_when_accepted_profile_covers_intensity(self):
        x = np.linspace(18.0, 22.0, 401)
        shape = np.exp(-0.5 * ((x - 20.0) / 0.10) ** 2)
        selected = 94.0 * shape
        residual = 6.0 * shape
        target = selected + residual
        record = ObservedLineRecord(
            two_theta=20.0,
            area=2.0,
            fwhm=0.24,
            height=6.0,
            prominence=6.0,
        )
        context = {
            "x": x,
            "target": target,
            "selected_total": selected,
            "residual_target": residual,
            "difference_curve": residual,
            "selected_peak_positions": np.asarray([20.0]),
            "fwhm": 0.18,
        }

        records = PhaseFinderWindow._compute_gain_stage_records(
            _GainRecordHarness(record), context, "overlap", limit=10
        )

        self.assertEqual(records, [])

    def test_overlap_stage_keeps_peak_when_accepted_profile_underfits_intensity(self):
        x = np.linspace(18.0, 22.0, 401)
        shape = np.exp(-0.5 * ((x - 20.0) / 0.10) ** 2)
        selected = 55.0 * shape
        residual = 45.0 * shape
        target = selected + residual
        record = ObservedLineRecord(
            two_theta=20.0,
            area=11.0,
            fwhm=0.24,
            height=45.0,
            prominence=45.0,
        )
        context = {
            "x": x,
            "target": target,
            "selected_total": selected,
            "residual_target": residual,
            "difference_curve": residual,
            "selected_peak_positions": np.asarray([20.0]),
            "fwhm": 0.18,
        }

        records = PhaseFinderWindow._compute_gain_stage_records(
            _GainRecordHarness(record), context, "overlap", limit=10
        )

        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(records[0].two_theta, 20.0)

    def test_nearby_strong_selected_peak_does_not_hide_local_overlap_deficit(self):
        x = np.linspace(19.4, 20.8, 701)
        selected_shape = np.exp(-0.5 * ((x - 20.0) / 0.055) ** 2)
        unknown_shape = np.exp(-0.5 * ((x - 20.29) / 0.055) ** 2)
        selected = 500.0 * selected_shape
        residual = 55.0 * unknown_shape
        target = selected + residual
        record = ObservedLineRecord(
            two_theta=20.29,
            area=7.5,
            fwhm=0.13,
            height=55.0,
            prominence=55.0,
        )
        context = {
            "x": x,
            "target": target,
            "selected_total": selected,
            "residual_target": residual,
            "difference_curve": residual,
            "selected_peak_positions": np.asarray([20.0]),
            "fwhm": 0.18,
        }

        records = PhaseFinderWindow._compute_gain_stage_records(
            _GainRecordHarness(record), context, "overlap", limit=10
        )

        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(records[0].two_theta, 20.29, places=2)


if __name__ == "__main__":
    unittest.main()
