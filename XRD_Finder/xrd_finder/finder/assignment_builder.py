from __future__ import annotations

import numpy as np

from xrd_finder.finder.models import FinderCandidateResult, ObservedPeak, PeakAssignment, PeakStatus
from xrd_finder.services.calculated_pattern_service import HKLPeak


def nearest_index(sorted_values: np.ndarray, value: float) -> int:
    index = int(np.searchsorted(sorted_values, value, side="left"))
    if index <= 0:
        return 0
    if index >= len(sorted_values):
        return len(sorted_values) - 1
    before = index - 1
    return before if abs(float(sorted_values[before]) - value) <= abs(float(sorted_values[index]) - value) else index


def sorted_usable_peaks(peaks: list[HKLPeak], intensity_min: float = 5.0) -> tuple[list[HKLPeak], np.ndarray]:
    usable = sorted((peak for peak in peaks if peak.intensity >= intensity_min), key=lambda peak: peak.two_theta)
    positions = np.fromiter((float(peak.two_theta) for peak in usable), dtype=float, count=len(usable))
    return usable, positions


def nearest_peak_from_sorted(
    observed_two_theta: float,
    usable: list[HKLPeak],
    positions: np.ndarray,
    tolerance: float,
) -> tuple[HKLPeak, float] | None:
    if len(positions) == 0:
        return None
    index = nearest_index(positions, float(observed_two_theta))
    delta = float(observed_two_theta) - float(positions[index])
    if abs(delta) > tolerance:
        return None
    return usable[index], delta


def nearest_phase_peak(
    observed_two_theta: float,
    peaks: list[HKLPeak],
    tolerance: float,
) -> tuple[HKLPeak, float] | None:
    usable, positions = sorted_usable_peaks(peaks, intensity_min=5.0)
    return nearest_peak_from_sorted(observed_two_theta, usable, positions, tolerance)


class AssignmentBuilder:
    def assign_observed_peaks(
        self,
        observed_peaks: list[ObservedPeak],
        phase_peak_sets: list[tuple[FinderCandidateResult, list[HKLPeak]]],
        tolerance: float,
    ) -> list[ObservedPeak]:
        assigned = []
        prepared_phase_peaks = [
            (candidate, *sorted_usable_peaks(peaks, intensity_min=5.0))
            for candidate, peaks in phase_peak_sets
        ]
        for observed in observed_peaks:
            assignments = []
            for candidate, usable_peaks, peak_positions in prepared_phase_peaks:
                nearest = nearest_peak_from_sorted(observed.two_theta, usable_peaks, peak_positions, tolerance)
                if nearest is None:
                    continue
                peak, delta = nearest
                assignments.append(
                    PeakAssignment(
                        candidate_key=candidate.candidate_key,
                        phase_name=candidate.name or candidate.formula or candidate.entry_id,
                        hkl=(int(peak.h), int(peak.k), int(peak.l)),
                        calc_two_theta=float(peak.two_theta),
                        delta_two_theta=float(delta),
                        intensity_ratio=float(max(peak.intensity, 0.0) / 100.0),
                    )
                )
            if len(assignments) == 0:
                status = PeakStatus.UNKNOWN
            elif len(assignments) == 1:
                status = PeakStatus.MATCHED
            else:
                status = PeakStatus.OVERLAPPING
            assigned.append(
                ObservedPeak(
                    two_theta=observed.two_theta,
                    intensity=observed.intensity,
                    fwhm=observed.fwhm,
                    assignments=assignments,
                    status=status,
                )
            )
        return assigned
