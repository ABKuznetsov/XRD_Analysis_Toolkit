from __future__ import annotations

from types import SimpleNamespace
import math
import unittest

from xrd_finder.services.phase_pattern_equivalence import phase_patterns_equivalent
from xrd_finder.ui.analysis_windows import PhaseFinderWindow


def _peaks(values):
    return [
        SimpleNamespace(two_theta=float(position), intensity=float(intensity))
        for position, intensity in values
    ]


class PhasePatternEquivalenceTests(unittest.TestCase):
    def test_accepts_same_phase_with_different_labels_and_entry_ids(self):
        accepted = _peaks(
            [(20.00, 100), (26.64, 78), (36.54, 42), (39.47, 18), (50.13, 31), (59.96, 14)]
        )
        duplicate = _peaks(
            [(20.04, 82), (26.61, 100), (36.58, 35), (39.43, 25), (50.17, 28), (60.01, 10)]
        )

        self.assertTrue(phase_patterns_equivalent(accepted, duplicate, fwhm=0.18))

    def test_rejects_polymorph_with_same_formula(self):
        accepted = _peaks(
            [(20.00, 100), (26.64, 78), (36.54, 42), (39.47, 18), (50.13, 31), (59.96, 14)]
        )
        polymorph = _peaks(
            [(20.02, 100), (24.20, 70), (31.10, 55), (36.50, 25), (45.30, 32), (56.80, 18)]
        )

        self.assertFalse(phase_patterns_equivalent(accepted, polymorph, fwhm=0.18))

    def test_rejects_pattern_that_only_contains_a_shared_subset(self):
        accepted = _peaks(
            [(20.00, 100), (26.64, 78), (36.54, 42), (39.47, 18), (50.13, 31), (59.96, 14)]
        )
        partial = _peaks(
            [(20.02, 100), (26.62, 75), (36.57, 40), (44.00, 65), (48.00, 55), (57.00, 45)]
        )

        self.assertFalse(phase_patterns_equivalent(accepted, partial, fwhm=0.18))

    def test_sparse_three_line_phase_can_be_recognized(self):
        accepted = _peaks([(22.10, 100), (31.45, 55), (44.92, 28)])
        duplicate = _peaks([(22.13, 70), (31.41, 100), (44.96, 35)])

        self.assertTrue(phase_patterns_equivalent(accepted, duplicate, fwhm=0.20))

    def test_accepts_compositional_variant_with_mutual_strong_line_coverage(self):
        accepted = _peaks(
            [(20.0, 100), (26.0, 80), (32.0, 50), (38.0, 40), (44.0, 30), (50.0, 20)]
        )
        variant = _peaks(
            [(20.03, 100), (26.02, 80), (35.0, 50), (38.02, 40), (44.03, 30), (50.02, 20)]
        )

        self.assertTrue(phase_patterns_equivalent(accepted, variant, fwhm=0.20))

    def test_accepts_same_reflection_positions_when_card_intensities_are_reordered(self):
        positions = [12.4, 15.8, 18.1, 22.7, 26.3, 29.6, 33.2, 37.8, 41.1, 46.5, 52.0, 57.4]
        accepted = _peaks(
            list(zip(positions, [100, 82, 64, 48, 36, 28, 21, 16, 12, 9, 7, 5]))
        )
        duplicate = _peaks(
            list(zip(
                [position + (0.03 if index % 2 else -0.02) for index, position in enumerate(positions)],
                [5, 8, 12, 18, 27, 39, 55, 73, 96, 68, 42, 24],
            ))
        )

        self.assertTrue(phase_patterns_equivalent(accepted, duplicate, fwhm=0.18))

    def test_rejects_related_patterns_with_only_half_the_positions_in_common(self):
        accepted = _peaks(
            [(12.0, 100), (16.0, 80), (20.0, 65), (24.0, 52), (28.0, 40), (32.0, 32),
             (36.0, 26), (40.0, 20), (44.0, 16), (48.0, 12)]
        )
        related = _peaks(
            [(12.02, 90), (16.02, 75), (20.02, 60), (24.02, 45), (28.02, 35),
             (34.0, 70), (38.0, 55), (42.0, 40), (46.0, 30), (50.0, 22)]
        )

        self.assertFalse(phase_patterns_equivalent(accepted, related, fwhm=0.18))

    def test_gain_duplicate_filter_checks_raw_patterns_before_match_adjustments(self):
        raw = _peaks(
            [(15.0, 100), (23.0, 80), (27.0, 65), (30.0, 50), (36.0, 35), (42.0, 20)]
        )
        selected_adjusted = _peaks(
            [(position + 0.8, intensity) for position, intensity in
             [(15.0, 100), (23.0, 80), (27.0, 65), (30.0, 50), (36.0, 35), (42.0, 20)]]
        )
        candidate_adjusted = _peaks(
            [(position - 0.8, intensity) for position, intensity in
             [(15.0, 100), (23.0, 80), (27.0, 65), (30.0, 50), (36.0, 35), (42.0, 20)]]
        )

        class Host:
            @staticmethod
            def _candidate_key(candidate):
                return f"{candidate['Source']}:{candidate['Entry']}"

        candidate = {"Source": "COD", "Entry": "3000120"}
        key = Host._candidate_key(candidate)
        context = {
            "fwhm": 0.18,
            "selected_phase_patterns_raw": [tuple(raw)],
            "selected_phase_patterns": [tuple(selected_adjusted)],
            "_gain_raw_peaks_cache": {key: tuple(raw)},
        }

        self.assertTrue(
            PhaseFinderWindow._candidate_duplicates_selected_phase(
                Host(), candidate, candidate_adjusted, context
            )
        )

    def test_fingerprint_accepts_same_pattern_after_affine_q_change(self):
        q_values = [0.25, 0.35, 0.46, 0.58, 0.69, 0.82, 0.95, 1.08, 1.21, 1.35, 1.50, 1.66]
        intensities = [100, 72, 58, 91, 43, 35, 67, 29, 23, 51, 18, 14]

        def two_theta(q):
            return math.degrees(2.0 * math.asin(q / 2.0))

        accepted = _peaks([(two_theta(q), intensity) for q, intensity in zip(q_values, intensities)])
        shifted = _peaks(
            [
                (two_theta(1.018 * q + 0.012), intensity)
                for q, intensity in zip(q_values, intensities)
            ]
        )

        self.assertTrue(phase_patterns_equivalent(accepted, shifted, fwhm=0.18))


if __name__ == "__main__":
    unittest.main()
