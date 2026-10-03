from __future__ import annotations

import unittest

from xrd_finder.services.geometric_fingerprint import (
    expanded_geometric_hashes_from_q,
    geometric_hashes_from_q,
    rank_fingerprint_candidates,
)


class GeometricFingerprintTests(unittest.TestCase):
    def test_shape_hash_is_invariant_to_affine_q_transform(self):
        q = [1.0, 1.6, 2.5, 3.7, 5.2, 7.0, 9.1]
        transformed = [1.017 * value + 0.23 for value in q]

        self.assertEqual(
            geometric_hashes_from_q(q),
            geometric_hashes_from_q(transformed),
        )

    def test_expanded_query_tolerates_neighboring_quantization_bins(self):
        candidate = geometric_hashes_from_q([1.0, 1.6, 2.5, 3.7, 5.2, 7.0])
        perturbed = expanded_geometric_hashes_from_q(
            [1.0, 1.603, 2.494, 3.705, 5.2, 7.0]
        )

        self.assertTrue(candidate.intersection(perturbed))

    def test_candidate_with_coherent_geometry_outranks_distractor(self):
        query = expanded_geometric_hashes_from_q(
            [1.0, 1.6, 2.5, 3.7, 5.2, 7.0, 9.1]
        )
        candidates = {
            ("COD", "target"): geometric_hashes_from_q(
                [1.2, 1.8, 2.7, 3.9, 5.4, 7.2, 9.3]
            ),
            ("COD", "distractor"): geometric_hashes_from_q(
                [1.0, 1.2, 1.9, 3.1, 5.8, 8.9, 13.0]
            ),
        }

        ranked = rank_fingerprint_candidates(query, candidates)

        self.assertEqual(ranked[0].key, ("COD", "target"))
        self.assertGreater(ranked[0].votes, ranked[1].votes)


if __name__ == "__main__":
    unittest.main()
