from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from xrd_finder.services.gain_retrieval_channels import (
    RETRIEVAL_CHANNELS,
    geometry_channel,
    rare_line_channel,
    rank_channel_scores,
    strong_residual_channel,
)


class GainRetrievalChannelResultTests(unittest.TestCase):
    def test_rank_filters_invalid_scores_and_assigns_one_based_ranks(self):
        run = rank_channel_scores(
            "strong",
            {
                "phase-b": 2.0,
                "phase-a": 2.0,
                "phase-c": 1.0,
                "zero": 0.0,
                "negative": -1.0,
                "nan": math.nan,
                "inf": math.inf,
            },
            {"phase-a": 3, "phase-b": 2, "phase-c": 1},
            limit=2,
        )

        self.assertEqual(run.channel, "strong")
        self.assertEqual(
            [(hit.phase_id, hit.rank) for hit in run.hits],
            [("phase-a", 1), ("phase-b", 2)],
        )
        self.assertEqual([hit.evidence_count for hit in run.hits], [3, 2])
        self.assertTrue(all(math.isfinite(hit.score) for hit in run.hits))
        self.assertTrue(math.isfinite(run.elapsed_seconds))
        self.assertGreaterEqual(run.elapsed_seconds, 0.0)

    def test_identifiers_are_normalized_and_missing_evidence_is_zero(self):
        run = rank_channel_scores(
            "rare",
            {20: 4.0, 10: 5.0},
            {10: -4},
            limit=10,
        )

        self.assertEqual([hit.phase_id for hit in run.hits], ["10", "20"])
        self.assertEqual([hit.evidence_count for hit in run.hits], [0, 0])
        self.assertTrue(all(hit.channel == "rare" for hit in run.hits))

    def test_empty_or_zero_limit_returns_empty_timed_run(self):
        for scores, limit in (({}, 5), ({"phase": 1.0}, 0)):
            with self.subTest(scores=scores, limit=limit):
                run = rank_channel_scores(
                    "geometry", scores, {}, limit=limit
                )
                self.assertEqual(run.hits, ())
                self.assertTrue(math.isfinite(run.elapsed_seconds))
                self.assertGreaterEqual(run.elapsed_seconds, 0.0)

    def test_stable_channel_names_are_public(self):
        self.assertEqual(
            RETRIEVAL_CHANNELS,
            ("strong", "rare", "geometry", "overlap"),
        )


class StrongAndRareRetrievalChannelTests(unittest.TestCase):
    @staticmethod
    def _line(two_theta, intensity=100.0):
        return SimpleNamespace(two_theta=two_theta, intensity=intensity)

    @staticmethod
    def _residual(
        two_theta,
        *,
        area,
        height,
        snr,
        fwhm=None,
        fit_quality=0.9,
    ):
        values = {
            "two_theta": two_theta,
            "area": area,
            "height": height,
            "prominence": height,
            "local_snr": snr,
            "fit_quality": fit_quality,
        }
        if fwhm is not None:
            values["fwhm"] = fwhm
        return SimpleNamespace(**values)

    def test_strong_channel_prefers_narrow_high_snr_support(self):
        candidates = {
            "narrow": [self._line(20.02)],
            "broad": [self._line(40.03)],
            "missing-width": [self._line(30.01)],
        }
        residual = [
            self._residual(20.0, area=100.0, height=90.0, snr=12.0, fwhm=0.16),
            self._residual(40.0, area=100.0, height=40.0, snr=4.0, fwhm=1.10, fit_quality=0.45),
            self._residual(30.0, area=45.0, height=35.0, snr=5.0),
        ]

        run = strong_residual_channel(candidates, residual, limit=10)

        self.assertEqual(run.hits[0].phase_id, "narrow")
        scores = {hit.phase_id: hit.score for hit in run.hits}
        self.assertGreater(scores["narrow"], scores["broad"])
        self.assertIn("missing-width", scores)
        self.assertEqual(
            {hit.phase_id: hit.evidence_count for hit in run.hits},
            {"narrow": 1, "broad": 1, "missing-width": 1},
        )

    def test_rare_channel_can_rescue_candidate_outside_strong_prefix(self):
        candidates = {
            "common-a": [self._line(20.0)],
            "common-b": [self._line(20.03)],
            "common-c": [self._line(19.98)],
            "rare-phase": [self._line(31.0)],
        }
        residual = [
            self._residual(20.0, area=100.0, height=90.0, snr=12.0, fwhm=0.16),
            self._residual(31.0, area=65.0, height=50.0, snr=8.0, fwhm=0.18),
        ]

        strong = strong_residual_channel(candidates, residual, limit=1)
        rare = rare_line_channel(candidates, residual, limit=2)

        self.assertNotEqual(strong.hits[0].phase_id, "rare-phase")
        self.assertIn("rare-phase", [hit.phase_id for hit in rare.hits])

    def test_noise_only_records_produce_no_strong_or_rare_hits(self):
        candidates = {"phase": [self._line(20.0)]}
        noise = [
            self._residual(20.0, area=200.0, height=100.0, snr=1.4, fwhm=0.18),
            self._residual(30.0, area=150.0, height=80.0, snr=2.2, fwhm=0.20),
        ]

        self.assertEqual(
            strong_residual_channel(candidates, noise, limit=10).hits,
            (),
        )
        self.assertEqual(
            rare_line_channel(candidates, noise, limit=10).hits,
            (),
        )


class GeometryRetrievalChannelTests(unittest.TestCase):
    def test_geometry_channel_wraps_scores_and_one_line_stays_empty(self):
        from xrd_finder.services.residual_geometry import (
            build_residual_geometry_index,
        )

        lines = {
            "phase": [
                SimpleNamespace(two_theta=20.0, intensity=100.0),
                SimpleNamespace(two_theta=25.0, intensity=80.0),
            ]
        }
        index = build_residual_geometry_index(lines)
        two_lines = [
            SimpleNamespace(two_theta=20.3, area=100.0, height=80.0),
            SimpleNamespace(two_theta=25.3, area=80.0, height=70.0),
        ]

        run = geometry_channel(index, two_lines, limit=10)

        self.assertEqual(run.channel, "geometry")
        self.assertEqual(run.hits[0].phase_id, "phase")
        self.assertEqual(
            geometry_channel(index, two_lines[:1], limit=10).hits,
            (),
        )


if __name__ == "__main__":
    unittest.main()
