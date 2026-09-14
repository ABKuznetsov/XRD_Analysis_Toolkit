from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from xrd_finder.finder.models import FinderCandidateInput, FinderInput
from xrd_finder.finder.service import FinderService
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
from xrd_finder.ui.gain_scoring import fit_residual_candidate_scale, profile_residual_gain


class CristmaMatchGainSmokeTests(unittest.TestCase):
    def test_primary_match_and_residual_gain_keep_the_expected_order(self) -> None:
        app_root = Path(__file__).parents[1]
        primary_cif = app_root / "Entry_96-100-0018.cif"
        impurity_cif = app_root / "data" / "cod_cache" / "cif" / "1010437.cif"
        decoy_cif = app_root / "data" / "cod_cache" / "cif" / "1100067.cif"
        profile = InstrumentProfile.default_cu_kalpha()
        x_grid = np.linspace(10.0, 80.0, 3501)
        adapter = CristmaPowderAdapter()

        primary = adapter.calculate_from_cif(
            primary_cif,
            x_grid=x_grid,
            instrument_profile=profile,
            use_lp=True,
        )
        impurity = adapter.calculate_from_cif(
            impurity_cif,
            x_grid=x_grid,
            instrument_profile=profile,
            use_lp=True,
        )
        decoy = adapter.calculate_from_cif(
            decoy_cif,
            x_grid=x_grid,
            instrument_profile=profile,
            use_lp=True,
        )

        result = FinderService().run(
            FinderInput(
                pattern_path="",
                observed_x=x_grid.tolist(),
                observed_y=(5.0 + primary.profile_y).tolist(),
                subtract_background=False,
                snap_peak_positions=False,
                instrument_profile=profile,
                candidates=[
                    FinderCandidateInput(
                        source="TEST",
                        entry_id="primary",
                        name="Primary",
                        cif_path=str(primary_cif),
                    ),
                    FinderCandidateInput(
                        source="TEST",
                        entry_id="decoy",
                        name="Decoy",
                        cif_path=str(decoy_cif),
                    ),
                ],
            )
        )
        scores = {candidate.entry_id: candidate.score for candidate in result.candidates}
        self.assertGreater(scores["primary"], scores["decoy"])

        residual = 0.20 * impurity.profile_y
        residual_area = float(np.trapezoid(residual, x_grid))
        weights = np.ones_like(x_grid)
        selected_total = np.zeros_like(x_grid)
        impurity_scale = fit_residual_candidate_scale(
            target=residual,
            selected_total=selected_total,
            profile=impurity.profile_y,
            weights=weights,
        )
        decoy_scale = fit_residual_candidate_scale(
            target=residual,
            selected_total=selected_total,
            profile=decoy.profile_y,
            weights=weights,
        )
        impurity_gain = profile_residual_gain(
            residual_target=residual,
            calculated=impurity_scale * impurity.profile_y,
            weights=weights,
            residual_area=residual_area,
            before_fit=80.0,
        )
        decoy_gain = profile_residual_gain(
            residual_target=residual,
            calculated=decoy_scale * decoy.profile_y,
            weights=weights,
            residual_area=residual_area,
            before_fit=80.0,
        )

        self.assertGreater(impurity_gain, decoy_gain)


if __name__ == "__main__":
    unittest.main()
