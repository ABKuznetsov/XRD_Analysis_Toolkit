from __future__ import annotations

from dataclasses import FrozenInstanceError
import math
import unittest

from xrd_finder.finder.reference_lines import ReferenceLine, ReferenceLineSet


class IndexedReferenceLinesTests(unittest.TestCase):
    def test_records_are_filtered_sorted_and_fingerprinted_deterministically(self) -> None:
        records = [
            {
                "d": 2.0,
                "two_theta": 45.0,
                "intensity": 25.0,
                "norm_intensity": 0.25,
                "raw_intensity": 40.0,
                "h": 2,
                "k": 0,
                "l": 0,
                "multiplicity": 4,
            },
            {
                "d": 3.0,
                "two_theta": 30.0,
                "intensity": 100.0,
                "norm_intensity": 1.0,
                "raw_intensity": 120.0,
                "h": 1,
                "k": 1,
                "l": 0,
                "multiplicity": 8,
            },
            {"d": math.nan, "two_theta": 20.0, "intensity": 10.0},
            {"d": 1.0, "two_theta": math.inf, "intensity": 10.0},
        ]

        lines = ReferenceLineSet.from_records(
            source="cod",
            entry_id="123",
            derived_version=9,
            provenance="local-phase-cache-v9",
            records=records,
        )

        self.assertEqual(lines.source, "COD")
        self.assertEqual(lines.entry_id, "123")
        self.assertEqual([line.two_theta for line in lines.lines], [30.0, 45.0])
        self.assertEqual(lines.lines[0].hkl, (1, 1, 0))
        self.assertEqual(lines.lines[0].normalized_intensity, 1.0)
        self.assertEqual(lines.lines[0].raw_intensity, 120.0)
        self.assertEqual(lines.lines[0].multiplicity, 8)
        self.assertEqual(
            lines.fingerprint,
            ReferenceLineSet.from_records(
                source="COD",
                entry_id="123",
                derived_version=9,
                provenance="local-phase-cache-v9",
                records=list(reversed(records)),
            ).fingerprint,
        )

    def test_line_and_line_set_are_immutable(self) -> None:
        line = ReferenceLine(
            d=3.0,
            two_theta=30.0,
            intensity=100.0,
            normalized_intensity=1.0,
            raw_intensity=120.0,
            h=1,
            k=1,
            l=0,
            multiplicity=8,
        )
        lines = ReferenceLineSet(
            source="COD",
            entry_id="123",
            derived_version=9,
            provenance="cache",
            lines=(line,),
        )

        with self.assertRaises(FrozenInstanceError):
            line.intensity = 1.0
        with self.assertRaises(FrozenInstanceError):
            lines.entry_id = "456"


if __name__ == "__main__":
    unittest.main()
