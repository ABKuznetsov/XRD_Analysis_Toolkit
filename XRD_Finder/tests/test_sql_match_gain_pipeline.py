from __future__ import annotations

from types import SimpleNamespace
import sys
import unittest

import numpy as np

# The focused scoring tests do not exercise signed project summaries. Keep the
# UI module import independent of that optional runtime package.
sys.modules.setdefault(
    "rfc8785",
    SimpleNamespace(
        CanonicalizationError=ValueError,
        dumps=lambda value: repr(value).encode("utf-8"),
    ),
)

from xrd_finder.services.calculated_pattern_service import HKLPeak
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.gain_scoring import profile_residual_gain


def _peak(two_theta: float, intensity: float, h: int) -> HKLPeak:
    return HKLPeak(
        h=h,
        k=0,
        l=0,
        d=1.0,
        two_theta=two_theta,
        intensity=intensity,
        multiplicity=1,
        raw_intensity=intensity,
    )


class _SqlMatchHarness:
    def __init__(self) -> None:
        self._candidate_probability_cache = {}
        self.indexed_calls: list[str] = []
        self.peaks = {
            "dominant": [
                _peak(25.0, 55.0, 1),
                _peak(30.0, 100.0, 2),
                _peak(36.0, 75.0, 3),
                _peak(43.0, 45.0, 4),
                _peak(51.0, 30.0, 5),
            ],
            "false": [
                _peak(20.0, 100.0, 1),
                _peak(27.5, 95.0, 2),
                _peak(39.0, 90.0, 3),
                _peak(48.0, 85.0, 4),
                _peak(58.0, 80.0, 5),
            ],
        }

    @staticmethod
    def _candidate_source(candidate) -> str:
        return candidate["Source"]

    def _candidate_indexed_peaks(self, candidate):
        entry_id = candidate["Entry"]
        self.indexed_calls.append(entry_id)
        return self.peaks[entry_id]

    @staticmethod
    def _pdf2_peaks_for_candidate(_candidate):
        raise AssertionError("PDF-2 path was used for a COD candidate")

    @staticmethod
    def _candidate_cached_json_peaks(_candidate):
        raise AssertionError("peaks_json compatibility path was used")

    @staticmethod
    def _candidate_local_cif_path(_candidate):
        raise AssertionError("CIF compatibility path was used")

    @staticmethod
    def _candidate_probability_key(candidate, _cif_path):
        return (candidate["Source"], candidate["Entry"])

    @staticmethod
    def _candidate_lightweight_structure(_candidate):
        return SimpleNamespace()

    @staticmethod
    def _active_wavelength() -> float:
        return 1.5406

    @staticmethod
    def _trim_candidate_probability_cache() -> None:
        return None


class _SqlGainHarness:
    def __init__(self) -> None:
        self.indexed_calls = 0

    @staticmethod
    def _candidate_source(candidate) -> str:
        return candidate["Source"]

    def _candidate_peaks_for_gain(self, _candidate):
        self.indexed_calls += 1
        return [_peak(34.0, 100.0, 1), _peak(46.0, 60.0, 2)]

    @staticmethod
    def _candidate_cached_json_peaks(_candidate):
        raise AssertionError("peaks_json compatibility path was used")

    @staticmethod
    def _candidate_cif_peaks_for_gain(_candidate):
        raise AssertionError("CIF compatibility path was used")

    @staticmethod
    def _aligned_candidate_gain_peaks(_candidate, peaks, _context):
        return peaks

    @staticmethod
    def _candidate_residual_line_gain(_peaks, _context) -> float:
        return 14.0

    @staticmethod
    def _candidate_gain_profile(_candidate, _peaks, _context):
        return None


