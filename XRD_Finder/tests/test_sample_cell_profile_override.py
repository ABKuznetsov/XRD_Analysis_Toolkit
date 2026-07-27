from __future__ import annotations

import unittest

from xrd_finder.core.structure import CellParameters, Structure
from xrd_finder.finder.models import FinderCandidateInput, candidate_structure_override


class SampleCellProfileOverrideTests(unittest.TestCase):
    def test_refined_sample_structure_wins_over_reference_cif(self) -> None:
        candidate = FinderCandidateInput(
            cif_path="9008195.cif",
            entry_id="COD:9008195",
            source="COD",
        )
        sample_structure = Structure.create("Melilite")
        sample_structure.cell = CellParameters(
            a=7.6402,
            b=7.6402,
            c=5.0414,
            alpha=90.0,
            beta=90.0,
            gamma=90.0,
        )

        resolved = candidate_structure_override(
            candidate,
            {"COD:9008195": sample_structure},
        )

        self.assertIs(resolved, sample_structure)


if __name__ == "__main__":
    unittest.main()
