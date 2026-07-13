from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import zlib

import numpy as np

from xrd_finder.finder.context import CalculationContext
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.services.calculated_pattern_service import (
    CalculatedPatternService,
    HKLPeak,
    calculated_profile_from_peaks,
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
    ) -> None:
        self.calculated_pattern_service = calculated_pattern_service or CalculatedPatternService()
        self._sticks_cache: OrderedDict[tuple[str, int, float, float, float, bool], list[HKLPeak]] = OrderedDict()
        self._sticks_cache_limit = max(0, int(sticks_cache_limit))
        self._profile_cache: OrderedDict[tuple[object, ...], np.ndarray] = OrderedDict()
        self._profile_cache_limit = max(0, int(profile_cache_limit))
        self._profile_cache_max_bytes = max(0, int(profile_cache_max_bytes))
        self._profile_cache_bytes = 0
        self._sticks_hits = 0
        self._sticks_misses = 0
        self._profile_hits = 0
        self._profile_misses = 0

    def cache_info(self) -> dict[str, int]:
        return {
            "sticks": len(self._sticks_cache),
            "profiles": len(self._profile_cache),
            "profile_bytes": int(self._profile_cache_bytes),
            "sticks_hits": int(self._sticks_hits),
            "sticks_misses": int(self._sticks_misses),
            "profile_hits": int(self._profile_hits),
            "profile_misses": int(self._profile_misses),
        }

    def candidate_sticks(
        self,
        cif_path: str,
        context: CalculationContext,
        use_lp: bool,
    ) -> list[HKLPeak]:
        path = Path(cif_path)
        stat = path.stat()
        wavelength, two_theta_min, two_theta_max = context.sticks_key
        cache_key = (
            str(path.resolve()),
            int(stat.st_mtime_ns),
            wavelength,
            two_theta_min,
            two_theta_max,
            bool(use_lp),
        )
        cached = self._sticks_cache.get(cache_key)
        if cached is not None:
            self._sticks_hits += 1
            self._sticks_cache.move_to_end(cache_key)
            return list(cached)
        self._sticks_misses += 1
        _phase, structure = create_phase_from_cif(str(path))
        peaks = self.calculated_pattern_service.calculate_sticks(
            structure,
            two_theta_min=two_theta_min,
            two_theta_max=two_theta_max,
            wavelength=wavelength,
            use_lp=use_lp,
        )
        if self._sticks_cache_limit > 0:
            self._sticks_cache[cache_key] = list(peaks)
            self._trim_sticks_cache()
        return peaks

    def profile_from_peaks(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
    ) -> np.ndarray:
        cache_key = self._profile_cache_key(peaks, context)
        cached = self._profile_cache.get(cache_key)
        if cached is not None:
            self._profile_hits += 1
            self._profile_cache.move_to_end(cache_key)
            return cached
        self._profile_misses += 1
        _x, profile = calculated_profile_from_peaks(
            peaks,
            x_grid,
            fwhm=context.fwhm,
            eta=context.profile_eta,
            wavelength=context.wavelength,
            include_kalpha2=True,
        )
        profile = np.asarray(profile, dtype=float)
        profile.setflags(write=False)
        if self._profile_cache_limit > 0 and self._profile_cache_max_bytes > 0:
            self._profile_cache[cache_key] = profile
            self._profile_cache_bytes += int(profile.nbytes)
            self._trim_profile_cache()
        return profile

    def _trim_sticks_cache(self) -> None:
        while len(self._sticks_cache) > self._sticks_cache_limit:
            self._sticks_cache.popitem(last=False)

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
    ) -> tuple[object, ...]:
        return (
            context.profile_key,
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
