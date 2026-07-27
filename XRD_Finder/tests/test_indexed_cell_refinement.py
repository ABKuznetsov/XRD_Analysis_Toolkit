from __future__ import annotations

import unittest

from xrd_finder.core.structure import CellParameters, Structure
from xrd_finder.services.refinement_service import RefinementService


class IndexedCellRefinementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RefinementService()
        self.wavelength = 1.5406
        self.hkls = [
            (1, 0, 0),
            (0, 1, 0),
            (0, 0, 1),
            (1, 1, 0),
            (1, 0, 1),
            (0, 1, 1),
            (1, 1, 1),
            (2, 1, 0),
            (2, 0, 1),
            (1, 2, 1),
            (2, 1, 2),
            (3, 1, 1),
        ]

    def test_all_crystal_system_parameter_constraints(self) -> None:
        cases = [
            ("triclinic", 1, (5.0, 5.8, 6.6, 87.0, 93.0, 104.0), (5.03, 5.76, 6.64, 87.3, 92.7, 104.4)),
            ("monoclinic", 14, (5.1, 6.2, 7.3, 90.0, 106.0, 90.0), (5.14, 6.16, 7.35, 90.0, 106.4, 90.0)),
            ("orthorhombic", 62, (5.2, 6.3, 7.4, 90.0, 90.0, 90.0), (5.24, 6.26, 7.46, 90.0, 90.0, 90.0)),
            ("tetragonal", 113, (7.7, 7.7, 5.05, 90.0, 90.0, 90.0), (7.76, 7.76, 5.12, 90.0, 90.0, 90.0)),
            ("trigonal_hex", 166, (5.0, 5.0, 13.6, 90.0, 90.0, 120.0), (5.04, 5.04, 13.52, 90.0, 90.0, 120.0)),
            ("trigonal_rhombohedral", 166, (5.4, 5.4, 5.4, 88.0, 88.0, 88.0), (5.44, 5.44, 5.44, 88.4, 88.4, 88.4)),
            ("hexagonal", 194, (3.2, 3.2, 5.2, 90.0, 90.0, 120.0), (3.23, 3.23, 5.16, 90.0, 90.0, 120.0)),
            ("cubic", 225, (5.4, 5.4, 5.4, 90.0, 90.0, 90.0), (5.44, 5.44, 5.44, 90.0, 90.0, 90.0)),
        ]
        for name, space_group_number, initial_values, target_values in cases:
            with self.subTest(crystal_system=name):
                initial = self._cell(initial_values)
                target = self._cell(target_values)
                structure = Structure.create(name)
                structure.space_group_number = str(space_group_number)
                structure.cell = initial
                matches = []
                for index, hkl in enumerate(self.hkls):
                    d_spacing = self.service._d_from_hkl(target, hkl)
                    two_theta = self.service._two_theta_from_d(d_spacing, self.wavelength)
                    if two_theta is not None:
                        matches.append((*hkl, two_theta, max(10.0, 100.0 - index * 5.0)))
                result = self.service.fit_indexed_cell(
                    phase_id=name,
                    phase_name=name,
                    structure=structure,
                    wavelength=self.wavelength,
                    indexed_matches=matches,
                )
                self.assertTrue(result.success, result.message)
                for parameter, expected in zip(
                    ("a", "b", "c", "alpha", "beta", "gamma"),
                    target_values,
                ):
                    self.assertAlmostEqual(
                        float(getattr(result.refined_cell, parameter)),
                        float(expected),
                        places=4,
                        msg=f"{name}: {parameter}",
                    )

    def test_missing_tetragonal_axial_match_is_completed_from_strong_observed_peak(self) -> None:
        initial = self._cell((7.6344, 7.6344, 5.0513, 90.0, 90.0, 90.0))
        structure = Structure.create("melilite")
        structure.space_group_number = "113"
        structure.cell = initial

        completed = self.service.complete_direct_indexed_matches(
            structure=structure,
            indexed_matches=[
                (1, 1, 0, 16.28, 5.4),
                (2, 1, 0, 26.02, 10.1),
                (1, 2, 1, 31.58, 100.0),
                (0, 2, 1, 29.36, 18.4),
            ],
            reference_peaks=[
                (1, 1, 0, 16.41, 5.4),
                (0, 0, 1, 17.54, 16.6),
                (2, 1, 0, 26.05, 10.1),
                (1, 2, 1, 31.58, 100.0),
            ],
            observed_peaks=[
                (17.22, 283.0, 0.08),
                (17.85, 587.0, 0.13),
                (18.27, 259.0, 0.08),
            ],
        )

        axial = [match for match in completed if match[:3] == (0, 0, 1)]
        self.assertEqual(len(axial), 1)
        self.assertAlmostEqual(axial[0][3], 17.85, places=2)

    def test_anisotropic_axial_shift_uses_independent_cell_ratios(self) -> None:
        initial = self._cell((9.52, 9.52, 6.85, 90.0, 90.0, 120.0))
        target = self._cell((9.8056, 9.8056, 7.22675, 90.0, 90.0, 120.0))
        structure = Structure.create("anisotropic")
        structure.space_group_number = "194"
        structure.cell = initial
        reference_peaks = []
        observed_peaks = []
        for hkl, intensity in [((1, 0, 0), 70.0), ((2, 0, 0), 100.0), ((0, 0, 4), 80.0)]:
            reference_two_theta = self.service._two_theta_from_d(
                self.service._d_from_hkl(initial, hkl),
                self.wavelength,
            )
            observed_two_theta = self.service._two_theta_from_d(
                self.service._d_from_hkl(target, hkl),
                self.wavelength,
            )
            reference_peaks.append((*hkl, reference_two_theta, intensity))
            observed_peaks.append((observed_two_theta, intensity * 2.0, 0.12))
        observed_peaks.append((53.4, 55.0, 0.10))

        completed = self.service.complete_direct_indexed_matches(
            structure=structure,
            indexed_matches=[],
            reference_peaks=reference_peaks,
            observed_peaks=observed_peaks,
        )
        result = self.service.fit_indexed_cell(
            phase_id="anisotropic",
            phase_name="anisotropic",
            structure=structure,
            wavelength=self.wavelength,
            indexed_matches=completed,
        )

        self.assertTrue(result.success, result.message)
        self.assertAlmostEqual(result.refined_cell.a, target.a, places=3)
        self.assertAlmostEqual(result.refined_cell.c, target.c, places=3)
        self.assertNotAlmostEqual(
            result.refined_cell.a / initial.a,
            result.refined_cell.c / initial.c,
            places=2,
        )

    def test_later_phase_receives_only_unclaimed_experimental_peaks(self) -> None:
        observed = [
            (28.00, 1000.0, 0.12),
            (30.05, 500.0, 0.16),
            (35.20, 250.0, 0.20),
        ]
        available = self.service.unclaimed_observed_peaks(
            observed,
            [(28.04, 0.14)],
        )

        self.assertEqual([round(item[0], 2) for item in available], [30.05, 35.20])

    @staticmethod
    def _cell(values) -> CellParameters:
        return CellParameters(
            a=values[0],
            b=values[1],
            c=values[2],
            alpha=values[3],
            beta=values[4],
            gamma=values[5],
        )


if __name__ == "__main__":
    unittest.main()
