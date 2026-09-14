from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
from cristma.diffraction import RadiationSpectrum

from xrd_finder.core.structure import CellParameters
from xrd_finder.instrument.models import (
    InstrumentProfile,
    RadiationProfile,
    ResolutionProfile,
)
from xrd_finder.instrument.radiation_catalog import radiation_profile_from_tube
from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.line_calculator import CachedLineCalculator
from xrd_finder.finder.models import FinderCandidateInput, FinderInput
from xrd_finder.finder.profile_calculator import CachedProfileCalculator
from xrd_finder.finder.service import FinderService
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter


class CristmaPowderAdapterTests(unittest.TestCase):
    def test_uses_packaged_cristma_tube_spectrum(self) -> None:
        profile = InstrumentProfile(
            radiation=radiation_profile_from_tube("Mo"),
            profile_id="mo-lab",
        )

        radiation = CristmaPowderAdapter.radiation_from_profile(profile)

        self.assertEqual(radiation.source_id, "xray-tube:mo-ka")
        self.assertEqual(len(radiation.components), 2)

    def test_uses_cristma_synchrotron_spectrum_for_custom_monochromatic(self) -> None:
        profile = InstrumentProfile(
            radiation=RadiationProfile.custom_monochromatic(
                0.41328,
                label="Beamline wavelength",
            ),
            profile_id="synchrotron",
        )

        radiation = CristmaPowderAdapter.radiation_from_profile(profile)

        self.assertEqual(len(radiation.components), 1)
        self.assertEqual(radiation.provenance.source, "user_supplied_synchrotron_wavelength")
        self.assertAlmostEqual(radiation.components[0].wavelength_angstrom, 0.41328)

    def test_maps_finder_radiation_and_tch_profile(self) -> None:
        base = InstrumentProfile.default_cu_kalpha()
        profile = InstrumentProfile(
            identity=base.identity,
            radiation=RadiationProfile(
                target="Cu",
                mode="kalpha1_only",
                components=base.radiation.components,
            ),
            geometry=base.geometry,
            detector=base.detector,
            resolution=ResolutionProfile.tch(u=1.0, v=-0.2, w=1.44, x=0.5, y=0.1),
            profile_id="test-tch",
        )

        radiation = CristmaPowderAdapter.radiation_from_profile(profile)
        resolution = CristmaPowderAdapter.resolution_from_profile(profile)

        self.assertEqual(len(radiation.components), 1)
        self.assertAlmostEqual(
            radiation.components[0].wavelength_angstrom,
            RadiationSpectrum.lab_k_alpha("Cu").components[0].wavelength_angstrom,
        )
        self.assertEqual(resolution.__class__.__name__, "TchProfile")
        self.assertAlmostEqual(resolution.w, 1.44)

    def test_calculates_profile_and_sticks_from_real_cif(self) -> None:
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"
        x_grid = np.linspace(10.0, 80.0, 3501)

        result = CristmaPowderAdapter().calculate_from_cif(
            cif_path,
            x_grid=x_grid,
            instrument_profile=InstrumentProfile.default_cu_kalpha(),
            use_lp=True,
        )

        self.assertEqual(result.backend, "cristma")
        self.assertEqual(len(result.profile_x), len(x_grid))
        self.assertEqual(len(result.profile_y), len(x_grid))
        self.assertGreater(len(result.peaks), 10)
        self.assertAlmostEqual(float(np.max(result.profile_y)), 100.0)
        self.assertTrue(all(10.0 <= peak.two_theta <= 80.0 for peak in result.peaks))

    def test_reprofiles_cached_lines_with_d_spacing_scale_and_zero_shift(self) -> None:
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"
        x_grid = np.linspace(10.0, 80.0, 3501)
        profile = InstrumentProfile.default_cu_kalpha()
        adapter = CristmaPowderAdapter()

        lines = adapter.lines_from_cif(
            cif_path,
            two_theta_min=10.0,
            two_theta_max=80.0,
            instrument_profile=profile,
            use_lp=True,
        )
        baseline = adapter.profile_from_lines(
            lines,
            x_grid=x_grid,
            instrument_profile=profile,
        )
        aligned = adapter.profile_from_lines(
            lines,
            x_grid=x_grid,
            instrument_profile=profile,
            d_spacing_scale=1.01,
            zero_shift_deg=0.08,
        )

        baseline_peak = max(baseline.peaks, key=lambda peak: peak.raw_intensity)
        aligned_peak = next(
            peak
            for peak in aligned.peaks
            if (peak.h, peak.k, peak.l) == (baseline_peak.h, baseline_peak.k, baseline_peak.l)
        )
        self.assertAlmostEqual(aligned_peak.d, baseline_peak.d * 1.01)
        self.assertLess(aligned_peak.two_theta, baseline_peak.two_theta)
        self.assertFalse(np.allclose(aligned.profile_y, baseline.profile_y))

    def test_cached_finder_sticks_use_cristma_for_an_instrument_profile(self) -> None:
        profile = InstrumentProfile.default_cu_kalpha()
        context = CalculationContext(
            wavelength=1.54056,
            primary_wavelength=1.54056,
            fwhm=0.12,
            two_theta_min=10.0,
            two_theta_max=80.0,
            x_grid_fingerprint=(3501, 10.0, 80.0, 1),
            instrument_profile_key=profile.calculation_key(),
        )
        calculator = CachedProfileCalculator()
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"

        _structure, peaks = calculator.candidate_structure_and_sticks(
            str(cif_path),
            context,
            use_lp=True,
            instrument_profile=profile,
        )

        self.assertGreater(len(peaks), 10)
        self.assertEqual(calculator.cache_info()["cristma_sticks"], 1)

    def test_line_calculator_owns_cristma_sticks_and_cache(self) -> None:
        profile = InstrumentProfile.default_cu_kalpha()
        context = CalculationContext(
            wavelength=1.54056,
            primary_wavelength=1.54056,
            fwhm=0.12,
            two_theta_min=10.0,
            two_theta_max=80.0,
            x_grid_fingerprint=(3501, 10.0, 80.0, 1),
            instrument_profile_key=profile.calculation_key(),
        )
        calculator = CachedLineCalculator()
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"

        _structure, first = calculator.candidate_structure_and_sticks(
            str(cif_path),
            context,
            use_lp=True,
            instrument_profile=profile,
        )
        _structure, second = calculator.candidate_structure_and_sticks(
            str(cif_path),
            context,
            use_lp=True,
            instrument_profile=profile,
        )

        self.assertEqual(len(first), len(second))
        self.assertEqual(calculator.cache_info()["cristma_sticks"], 1)
        self.assertEqual(calculator.cache_info()["sticks_hits"], 1)

    def test_line_calculator_recalculates_lines_for_an_independent_cell_override(self) -> None:
        profile = InstrumentProfile.default_cu_kalpha()
        context = CalculationContext(
            wavelength=1.54056,
            primary_wavelength=1.54056,
            fwhm=0.12,
            two_theta_min=10.0,
            two_theta_max=80.0,
            x_grid_fingerprint=(3501, 10.0, 80.0, 1),
            instrument_profile_key=profile.calculation_key(),
        )
        calculator = CachedLineCalculator()
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"

        _structure, original = calculator.candidate_structure_and_lines(
            str(cif_path),
            context,
            use_lp=True,
            instrument_profile=profile,
        )
        fitted_cell = CellParameters(
            a=4.808206,
            b=4.808206,
            c=12.86406,
            alpha=90.0,
            beta=90.0,
            gamma=120.0,
        )
        fitted_structure, fitted = calculator.candidate_structure_and_lines(
            str(cif_path),
            context,
            use_lp=True,
            instrument_profile=profile,
            cell_override=fitted_cell,
        )

        original_by_hkl = {(peak.h, peak.k, peak.l): peak for peak in original.peaks}
        fitted_by_hkl = {(peak.h, peak.k, peak.l): peak for peak in fitted.peaks}
        common = original_by_hkl.keys() & fitted_by_hkl.keys()
        basal = next(hkl for hkl in common if hkl[2] == 0 and (hkl[0] or hkl[1]))
        axial = next(hkl for hkl in common if hkl[0] == 0 and hkl[1] == 0 and hkl[2])

        self.assertAlmostEqual(float(fitted_structure.cell.a), fitted_cell.a)
        self.assertGreater(fitted_by_hkl[basal].d, original_by_hkl[basal].d)
        self.assertLess(fitted_by_hkl[axial].d, original_by_hkl[axial].d)
        self.assertEqual(calculator.cache_info()["cristma_sticks"], 2)

    def test_cached_cristma_lines_are_reprofiled_without_reloading_cif(self) -> None:
        profile = InstrumentProfile.default_cu_kalpha()
        x_grid = np.linspace(10.0, 80.0, 3501)
        context = CalculationContext(
            wavelength=1.54056,
            primary_wavelength=1.54056,
            fwhm=0.12,
            two_theta_min=10.0,
            two_theta_max=80.0,
            x_grid_fingerprint=(3501, 10.0, 80.0, 1),
            instrument_profile_key=profile.calculation_key(),
            global_zero_shift=0.07,
            cell_scale=1.006,
        )
        line_calculator = CachedLineCalculator()
        calculator = CachedProfileCalculator(line_calculator=line_calculator)
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"

        _structure, line_data = line_calculator.candidate_structure_and_lines(
            str(cif_path),
            context,
            use_lp=True,
            instrument_profile=profile,
        )
        first = calculator.profile_from_lines(
            line_data,
            x_grid,
            context,
            instrument_profile=profile,
        )
        second = calculator.profile_from_lines(
            line_data,
            x_grid,
            context,
            instrument_profile=profile,
        )

        self.assertEqual(line_calculator.cache_info()["cristma_sticks"], 1)
        self.assertEqual(calculator.cache_info()["cristma_profiles"], 1)
        self.assertEqual(calculator.cache_info()["profile_hits"], 1)
        self.assertIs(first, second)

    def test_finder_uses_cristma_profile_for_unsnapped_cif_candidate(self) -> None:
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"
        x_grid = np.linspace(10.0, 80.0, 3501)
        instrument = InstrumentProfile.default_cu_kalpha()
        observed = CristmaPowderAdapter().calculate_from_cif(
            cif_path,
            x_grid=x_grid,
            instrument_profile=instrument,
            use_lp=True,
        )
        service = FinderService()

        result = service.run(
            FinderInput(
                pattern_path="",
                observed_x=x_grid.tolist(),
                observed_y=(observed.profile_y + 5.0).tolist(),
                subtract_background=False,
                snap_peak_positions=False,
                instrument_profile=instrument,
                candidates=[
                    FinderCandidateInput(
                        source="COD",
                        entry_id="1000018",
                        name="test phase",
                        cif_path=str(cif_path),
                    )
                ],
            )
        )

        self.assertEqual(len(result.candidates), 1)
        self.assertGreater(service.profile_calculator.cache_info()["cristma_profiles"], 0)

    def test_finder_estimates_a_starting_cell_before_reprofiling_an_indexed_cif(self) -> None:
        cif_path = Path(__file__).parents[1] / "Entry_96-100-0018.cif"
        x_grid = np.linspace(15.0, 80.0, 3251)
        instrument = InstrumentProfile.default_cu_kalpha()
        target_cell = CellParameters(
            a=4.7986848,
            b=4.7986848,
            c=12.942024,
            alpha=90.0,
            beta=90.0,
            gamma=120.0,
        )
        observed = CristmaPowderAdapter().calculate_from_cif(
            cif_path,
            x_grid=x_grid,
            instrument_profile=instrument,
            use_lp=True,
            cell_override=target_cell,
        )

        result = FinderService().run(
            FinderInput(
                pattern_path="",
                observed_x=x_grid.tolist(),
                observed_y=(observed.profile_y * 500.0 + 8.0).tolist(),
                subtract_background=False,
                snap_peak_positions=False,
                instrument_profile=instrument,
                candidates=[
                    FinderCandidateInput(
                        source="COD",
                        entry_id="1000018",
                        name="corundum",
                        cif_path=str(cif_path),
                    )
                ],
            )
        )

        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.cell_scale, 1.0)
        self.assertGreaterEqual(candidate.cell_fit_peaks, 4)
        _phase, initial_structure = create_phase_from_cif(str(cif_path))
        self.assertLess(
            abs(candidate.estimated_cell["a"] - target_cell.a),
            abs(float(initial_structure.cell.a) - target_cell.a),
        )
        self.assertLess(
            abs(candidate.estimated_cell["c"] - target_cell.c),
            abs(float(initial_structure.cell.c) - target_cell.c),
        )
        self.assertLess(candidate.cell_fit_rms_deg, candidate.cell_fit_initial_rms_deg * 0.5)


if __name__ == "__main__":
    unittest.main()