class _RankingHarness:
    _rank_candidate_rows_by_peak_probability = (
        PhaseFinderWindow._rank_candidate_rows_by_peak_probability
    )
    _percent_text_value = PhaseFinderWindow._percent_text_value

    def __init__(self) -> None:
        self.match_candidates = []
        self._candidate_hidden_match_by_key = {}
        self.scoring_status_label = None
        self._gain_overlap_locked = False
        self._active_gain_stage = ""
        self._last_gain_debug = ""

    @staticmethod
    def _rank_by_peak_probability_enabled() -> bool:
        return True

    @staticmethod
    def _probability_observed_data():
        values = np.asarray([25.0, 30.0, 36.0], dtype=float)
        return values, values, [(25.0, 50.0), (30.0, 100.0), (36.0, 70.0)]

    @staticmethod
    def _candidate_key(candidate) -> str:
        return f"{candidate.get('Source', '')}:{candidate.get('Entry', '')}"

    @staticmethod
    def _candidate_row_peak_probability_from_records(row, _records, **_kwargs) -> float:
        return {"dominant": 82.0, "impurity": 54.0, "false": 31.0}[row[1]]

    @staticmethod
    def _gain_observed_records(_context, *, limit):
        del limit
        return [(34.0, 20.0), (46.0, 12.0)]

    @staticmethod
    def _gain_stage_for_context(_context) -> str:
        return "direct"

    @staticmethod
    def _candidate_row_integral_gain(row, _context) -> float:
        return {"dominant": 0.0, "impurity": 18.0, "false": 2.0}[row[1]]


class SqlMatchGainPipelineTests(unittest.TestCase):
    def test_match_uses_current_sql_lines_and_penalizes_unmatched_sticks(self) -> None:
        harness = _SqlMatchHarness()
        records = [
            (25.02, 50.0),
            (30.01, 100.0),
            (36.03, 72.0),
            (43.01, 42.0),
            (51.02, 28.0),
        ]

        dominant = PhaseFinderWindow._candidate_row_peak_probability_from_records(
            harness,
            ["COD", "dominant", "A", "Dominant", "", "", ""],
            records,
            allow_cif_fallback=False,
        )
        false = PhaseFinderWindow._candidate_row_peak_probability_from_records(
            harness,
            ["COD", "false", "B", "False", "", "", ""],
            records,
            allow_cif_fallback=False,
        )

        self.assertEqual(harness.indexed_calls, ["dominant", "false"])
        self.assertGreater(dominant, false)
        self.assertLessEqual(false, 28.0)

    def test_gain_uses_the_same_indexed_candidate_line_path(self) -> None:
        harness = _SqlGainHarness()

        gain = PhaseFinderWindow._candidate_row_integral_gain(
            harness,
            ["COD", "impurity", "B", "Impurity", "", "", ""],
            {"gain_stage": "direct"},
        )

        self.assertEqual(gain, 14.0)
        self.assertEqual(harness.indexed_calls, 1)

    def test_residual_gain_rewards_complementary_phase_over_false_lines(self) -> None:
        x = np.linspace(20.0, 60.0, 4001)
        residual = (
            8.0 * np.exp(-0.5 * ((x - 34.0) / 0.10) ** 2)
            + 5.0 * np.exp(-0.5 * ((x - 46.0) / 0.12) ** 2)
        )
        false = (
            12.0 * np.exp(-0.5 * ((x - 28.0) / 0.10) ** 2)
            + 10.0 * np.exp(-0.5 * ((x - 52.0) / 0.12) ** 2)
        )
        weights = np.ones_like(x)
        residual_area = float(np.trapezoid(residual, x))

        complementary_gain = profile_residual_gain(
            residual_target=residual,
            calculated=residual,
            weights=weights,
            residual_area=residual_area,
            before_fit=70.0,
        )
        false_gain = profile_residual_gain(
            residual_target=residual,
            calculated=false,
            weights=weights,
            residual_area=residual_area,
            before_fit=70.0,
        )

        self.assertGreater(complementary_gain, false_gain)
        self.assertLess(false_gain, 1.0e-9)

    def test_ranking_switches_from_match_to_gain_after_phase_selection(self) -> None:
        harness = _RankingHarness()
        rows = [
            ["COD", "false", "F", "False", "", "", "", ""],
            ["COD", "impurity", "I", "Impurity", "", "", "", ""],
            ["COD", "dominant", "D", "Dominant", "", "", "", ""],
        ]

        match_ranked = harness._rank_candidate_rows_by_peak_probability(rows, force=True)

        self.assertEqual(match_ranked[0][1], "dominant")
        self.assertEqual(match_ranked[0][5], "82%")

        harness.match_candidates = [{"Source": "COD", "Entry": "dominant"}]
        gain_ranked = harness._rank_candidate_rows_by_peak_probability(
            match_ranked,
            force=True,
            gain_context={"residual_share": 0.30, "before_fit": 65.0},
        )

        self.assertEqual(gain_ranked[0][1], "impurity")
        self.assertEqual(gain_ranked[0][6], "18%")
        self.assertEqual(gain_ranked[0][5], "")


if __name__ == "__main__":
    unittest.main()
