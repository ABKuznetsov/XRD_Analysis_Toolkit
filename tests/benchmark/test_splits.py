from __future__ import annotations

import unittest

from benchmarks.match.splits import PhaseDescriptor, assign_split_families


class SplitTests(unittest.TestCase):
    def test_family_members_never_cross_splits_and_seed_is_stable(self):
        phases = [
            PhaseDescriptor(f"phase-{index}", f"family-{index // 2}", "organic" if index % 7 == 0 else "inorganic")
            for index in range(30)
        ]

        first = assign_split_families(phases, seed=5036)
        second = assign_split_families(phases, seed=5036)

        self.assertEqual(first, second)
        by_family: dict[str, set[str]] = {}
        for assignment in first:
            by_family.setdefault(assignment.family_id, set()).add(assignment.split)
        self.assertTrue(all(len(splits) == 1 for splits in by_family.values()))
        self.assertEqual({assignment.split for assignment in first}, {"train", "validation", "test"})


if __name__ == "__main__":
    unittest.main()
