from __future__ import annotations

import unittest
from pathlib import Path

from xrd_finder.finder.reference_lines import ReferenceLine, ReferenceLineSet
from xrd_finder.ui.candidate_line_provider import CandidateLineResolution, LineSetStatus
from xrd_finder.ui.match_profile_renderer import build_finder_candidate_inputs


def _ready_lines(entry_id: str) -> ReferenceLineSet:
    return ReferenceLineSet(
        source="COD",
        entry_id=entry_id,
        derived_version=7,
        provenance="test",
        lines=(ReferenceLine(2.0, 45.0, 100.0, 100.0, 100.0, 1, 0, 0, 2),),
    )


class IndexedCandidateUiAdapterTests(unittest.TestCase):
    def _build(self, candidates, resolver, path_resolver):
        return build_finder_candidate_inputs(
            candidates,
            path_resolver,
            lambda row: f"{row['Source']}:{row['Entry']}",
            lambda row: row.get("Phase", ""),
            lambda row: row.get("Source", ""),
            line_resolver=resolver,
        )

    def test_ready_indexed_candidate_does_not_request_a_cif_path(self) -> None:
        candidate = {"Source": "COD", "Entry": "100", "Phase": "Alpha", "Formula": "A"}

        result = self._build(
            [candidate],
            lambda _row: CandidateLineResolution(LineSetStatus.READY, _ready_lines("100")),
            lambda _row: (_ for _ in ()).throw(AssertionError("CIF path requested")),
        )

        self.assertEqual(len(result.ready), 1)
        self.assertIsNotNone(result.ready[0].reference_lines)
        self.assertEqual(result.ready[0].cif_path, "")
        self.assertEqual(result.candidate_by_key["COD:100"], candidate)
        self.assertEqual(result.needs_index, [])

    def test_obsolete_structural_candidate_is_reported_for_indexing(self) -> None:
        candidate = {"Source": "COD", "Entry": "101", "Phase": "Beta"}

        result = self._build(
            [candidate],
            lambda _row: CandidateLineResolution(LineSetStatus.OBSOLETE, needs_index=True),
            lambda _row: (_ for _ in ()).throw(AssertionError("CIF path requested")),
        )

        self.assertEqual(result.ready, [])
        self.assertEqual(result.needs_index, [candidate])

    def test_user_candidate_retains_local_cif_compatibility_path(self) -> None:
        candidate = {"Source": "USER", "Entry": "local", "Phase": "Local"}

        result = self._build(
            [candidate],
            lambda _row: CandidateLineResolution(LineSetStatus.MISSING, needs_index=True),
            lambda _row: Path("/tmp/local.cif"),
        )

        self.assertEqual(len(result.ready), 1)
        self.assertEqual(result.ready[0].cif_path, "/tmp/local.cif")
        self.assertEqual(result.needs_index, [])


if __name__ == "__main__":
    unittest.main()
