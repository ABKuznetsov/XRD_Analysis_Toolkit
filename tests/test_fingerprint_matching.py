from __future__ import annotations

from types import SimpleNamespace
import unittest

from xrd_finder.finder.fingerprint_matching import (
    DEFAULT_MATCH_WEIGHTS,
    MatchWeights,
    fingerprint_match_score,
)


def _peaks(lines):
    return [SimpleNamespace(two_theta=position, intensity=intensity) for position, intensity in lines]


class FingerprintMatchingTests(unittest.TestCase):
    def test_explicit_default_weights_preserve_score_and_alignment(self):
        reference = _peaks([(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)])
        observed = [(20.15, 100), (30.15, 82), (40.15, 64), (50.15, 43), (60.15, 25), (72.15, 15)]

        implicit = fingerprint_match_score(reference, observed, wavelength=1.5406)
        explicit = fingerprint_match_score(
            reference,
            observed,
            wavelength=1.5406,
            weights=DEFAULT_MATCH_WEIGHTS,
        )

        self.assertAlmostEqual(implicit.score, explicit.score, places=12)
        self.assertAlmostEqual(implicit.position_scale, explicit.position_scale, places=12)
        self.assertAlmostEqual(implicit.zero_shift, explicit.zero_shift, places=12)
        self.assertEqual(implicit.matched_lines, explicit.matched_lines)

    def test_exposes_four_weight_independent_match_components(self):
        reference = _peaks([(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)])
        observed = [(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)]

        result = fingerprint_match_score(reference, observed, wavelength=1.5406)

        self.assertIsNotNone(result.features)
        self.assertTrue(
            all(
                0.0 <= value <= 1.0
                for value in (
                    result.features.observed_coverage,
                    result.features.reference_coverage,
                    result.features.sufficient_lines,
                    result.features.alignment_seed,
                )
            )
        )

    def test_custom_weights_change_only_score(self):
        reference = _peaks([(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)])
        observed = [
            (20, 100),
            (30, 82),
            (40, 64),
            (50, 43),
            (60, 25),
            (72, 15),
            (25, 95),
            (35, 75),
            (45, 55),
            (55, 35),
        ]

        current = fingerprint_match_score(reference, observed, wavelength=1.5406)
        manuscript = fingerprint_match_score(
            reference,
            observed,
            wavelength=1.5406,
            weights=MatchWeights(0.62, 0.25, 0.08, 0.05),
        )

        self.assertNotAlmostEqual(current.score, manuscript.score, places=6)
        self.assertEqual(current.features, manuscript.features)
        self.assertAlmostEqual(current.position_scale, manuscript.position_scale, places=12)
        self.assertAlmostEqual(current.zero_shift, manuscript.zero_shift, places=12)
        self.assertEqual(current.matched_lines, manuscript.matched_lines)

    def test_rejects_negative_or_non_unit_weights(self):
        with self.assertRaises(ValueError):
            MatchWeights(-0.1, 0.6, 0.3, 0.2)
        with self.assertRaises(ValueError):
            MatchWeights(0.4, 0.4, 0.1, 0.0)

    def test_recovers_small_scale_and_zero_shift_together(self):
        reference = _peaks([(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)])
        observed = [
            (position + (position - 45.0) * 0.004 + 0.42, intensity)
            for position, intensity in [(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)]
        ]

        result = fingerprint_match_score(reference, observed, wavelength=1.5406)

        self.assertGreater(result.score, 80.0)
        self.assertAlmostEqual(result.position_scale, 1.004, delta=0.0031)
        self.assertAlmostEqual(result.zero_shift, 0.42, delta=0.09)

    def test_fixed_global_zero_shift_is_preserved_while_phase_scale_is_refined(self):
        reference = _peaks([(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)])
        observed = [
            SimpleNamespace(
                two_theta=position + (position - 45.0) * 0.006 + 0.30,
                height=intensity,
                area=intensity,
                fwhm=0.34,
            )
            for position, intensity in [(20, 100), (30, 82), (40, 64), (50, 43), (60, 25), (72, 15)]
        ]

        result = fingerprint_match_score(
            reference,
            observed,
            wavelength=1.5406,
            fixed_zero_shift=0.30,
        )

        self.assertAlmostEqual(result.zero_shift, 0.30, places=12)
        self.assertAlmostEqual(result.position_scale, 1.006, delta=0.0031)
        self.assertAlmostEqual(result.profile_fwhm, 0.34, delta=0.03)

    def test_profile_width_is_reestimated_for_each_candidate(self):
        reference = _peaks([(20, 100), (30, 82), (40, 64), (50, 43), (60, 25)])
        narrow = [
            SimpleNamespace(two_theta=position, height=intensity, area=intensity, fwhm=0.10)
            for position, intensity in [(20, 100), (30, 82), (40, 64), (50, 43), (60, 25)]
        ]
        broad = [
            SimpleNamespace(two_theta=position, height=intensity, area=intensity, fwhm=0.48)
            for position, intensity in [(20, 100), (30, 82), (40, 64), (50, 43), (60, 25)]
        ]

        narrow_result = fingerprint_match_score(reference, narrow, wavelength=1.5406)
        broad_result = fingerprint_match_score(reference, broad, wavelength=1.5406)

        self.assertLess(narrow_result.profile_fwhm, broad_result.profile_fwhm)
        self.assertAlmostEqual(narrow_result.profile_fwhm, 0.10, delta=0.02)
        self.assertAlmostEqual(broad_result.profile_fwhm, 0.48, delta=0.03)

    def test_missing_strong_reference_lines_penalize_accidental_hits(self):
        observed = [(20, 100), (30, 80), (40, 60), (50, 45), (60, 30)]
        coherent = _peaks([(20, 100), (30, 80), (40, 60), (50, 45), (60, 30)])
        accidental = _peaks(
            [(20, 100), (30, 80), (40, 60), (24, 95), (35, 85), (46, 75), (56, 65), (68, 55)]
        )

        coherent_score = fingerprint_match_score(coherent, observed, wavelength=1.5406).score
        accidental_score = fingerprint_match_score(accidental, observed, wavelength=1.5406).score

        self.assertGreater(coherent_score, accidental_score + 20.0)

    def test_extra_observed_phase_lines_do_not_hide_a_supported_candidate(self):
        reference = _peaks([(20, 100), (30, 80), (40, 60), (50, 45), (60, 30)])
        observed = [
            (20, 100),
            (30, 80),
            (40, 60),
            (50, 45),
            (60, 30),
            (25, 95),
            (35, 70),
            (45, 55),
            (55, 35),
        ]

        result = fingerprint_match_score(reference, observed, wavelength=1.5406)

        self.assertGreater(result.score, 65.0)

    def test_adaptive_tolerance_uses_observed_peak_width_to_reject_narrow_near_misses(self):
        observed = [
            SimpleNamespace(two_theta=position, height=intensity, area=intensity, fwhm=0.08)
            for position, intensity in [(20, 100), (30, 80), (40, 60), (50, 45), (60, 30)]
        ]
        exact = _peaks([(20, 100), (30, 80), (40, 60), (50, 45), (60, 30)])
        displaced = _peaks([(20.34, 100), (29.66, 80), (40.34, 60), (49.66, 45), (60.34, 30)])

        exact_score = fingerprint_match_score(
            exact,
            observed,
            wavelength=1.5406,
            adaptive_line_tolerance=True,
        ).score
        displaced_score = fingerprint_match_score(
            displaced,
            observed,
            wavelength=1.5406,
            adaptive_line_tolerance=True,
        ).score

        self.assertGreater(exact_score, displaced_score + 20.0)


if __name__ == "__main__":
    unittest.main()
