from __future__ import annotations

import unittest

from benchmarks.match.joint_gain_sensitivity import (
    JointGainSensitivityRow,
    calculate_stability_metrics,
    joint_gain_parameter_grid,
    select_validation_config,
)


class JointGainSensitivityTests(unittest.TestCase):
    def test_parameter_grid_covers_requested_design_without_test_selection(self):
        grid = joint_gain_parameter_grid()

        self.assertEqual(len(grid), 64)
        self.assertEqual({item.derivative_weight for item in grid}, {0.0, 0.05, 0.10, 0.20})
        self.assertEqual({item.complexity_penalty for item in grid}, {0.0, 0.001, 0.003, 0.01})
        self.assertEqual({item.excess_penalty for item in grid}, {1.0, 2.0, 3.0, 5.0})

    def test_selection_uses_validation_full_set_then_top5_false_positives_and_time(self):
        grid = joint_gain_parameter_grid()
        fast = grid[0]
        accurate = grid[-1]
        rows = (
            self._row("validation", "v1", fast, full=False, rank=1, false=0, seconds=0.1),
            self._row("validation", "v2", fast, full=False, rank=1, false=0, seconds=0.1),
            self._row("validation", "v1", accurate, full=True, rank=3, false=1, seconds=0.3),
            self._row("validation", "v2", accurate, full=True, rank=4, false=1, seconds=0.3),
            self._row("test", "t1", fast, full=True, rank=1, false=0, seconds=0.01),
        )

        selected = select_validation_config(rows)

        self.assertEqual(selected, accurate)

    def test_stability_reports_order_card_jaccard_and_suppression(self):
        config = joint_gain_parameter_grid()[0]
        rows = (
            self._row("test", "order-a", config, rank=2, families=("a", "target", "b"), group="order", kind="accepted-order", suppressed=1),
            self._row("test", "order-b", config, rank=3, families=("target", "a", "c"), group="order", kind="accepted-order", suppressed=2),
            self._row("test", "card-a", config, rank=1, families=("target", "a"), group="card", kind="card-variant", suppressed=1),
            self._row("test", "card-b", config, rank=4, families=("a", "target"), group="card", kind="card-variant", suppressed=0),
        )

        metrics = calculate_stability_metrics(rows)

        self.assertEqual(metrics.order_top5_retention, 1.0)
        self.assertEqual(metrics.card_variant_rank_delta, 3.0)
        self.assertAlmostEqual(metrics.top5_jaccard, 0.5)
        self.assertEqual(metrics.suppressed_candidate_count, 4)

    @staticmethod
    def _row(
        split,
        case_id,
        config,
        *,
        full=True,
        rank=1,
        false=0,
        seconds=0.2,
        families=("target",),
        group="",
        kind="",
        suppressed=0,
    ):
        return JointGainSensitivityRow(
            split=split,
            case_id=case_id,
            variant_group=group,
            variant_kind=kind,
            config=config,
            target_rank=rank,
            ranked_families=tuple(families),
            full_set_recovered=full,
            false_positive_families=false,
            search_seconds=seconds,
            suppressed_candidate_count=suppressed,
        )


if __name__ == "__main__":
    unittest.main()
