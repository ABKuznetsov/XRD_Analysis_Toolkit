from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION
from xrd_finder.finder.context import CalculationContext
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.cif_powder_pattern import extract_cif_powder_peaks
from xrd_finder.services.calculated_pattern_service import HKLPeak, radiation_lines_from_wavelength


def candidate_cif_fingerprint(path: Path) -> tuple[str, bytes]:
    return str(path.resolve()), hashlib.sha256(path.read_bytes()).digest()


class GainLineMixin:
    """Existing local diffraction-line resolution shared with the Gain worker."""

    def _structure_cell_signature(self, structure) -> tuple[object, ...] | None:
        if structure is None:
            return None
        cell = getattr(structure, "cell", None)
        if cell is None:
            return None
        return tuple(
            None if getattr(cell, name, None) is None else round(float(getattr(cell, name)), 8)
            for name in ("a", "b", "c", "alpha", "beta", "gamma", "volume")
        )

    def _trim_candidate_json_peak_cache(self, limit: int = 5000) -> None:
        while len(self._candidate_json_peak_cache) > limit:
            self._candidate_json_peak_cache.pop(next(iter(self._candidate_json_peak_cache)), None)

    def _trim_candidate_peak_cache(self, limit: int = 2048) -> None:
        while len(self._candidate_peak_cache) > limit:
            self._candidate_peak_cache.pop(next(iter(self._candidate_peak_cache)), None)

    def _candidate_cif_peaks_for_gain(self, candidate: dict[str, str]) -> list[HKLPeak]:
        structure = self._gain_structure_override(candidate)
        cif_path = self._candidate_local_cif_path(candidate)
        try:
            if structure is None:
                if cif_path is None:
                    return []
                # Missing local indices use the same native engine as preparation,
                # never the old per-reflection Python structural-factor loop.
                peaks = extract_cif_powder_peaks(cif_path, wavelength=self._active_wavelength(), intensity_min=.5)
                if peaks:
                    return peaks
                from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
                return list(CristmaPowderAdapter().reference_sticks_from_cif(
                    cif_path, two_theta_min=5., two_theta_max=120.,
                    instrument_profile=self._gain_instrument_profile(), use_lp=True))
            if candidate.get("Phase"):
                structure.name = candidate["Phase"]
            structure.wavelength = self._active_wavelength()
            if cif_path is not None:
                return self._candidate_cached_peaks(cif_path, structure)
            return self.calculated_pattern_service.calculate_sticks(
                structure,
                wavelength=self._active_wavelength(),
                two_theta_min=5.0,
                two_theta_max=120.0,
                intensity_min=0.5,
            )
        except Exception:
            return []

    def _candidate_cached_json_peaks(self, candidate: dict[str, str]) -> list[HKLPeak]:
        from xrd_finder.finder.reference_lines import ReferenceLineSet
        import hashlib
        if self._candidate_embedded_cif_path(candidate) is not None:
            return []
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if source not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"} or not entry_id:
            return []
        entry = self.local_phase_cache.get(source, entry_id)
        if entry is None or not entry.peaks_json or entry.derived_version != DERIVED_CACHE_VERSION:
            return []
        instrument = (self._gain_instrument_profile() if hasattr(self, "_gain_instrument_profile")
                      else self._instrument_profile_for_pattern(self._active_pattern()))
        wavelength = instrument.radiation.components[0].wavelength_angstrom
        if not self.local_phase_cache.reference_range_covered(source, entry_id, wavelength=wavelength):
            return []
        cache_key = (source, entry_id, entry.derived_version,
            hashlib.sha256(entry.peaks_json.encode('utf-8')).digest(), instrument.calculation_key())
        cached = self._candidate_json_peak_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            lines = ReferenceLineSet.from_records(source=source,entry_id=entry_id,
                derived_version=entry.derived_version,provenance="local-phase-cache-json",
                records=json.loads(entry.peaks_json))
        except (ValueError,TypeError):
            return []
        context = CalculationContext(wavelength,wavelength,.18,5.,120.,(0,0.,0.,0),
            include_kalpha2=False,instrument_profile_key=instrument.calculation_key())
        peaks = self.finder_service.profile_calculator.peaks_from_reference_lines(
            lines,context,instrument_profile=instrument)
        self._candidate_json_peak_cache[cache_key] = peaks
        self._trim_candidate_json_peak_cache()
        return peaks

    def _candidate_cached_peaks(self, cif_path: Path, structure) -> list:
        file_key = candidate_cif_fingerprint(cif_path)
        wavelength = float(self._active_wavelength())
        cache_key = (
            file_key,
            wavelength,
            self._structure_cell_signature(structure),
        )
        cached = self._candidate_peak_cache.get(cache_key)
        if cached is not None:
            return cached
        peaks = extract_cif_powder_peaks(
            cif_path,
            wavelength=self._active_wavelength(),
            intensity_min=0.5,
        )
        if not peaks:
            peaks = self.calculated_pattern_service.calculate_sticks(
                structure,
                wavelength=self._active_wavelength(),
                two_theta_min=5.0,
                two_theta_max=120.0,
                intensity_min=0.5,
            )
        self._candidate_peak_cache[cache_key] = peaks
        self._trim_candidate_peak_cache()
        return peaks

    def _candidate_peaks_for_gain(self, candidate: dict[str, str]) -> list:
        if self._candidate_source(candidate) == "PDF2":
            return self._pdf2_peaks_for_candidate(candidate)
        indexed_peaks = self._candidate_indexed_peaks(candidate)
        if indexed_peaks:
            return indexed_peaks
        if self._candidate_embedded_cif_path(candidate) is not None:
            return self._candidate_cif_peaks_for_gain(candidate)
        structure = self._gain_structure_override(candidate)
        if structure is not None:
            try:
                cif_path = self._candidate_local_cif_path(candidate)
                if cif_path is not None:
                    return self._candidate_cached_peaks(cif_path, structure)
                return self.calculated_pattern_service.calculate_sticks(
                    structure,
                    wavelength=self._active_wavelength(),
                    two_theta_min=5.0,
                    two_theta_max=120.0,
                    intensity_min=0.5,
                )
            except Exception:
                pass
        peaks = self._candidate_cached_json_peaks(candidate)
        if not peaks:
            peaks = self._candidate_cif_peaks_for_gain(candidate)
        return peaks

    def _candidate_indexed_peaks(self, candidate: dict[str, str]) -> list:
        if (self._candidate_embedded_cif_path(candidate) is not None
                or self._gain_structure_override(candidate) is not None):
            return []
        provider = getattr(self, "candidate_line_provider", None)
        if provider is None:
            return []
        instrument = (self._gain_instrument_profile() if hasattr(self, "_gain_instrument_profile")
                      else self._instrument_profile_for_pattern(self._active_pattern()))
        primary_wavelength = float(instrument.radiation.components[0].wavelength_angstrom)
        resolution = provider.resolve(candidate, wavelength=primary_wavelength)
        if resolution.line_set is None:
            return []
        wavelength = float(self._active_wavelength())
        context = CalculationContext(
            wavelength=wavelength,
            primary_wavelength=float(primary_wavelength),
            fwhm=0.18,
            two_theta_min=5.0,
            two_theta_max=120.0,
            x_grid_fingerprint=(0, 0.0, 0.0, 0),
            include_kalpha2=False,
        )
        return self.finder_service.profile_calculator.peaks_from_reference_lines(
            resolution.line_set,
            context,
            instrument_profile=instrument,
        )

    def _pdf2_peaks_for_candidate(self, candidate: dict[str, str]):
        if self.match_pdf2 is None:
            return []
        wavelength = self._active_wavelength()
        peaks = []
        for peak in self.match_pdf2.diffraction_peaks(candidate.get("Entry", "")):
            ratio = wavelength / (2.0 * peak.d_spacing)
            if ratio <= 0.0 or ratio > 1.0:
                continue
            two_theta = math.degrees(2.0 * math.asin(ratio))
            peaks.append(
                SimpleNamespace(
                    two_theta=two_theta,
                    reference_two_theta=two_theta,
                    d_spacing=peak.d_spacing,
                    intensity=peak.intensity,
                    h=peak.h,
                    k=peak.k,
                    l=peak.l,
                )
            )
        return peaks

    def _candidate_embedded_cif_path(self, candidate: dict[str, str]) -> Path | None:
        candidate_paths, _phases = self._gain_line_locations()
        embedded_path = candidate_paths.get(self._candidate_key(candidate))
        if embedded_path:
            path = Path(embedded_path)
            if path.is_file():
                return path
        return None

    def _candidate_local_cif_path(self, candidate: dict[str, str]) -> Path | None:
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if not entry_id:
            return None
        embedded_path = self._candidate_embedded_cif_path(candidate)
        if embedded_path is not None:
            return embedded_path
        if source == "USER":
            cached_path = self.local_phase_cache.cif_path("USER", entry_id)
            if cached_path is not None:
                return cached_path
            _paths, phases = self._gain_line_locations()
            phase = next((item for item in phases if item.id == entry_id), None)
            if phase is not None and phase.source_path:
                path = Path(phase.source_path)
                if path.exists():
                    return path
            for phase in phases:
                if Path(phase.source_path or "").stem == entry_id:
                    path = Path(phase.source_path)
                    if path.exists():
                        return path
            return None
        if source in {"COD", "CCDC", "MP", "AFLOW", "OQMD"}:
            return self.local_phase_cache.cif_path(source, entry_id)
        return None
