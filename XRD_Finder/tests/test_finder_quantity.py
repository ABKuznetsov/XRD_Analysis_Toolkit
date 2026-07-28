from __future__ import annotations

import unittest

import numpy as np
from xrd_finder.finder.service import FinderService


class FinderQuantityTests(unittest.TestCase):
    def test_mass_fractions_use_scale_times_unit_cell_mass(self) -> None:
        fractions = FinderService._mass_fractions(
            scales=np.asarray([2.0, 1.0]),
            cell_masses=np.asarray([50.0, 100.0]),
        )

        np.testing.assert_allclose(fractions, np.asarray([0.5, 0.5]))
        self.assertAlmostEqual(float(np.sum(fractions)), 1.0)

    def test_mass_fractions_remain_nonnegative(self) -> None:
        fractions = FinderService._mass_fractions(
            scales=np.asarray([-1.0, 2.0]),
            cell_masses=np.asarray([100.0, 25.0]),
        )

        np.testing.assert_allclose(fractions, np.asarray([0.0, 1.0]))


if __name__ == "__main__":
    unittest.main()
