from __future__ import annotations

from collections import OrderedDict
import zlib

import numpy as np

from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.line_calculator import CachedLineCalculator, CandidateLineData
from xrd_finder.finder.profile_backend import FinderPeakProfileBackend, PeakProfileBackend
from xrd_finder.finder.reference_lines import ReferenceLineSet
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.calculated_pattern_service import (
    CalculatedPatternService,
    HKLPeak,
)


def array_fingerprint(values: np.ndarray) -> tuple[int, float, float, int]:
    array = np.ascontiguousarray(values, dtype=np.float64)
    if len(array) == 0:
        return (0, 0.0, 0.0, 0)
    checksum = zlib.crc32(array.tobytes())
    return (len(array), round(float(array[0]), 7), round(float(array[-1]), 7), int(checksum))


class CachedProfileCalculator:
    def __init__(
        self,
        calculated_pattern_service: CalculatedPatternService | None = None,
        sticks_cache_limit: int = 256,
        profile_cache_limit: int = 256,
        profile_cache_max_bytes: int = 128 * 1024 * 1024,
        cristma_adapter=None,
        line_calculator: CachedLineCalculator | None = None,
        profile_backend: PeakProfileBackend | None = None,
    ) -> None:
        self.calculated_pattern_service = calculated_pattern_service or CalculatedPatternService()
        self.line_calculator = line_calculator or CachedLineCalculator(
            calculated_pattern_service=self.calculated_pattern_service,
            cache_limit=sticks_cache_limit,
            cristma_adapter=cristma_adapter,
        )
        self.profile_backend = profile_backend or FinderPeakProfileBackend()
        self._profile_cache: OrderedDict[tuple[object, ...], np.ndarray] = OrderedDict()
        self._profile_cache_limit = max(0, int(profile_cache_limit))
        self._profile_cache_max_bytes = max(0, int(profile_cache_max_bytes))
        self._profile_cache_bytes = 0
        self._profile_hits = 0
        self._profile_misses = 0
        self._cristma_profiles = 0

    def cache_info(self) -> dict[str, int]:
        return {
            **self.line_calculator.cache_info(),
            "profiles": len(self._profile_cache),
            "profile_bytes": int(self._profile_cache_bytes),
            "profile_hits": int(self._profile_hits),
            "profile_misses": int(self._profile_misses),
            "cristma_profiles": int(self._cristma_profiles),
        }

    def candidate_sticks(
        self,
        cif_path: str,
        context: CalculationContext,
        use_lp: bool,
        instrument_profile: InstrumentProfile | None = None,
    ) -> list[HKLPeak]:
        return self.line_calculator.candidate_sticks(
            cif_path,
            context,
            use_lp,
            instrument_profile=instrument_profile,
        )

    def candidate_structure_and_sticks(
        self,
        cif_path: str,
        context: CalculationContext,
        use_lp: bool,
        instrument_profile: InstrumentProfile | None = None,
    ) -> tuple[object, list[HKLPeak]]:
        return self.line_calculator.candidate_structure_and_sticks(
            cif_path,
            context,
            use_lp,
            instrument_profile=instrument_profile,
        )

    def profile_from_peaks(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
        source_fingerprint: tuple[object, ...] | None = None,
        *,
        instrument_profile: InstrumentProfile | None = None,
    ) -> np.ndarray:
        cache_key = self._profile_cache_key(
            peaks,
            context,
            source_fingerprint,
            instrument_profile=instrument_profile,
        )
        cached = self._profile_cache.get(cache_key)
        if cached is not None:
            self._profile_hits += 1
            self._profile_cache.move_to_end(cache_key)
            return cached
        self._profile_misses += 1
        instrument_calculator = getattr(self.profile_backend, "calculate_with_instrument", None)
        if instrument_profile is not None and callable(instrument_calculator):
            profile = instrument_calculator(
                peaks,
                x_grid,
                context,
                instrument_profile,
            )
        else:
            profile = self.profile_backend.calculate(
                peaks,
                x_grid,
                context,
            )
        profile = np.asarray(profile, dtype=float)
        profile.setflags(write=False)
        if self._profile_cache_limit > 0 and self._profile_cache_max_bytes > 0:
            self._profile_cache[cache_key] = profile
            self._profile_cache_bytes += int(profile.nbytes)
            self._trim_profile_cache()
        return profile

    def profile_from_lines(
        self,
        lines: CandidateLineData,
        x_grid: np.ndarray,
        context: CalculationContext,
        *,
        instrument_profile: InstrumentProfile,
    ) -> np.ndarray:
        adapter = self.line_calculator.cristma_adapter
        if lines.cristma_lines is None or adapter is None:
            return self.profile_from_peaks(
                list(lines.peaks),
                x_grid,
                context,
                source_fingerprint=lines.fingerprint,
                instrument_profile=instrument_profile,
            )
        cache_key = (
            "cristma-lines-v1",
            lines.fingerprint,
            instrument_profile.calculation_key(),
            context.profile_key,
        )
        cached = self._profile_cache.get(cache_key)
        if cached is not None:
            self._profile_hits += 1
            self._profile_cache.move_to_end(cache_key)
            return cached
        self._profile_misses += 1
        result = adapter.profile_from_lines(
            lines.cristma_lines,
            x_grid=x_grid,
            instrument_profile=instrument_profile,
            zero_shift_deg=context.global_zero_shift,
            d_spacing_scale=context.cell_scale,
        )
        profile = np.asarray(result.profile_y, dtype=float)
        profile.setflags(write=False)
        self._cristma_profiles += 1
        if self._profile_cache_limit > 0 and self._profile_cache_max_bytes > 0:
            self._profile_cache[cache_key] = profile
            self._profile_cache_bytes += int(profile.nbytes)
            self._trim_profile_cache()
        return profile

    def peaks_from_reference_lines(
        self,
        lines: ReferenceLineSet,
        context: CalculationContext,
    ) -> list[HKLPeak]:
        return self.line_calculator.peaks_from_reference_lines(lines, context)

    def _trim_profile_cache(self) -> None:
        while self._profile_cache and (
            len(self._profile_cache) > self._profile_cache_limit
            or self._profile_cache_bytes > self._profile_cache_max_bytes
        ):
            _key, profile = self._profile_cache.popitem(last=False)
            self._profile_cache_bytes -= int(profile.nbytes)
        self._profile_cache_bytes = max(0, int(self._profile_cache_bytes))

    def _profile_cache_key(
        self,
        peaks: list[HKLPeak],
        context: CalculationContext,
        source_fingerprint: tuple[object, ...] | None = None,
        *,
        instrument_profile: InstrumentProfile | None = None,
    ) -> tuple[object, ...]:
        return (
            str(self.profile_backend.cache_key),
            context.profile_key,
            source_fingerprint,
            None if instrument_profile is None else instrument_profile.calculation_key(),
            tuple(
                (
                    int(peak.h),
                    int(peak.k),
                    int(peak.l),
                    round(float(peak.d), 7),
                    round(float(peak.two_theta), 5),
                    round(float(peak.intensity), 4),
                )
                for peak in peaks
            ),
        )
