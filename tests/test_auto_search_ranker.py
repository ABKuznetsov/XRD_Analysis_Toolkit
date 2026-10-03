from __future__ import annotations

from types import SimpleNamespace
import unittest

from xrd_finder.services.auto_search_ranker import _cached_reference_peaks, rank_candidate_rows


class AutoSearchRankerTests(unittest.TestCase):
    def test_refines_fingerprint_priority_candidate_with_scale_and_shift(self):
        shifted = [
            SimpleNamespace(two_theta=position, intensity=intensity)
            for position, intensity in [(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)]
        ]
        observed = [
            (position + (position - 45.0) * 0.004 + 0.42, intensity)
            for position, intensity in [(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)]
        ]

        result = rank_candidate_rows(
            [["COD", "shifted", "A", "Shifted", "", "", "", ""]],
            observed,
            wavelength=1.5406,
            reference_peak_loader=lambda _row: shifted,
        )

        self.assertGreater(float(result.rows[0][5].rstrip("%")), 80.0)

    def test_ranks_scored_prefix_and_preserves_unscored_tail(self):
        rows = [
            ["COD", "1", "A", "First", "", "", "", ""],
            ["USER", "2", "B", "Second", "", "", "", ""],
            ["RRUFF", "3", "C", "Tail", "", "", "", ""],
        ]
        peaks = {
            ("COD", "1"): [
                SimpleNamespace(two_theta=20.0, intensity=100.0),
                SimpleNamespace(two_theta=30.0, intensity=80.0),
                SimpleNamespace(two_theta=40.0, intensity=60.0),
            ],
            ("USER", "2"): [
                SimpleNamespace(two_theta=25.0, intensity=100.0),
                SimpleNamespace(two_theta=35.0, intensity=80.0),
                SimpleNamespace(two_theta=45.0, intensity=60.0),
            ],
        }
        observed = [(25.0, 100.0), (35.0, 80.0), (45.0, 60.0)]

        result = rank_candidate_rows(
            rows,
            observed,
            wavelength=1.5406,
            reference_peak_loader=lambda row: peaks.get((row[0], row[1]), []),
            rank_limit=2,
        )

        self.assertEqual([row[1] for row in result.rows], ["2", "1", "3"])
        self.assertGreater(float(result.rows[0][5].rstrip("%")), 0.0)
        self.assertEqual(result.rows[2][5], "")
        self.assertEqual(result.scored_keys, {("COD", "1"), ("USER", "2")})
        self.assertEqual(result.matched_count, 1)

    def test_reports_text_progress_without_requiring_a_dialog(self):
        messages = []
        rows = [["COD", "1", "A", "First", "", "", "", ""]]

        rank_candidate_rows(
            rows,
            [(20.0, 100.0), (30.0, 80.0), (40.0, 60.0)],
            wavelength=1.5406,
            reference_peak_loader=lambda _row: [],
            progress=lambda message, value, maximum: messages.append((message, value, maximum)),
        )

        self.assertEqual(messages[-1], ("Ranking local candidates", 1, 1))

    def test_default_ranks_entire_sql_shortlist_beyond_first_thousand(self):
        rows = [
            ["COD", str(index), "A", f"Candidate {index}", "", "", "", ""]
            for index in range(1001)
        ]
        matching_peaks = [
            SimpleNamespace(two_theta=25.0, intensity=100.0),
            SimpleNamespace(two_theta=35.0, intensity=80.0),
            SimpleNamespace(two_theta=45.0, intensity=60.0),
        ]

        result = rank_candidate_rows(
            rows,
            [(25.0, 100.0), (35.0, 80.0), (45.0, 60.0)],
            wavelength=1.5406,
            reference_peak_loader=lambda row: matching_peaks if row[1] == "1000" else [],
        )

        self.assertEqual(result.rows[0][1], "1000")
        self.assertGreater(float(result.rows[0][5].rstrip("%")), 0.0)
        self.assertEqual(len(result.scored_keys), 1001)

    def test_cached_normalized_intensities_are_scaled_to_percent(self):
        peaks = _cached_reference_peaks(
            [
                {"two_theta": 20.0, "d": 4.0, "norm_intensity": 1.0},
                {"two_theta": 30.0, "d": 3.0, "norm_intensity": 0.25},
                {"two_theta": 40.0, "d": 2.0, "norm_intensity": 0.05},
            ],
            1.5406,
        )

        self.assertEqual([peak.intensity for peak in peaks], [100.0, 25.0, 5.0])


if __name__ == "__main__":
    unittest.main()
