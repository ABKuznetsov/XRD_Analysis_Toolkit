from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from xrd_finder.services.gain_retrieval_channels import (
    RetrievalChannelRun,
    RetrievalHit,
)
from xrd_finder.services.gain_retrieval_union import (
    GainRetrievalConfig,
    GainRetrievalPool,
    build_gain_retrieval_pool,
)


class GainRetrievalUnionTests(unittest.TestCase):
    def test_each_channel_can_supply_a_unique_candidate(self):
        references = {
            "strong-only": self._lines(10, 20, 30, 40),
            "rare-only": self._lines(11, 23, 36, 49),
            "geometry-only": self._lines(12, 25, 39, 54),
            "overlap-only": self._lines(13, 27, 42, 58),
        }
        runs = tuple(
            self._run(channel, [(phase_id, score)])
            for channel, phase_id, score in (
                ("strong", "strong-only", 1.0e9),
                ("rare", "rare-only", 0.001),
                ("geometry", "geometry-only", 12.0),
                ("overlap", "overlap-only", 0.7),
            )
        )

        pool = build_gain_retrieval_pool(
            runs,
            references,
            accepted_ids=(),
            residual_records=self._records(10, 11, 12, 13),
            config=GainRetrievalConfig(
                channel_limits=(("strong", 1), ("rare", 1), ("geometry", 1), ("overlap", 1)),
                union_limit=8,
                profile_limit=4,
            ),
        )

        self.assertIsInstance(pool, GainRetrievalPool)
        self.assertEqual(set(pool.optional_ids), set(references))
        self.assertEqual(pool.raw_union_count, 4)
        self.assertEqual(pool.collapsed_family_count, 4)

    def test_rank_fusion_is_deterministic_across_score_scales_and_nonfinite_values(self):
        references = {
            "a": self._lines(10, 20, 30, 40),
            "b": self._lines(11, 23, 36, 49),
            "c": self._lines(12, 25, 39, 54),
        }
        runs = (
            self._run("strong", [("b", 1.0e30), ("a", math.nan), ("c", 1.0)]),
            self._run("rare", [("a", 1.0e-30), ("c", 1.0e-40)]),
        )
        config = GainRetrievalConfig(
            channel_limits=(("strong", 3), ("rare", 3)),
            union_limit=3,
            profile_limit=3,
        )

        first = build_gain_retrieval_pool(
            runs,
            references,
            accepted_ids=(),
            residual_records=self._records(10, 11, 12),
            config=config,
        )
        second = build_gain_retrieval_pool(
            runs,
            references,
            accepted_ids=(),
            residual_records=self._records(10, 11, 12),
            config=config,
        )

        self.assertEqual(first.optional_ids, second.optional_ids)
        self.assertEqual(set(first.optional_ids), set(references))

    def test_invalid_and_tied_channel_ranks_are_safe_and_stable(self):
        references = {
            "a": self._lines(10, 20, 30, 40),
            "b": self._lines(11, 23, 36, 49),
        }
        hits = (
            RetrievalHit("b", "strong", 1.0, None, 1),
            RetrievalHit("a", "strong", 1.0, None, 1),
        )
        run = RetrievalChannelRun("strong", hits, 0.0)

        pool = build_gain_retrieval_pool(
            (run,),
            references,
            accepted_ids=(),
            residual_records=self._records(10, 11),
            config=GainRetrievalConfig(
                channel_limits=(("strong", 2),), union_limit=2, profile_limit=2
            ),
        )

        self.assertEqual(set(pool.optional_ids), {"a", "b"})

    def test_union_and_profile_limits_are_enforced(self):
        references = {
            f"p{index:02d}": self._lines(10 + index, 40 + index, 75 + index)
            for index in range(40)
        }
        runs = (
            self._run("strong", [(key, 100 - index) for index, key in enumerate(references)]),
            self._run("rare", [(key, 100 - index) for index, key in enumerate(reversed(references))]),
        )
        pool = build_gain_retrieval_pool(
            runs,
            references,
            accepted_ids=(),
            residual_records=self._records(15, 25, 35),
            config=GainRetrievalConfig(
                channel_limits=(("strong", 30), ("rare", 30)),
                union_limit=32,
                profile_limit=24,
            ),
        )

        self.assertLessEqual(pool.raw_union_count, 32)
        self.assertEqual(len(pool.optional_ids), 24)

    def test_equivalent_cards_share_one_slot_and_accepted_family_is_excluded(self):
        references = {
            "accepted": self._lines(12.0, 20.0, 31.0, 47.0, 63.0),
            "accepted-other-source": self._lines(12.03, 19.98, 31.02, 46.98, 63.02),
            "duplicate-z": self._lines(15.0, 27.0, 42.0, 58.0, 77.0),
            "duplicate-a": self._lines(15.02, 26.98, 42.01, 58.02, 76.98),
            "other": self._lines(17.0, 30.0, 49.0, 69.0, 88.0),
        }
        runs = (
            self._run(
                "strong",
                [
                    ("accepted-other-source", 100),
                    ("duplicate-z", 90),
                    ("duplicate-a", 80),
                    ("other", 70),
                ],
            ),
        )

        pool = build_gain_retrieval_pool(
            runs,
            references,
            accepted_ids=("accepted",),
            residual_records=self._records(15, 27, 42, 58),
            config=GainRetrievalConfig(
                channel_limits=(("strong", 8),), union_limit=8, profile_limit=8
            ),
        )

        self.assertNotIn("accepted-other-source", pool.optional_ids)
        duplicate_count = sum(
            phase_id in {"duplicate-z", "duplicate-a"}
            for phase_id in pool.optional_ids
        )
        self.assertEqual(duplicate_count, 1)
        assignments = dict(pool.family_assignments)
        self.assertEqual(assignments["accepted"], assignments["accepted-other-source"])
        self.assertEqual(assignments["duplicate-z"], assignments["duplicate-a"])

    def test_missing_strong_line_is_soft_and_overlap_or_weak_lines_are_exempt(self):
        references = {
            "complete": self._weighted_lines((20, 100), (30, 100)),
            "missing": self._weighted_lines((20, 100), (45, 100)),
            "overlap-exempt": self._weighted_lines((20, 100), (50, 100)),
            "weak-exempt": self._weighted_lines((20, 100), (60, 8)),
        }
        runs = (
            self._run(
                "strong",
                [("missing", 10), ("overlap-exempt", 9), ("weak-exempt", 8), ("complete", 7)],
            ),
        )
        pool = build_gain_retrieval_pool(
            runs,
            references,
            accepted_ids=(),
            residual_records=self._records(20, 30),
            overlap_positions=(50.0,),
            config=GainRetrievalConfig(
                channel_limits=(("strong", 8),),
                union_limit=8,
                profile_limit=4,
                missing_line_weight=0.5,
            ),
        )

        self.assertEqual(set(pool.optional_ids), set(references))
        self.assertLess(pool.optional_ids.index("complete"), pool.optional_ids.index("missing"))
        self.assertLess(pool.optional_ids.index("overlap-exempt"), pool.optional_ids.index("missing"))
        self.assertLess(pool.optional_ids.index("weak-exempt"), pool.optional_ids.index("missing"))

    def test_line_level_compression_uses_d_spacing_across_xray_tubes(self):
        copper = 1.5406
        cobalt = 1.7890
        correct_d = (4.437, 2.976, 2.014)
        references = {
            "wrong": self._d_lines((4.10, 2.70, 1.85), copper),
            "correct": self._d_lines(correct_d, copper),
        }
        cobalt_positions = tuple(
            math.degrees(2.0 * math.asin(cobalt / (2.0 * d_spacing)))
            for d_spacing in correct_d
        )
        runs = (self._run("geometry", [("wrong", 1.0), ("correct", 1.0)]),)

        pool = build_gain_retrieval_pool(
            runs,
            references,
            accepted_ids=(),
            residual_records=self._records(*cobalt_positions),
            config=GainRetrievalConfig(
                channel_limits=(("geometry", 2),),
                union_limit=2,
                profile_limit=1,
            ),
            wavelength=cobalt,
        )

        self.assertEqual(pool.optional_ids, ("correct",))

    @staticmethod
    def _run(channel, phase_scores):
        hits = tuple(
            RetrievalHit(
                phase_id=phase_id,
                channel=channel,
                score=float(score),
                rank=index,
                evidence_count=1,
            )
            for index, (phase_id, score) in enumerate(phase_scores, start=1)
        )
        return RetrievalChannelRun(channel=channel, hits=hits, elapsed_seconds=0.001)

    @staticmethod
    def _lines(*positions):
        return tuple(
            SimpleNamespace(two_theta=float(position), intensity=float(100 - index * 10))
            for index, position in enumerate(positions)
        )

    @staticmethod
    def _weighted_lines(*values):
        return tuple(
            SimpleNamespace(two_theta=float(position), intensity=float(intensity))
            for position, intensity in values
        )

    @staticmethod
    def _d_lines(d_spacings, wavelength):
        return tuple(
            SimpleNamespace(
                d=float(d_spacing),
                two_theta=math.degrees(
                    2.0 * math.asin(float(wavelength) / (2.0 * float(d_spacing)))
                ),
                intensity=float(100 - index * 10),
            )
            for index, d_spacing in enumerate(d_spacings)
        )

    @staticmethod
    def _records(*positions):
        return tuple(
            SimpleNamespace(
                two_theta=float(position),
                area=100.0,
                height=100.0,
                prominence=100.0,
                fwhm=0.18,
                local_snr=10.0,
            )
            for position in positions
        )


if __name__ == "__main__":
    unittest.main()
