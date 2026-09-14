from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path

from xrd_finder.core.structure import CellParameters
from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.reference_lines import ReferenceLineSet
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    HKLPeak,
)

from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter


@dataclass(frozen=True, slots=True)
class CandidateLineData:
    peaks: tuple[HKLPeak, ...]
    fingerprint: tuple[object, ...]
    cristma_lines: object | None = None


class CachedLineCalculator:
    """Load and cache wavelength-aware powder lines independently of profiles."""

    def __init__(
        self,
        calculated_pattern_service=None,
        cache_limit: int = 256,
        cristma_adapter=None,
    ) -> None:
        self._sticks_cache: OrderedDict[tuple[object, ...], CandidateLineData] = OrderedDict()
        self._structure_cache: OrderedDict[tuple[str, int], object] = OrderedDict()
        self._cache_limit = max(0, int(cache_limit))
        self._sticks_hits = 0
        self._sticks_misses = 0
        self._cristma_adapter = cristma_adapter if cristma_adapter is not None else CristmaPowderAdapter()
        self._cristma_sticks = 0

    @property
    def cristma_adapter(self):
        return self._cristma_adapter

    def cache_info(self) -> dict[str, int]:
        return {
            "sticks": len(self._sticks_cache),
            "sticks_hits": int(self._sticks_hits),
            "sticks_misses": int(self._sticks_misses),
            "cristma_sticks": int(self._cristma_sticks),
        }

    def candidate_sticks(
        self,
        cif_path: str,
        context: CalculationContext,
        use_lp: bool,
        instrument_profile: InstrumentProfile | None = None,
        cell_override: CellParameters | None = None,
    ) -> list[HKLPeak]:
        _structure, peaks = self.candidate_structure_and_sticks(
            cif_path,
            context,
            use_lp,
            instrument_profile=instrument_profile,
            cell_override=cell_override,
        )
        return peaks

    def candidate_structure_and_sticks(
        self,
        cif_path: str,
        context: CalculationContext,
        use_lp: bool,
        instrument_profile: InstrumentProfile | None = None,
        cell_override: CellParameters | None = None,
    ) -> tuple[object, list[HKLPeak]]:
        structure, lines = self.candidate_structure_and_lines(
            cif_path,
            context,
            use_lp,
            instrument_profile=instrument_profile,
            cell_override=cell_override,
        )
        return structure, list(lines.peaks)

    def candidate_structure_and_lines(
        self,
        cif_path: str,
        context: CalculationContext,
        use_lp: bool,
        instrument_profile: InstrumentProfile | None = None,
        cell_override: CellParameters | None = None,
    ) -> tuple[object, CandidateLineData]:
        path = Path(cif_path)
        stat = path.stat()
        structure_key = (str(path.resolve()), int(stat.st_mtime_ns))
        wavelength, two_theta_min, two_theta_max, instrument_profile_key = context.sticks_key
        cell_key = self._cell_key(cell_override)
        cache_key = (
            *structure_key,
            wavelength,
            two_theta_min,
            two_theta_max,
            bool(use_lp),
            instrument_profile_key,
            cell_key,
        )
        cached = self._sticks_cache.get(cache_key)
        structure = self._structure_cache.get(structure_key)
        if cached is not None:
            self._sticks_hits += 1
            self._sticks_cache.move_to_end(cache_key)
            if structure is None:
                _phase, structure = create_phase_from_cif(str(path))
                self._cache_structure(structure_key, structure)
            else:
                self._structure_cache.move_to_end(structure_key)
            return self._structure_with_cell(structure, cell_override), cached

        self._sticks_misses += 1
        if structure is None:
            _phase, structure = create_phase_from_cif(str(path))
            self._cache_structure(structure_key, structure)
        else:
            self._structure_cache.move_to_end(structure_key)

        if instrument_profile is None:
            raise ValueError("CRiStMa powder lines require an instrument profile")
        cristma_lines = self._cristma_adapter.lines_from_cif(
            path,
            two_theta_min=two_theta_min,
            two_theta_max=two_theta_max,
            instrument_profile=instrument_profile,
            use_lp=use_lp,
            cell_override=cell_override,
        )
        peaks = list(cristma_lines.peaks)
        self._cristma_sticks += 1
        line_data = CandidateLineData(
            peaks=tuple(peaks),
            fingerprint=cache_key,
            cristma_lines=cristma_lines,
        )
        if self._cache_limit > 0:
            self._sticks_cache[cache_key] = line_data
            self._trim_cache()
        return self._structure_with_cell(structure, cell_override), line_data

    @staticmethod
    def _cell_key(cell: CellParameters | None) -> tuple[float, ...] | None:
        if cell is None:
            return None
        return tuple(
            round(float(getattr(cell, name)), 8)
            for name in ("a", "b", "c", "alpha", "beta", "gamma")
        )

    @staticmethod
    def _structure_with_cell(structure: object, cell: CellParameters | None) -> object:
        result = deepcopy(structure)
        if cell is not None:
            result.cell = deepcopy(cell)
        return result

    def peaks_from_reference_lines(
        self,
        lines: ReferenceLineSet,
        context: CalculationContext,
    ) -> list[HKLPeak]:
        peaks = []
        relative_intensities = [
            max(float(line.normalized_intensity or line.intensity), 0.0)
            for line in lines.lines
        ]
        maximum_intensity = max(
            (value for value in relative_intensities if math.isfinite(value)),
            default=0.0,
        )
        intensity_scale = 100.0 / maximum_intensity if maximum_intensity > 0.0 else 1.0
        use_cached_angles = math.isclose(
            float(context.primary_wavelength),
            CU_KA1_WAVELENGTH,
            rel_tol=0.0,
            abs_tol=1.0e-4,
        )
        for line, relative_intensity in zip(lines.lines, relative_intensities):
            two_theta = float(line.two_theta)
            if not use_cached_angles:
                argument = float(context.primary_wavelength) / (2.0 * float(line.d))
                if not 0.0 < argument <= 1.0:
                    continue
                two_theta = math.degrees(2.0 * math.asin(argument))
            if not context.two_theta_min <= two_theta <= context.two_theta_max:
                continue
            intensity = relative_intensity * intensity_scale
            raw_intensity = max(float(line.raw_intensity or line.intensity), 0.0)
            peaks.append(
                HKLPeak(
                    h=int(line.h),
                    k=int(line.k),
                    l=int(line.l),
                    d=float(line.d),
                    two_theta=two_theta,
                    intensity=intensity,
                    multiplicity=max(int(line.multiplicity), 1),
                    raw_intensity=raw_intensity,
                )
            )
        return peaks

    def _cache_structure(self, key: tuple[str, int], structure: object) -> None:
        if self._cache_limit <= 0:
            return
        self._structure_cache[key] = structure
        self._structure_cache.move_to_end(key)
        while len(self._structure_cache) > self._cache_limit:
            self._structure_cache.popitem(last=False)

    def _trim_cache(self) -> None:
        while len(self._sticks_cache) > self._cache_limit:
            self._sticks_cache.popitem(last=False)


__all__ = ["CachedLineCalculator", "CandidateLineData"]
