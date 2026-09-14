from __future__ import annotations

from pathlib import Path
import unittest

from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.diffraction_backend_comparison import compare_cif_backends


class DiffractionBackendComparisonTests(unittest.TestCase):
    def test_real_cif_produces_finite_and_positionally_consistent_results(self) -> None:
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"

        result = compare_cif_backends(
            cif_path,
            instrument_profile=InstrumentProfile.default_cu_kalpha(),
            two_theta_min=10.0,
            two_theta_max=80.0,
            grid_points=3501,
            strongest_lines=20,
            position_tolerance_deg=0.15,
        )

        self.assertTrue(result.legacy_profile_finite)
        self.assertTrue(result.cristma_profile_finite)
        self.assertGreater(result.legacy_line_count, 10)
        self.assertGreater(result.cristma_line_count, 10)
        self.assertGreaterEqual(result.strong_line_match_fraction, 0.70)
        self.assertLessEqual(result.median_position_delta_deg, 0.08)


if __name__ == "__main__":
    unittest.main()
