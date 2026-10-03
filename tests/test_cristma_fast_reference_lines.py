from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter


P1_CIF = """
data_simple
_chemical_formula_sum 'Si'
_space_group_IT_number 1
_symmetry_space_group_name_H-M 'P 1'
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0 0 0 1
"""


class CristmaFastReferenceLineTests(unittest.TestCase):
    def test_fast_reference_sticks_match_full_powder_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simple.cif"
            path.write_text(P1_CIF, encoding="utf-8")
            adapter = CristmaPowderAdapter()
            profile = InstrumentProfile.default_cu_kalpha()

            fast = adapter.reference_sticks_from_cif(
                path,
                two_theta_min=10.0,
                two_theta_max=80.0,
                instrument_profile=profile,
                use_lp=True,
            )
            full = adapter.lines_from_cif(
                path,
                two_theta_min=10.0,
                two_theta_max=80.0,
                instrument_profile=profile,
                use_lp=True,
            ).peaks

            self.assertGreater(len(fast), 0)
            self.assertEqual(len(fast), len(full))
            ordered_fast = sorted(fast, key=lambda peak: (peak.two_theta, peak.raw_intensity))
            ordered_full = sorted(full, key=lambda peak: (peak.two_theta, peak.raw_intensity))
            for fast_peak, full_peak in zip(ordered_fast, ordered_full, strict=True):
                self.assertAlmostEqual(fast_peak.d, full_peak.d, places=12)
                self.assertAlmostEqual(fast_peak.two_theta, full_peak.two_theta, places=12)
                self.assertAlmostEqual(fast_peak.intensity, full_peak.intensity, places=10)
                self.assertAlmostEqual(fast_peak.raw_intensity, full_peak.raw_intensity, places=8)
                self.assertAlmostEqual(fast_peak.lp, full_peak.lp, places=12)

    def test_sticks_prefer_fast_reference_calculation(self) -> None:
        adapter = CristmaPowderAdapter()
        sentinel = (object(),)
        adapter.reference_sticks_from_cif = lambda *_args, **_kwargs: sentinel

        observed = adapter.sticks_from_cif(
            "unused.cif",
            two_theta_min=10.0,
            two_theta_max=80.0,
            instrument_profile=InstrumentProfile.default_cu_kalpha(),
            use_lp=False,
        )

        self.assertIs(observed, sentinel)

    def test_sticks_fall_back_to_full_calculation_when_fast_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simple.cif"
            path.write_text(P1_CIF, encoding="utf-8")
            adapter = CristmaPowderAdapter()
            profile = InstrumentProfile.default_cu_kalpha()
            expected = adapter.lines_from_cif(
                path,
                two_theta_min=10.0,
                two_theta_max=80.0,
                instrument_profile=profile,
                use_lp=False,
            ).peaks

            def fail(*_args, **_kwargs):
                raise RuntimeError("fast calculation failed")

            adapter.reference_sticks_from_cif = fail
            observed = adapter.sticks_from_cif(
                path,
                two_theta_min=10.0,
                two_theta_max=80.0,
                instrument_profile=profile,
                use_lp=False,
            )

            self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()
