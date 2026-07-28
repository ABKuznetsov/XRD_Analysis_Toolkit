from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class GainStage(StrEnum):
    """Residual evidence mode used while ranking an additional phase."""

    DIRECT = "direct"
    OVERLAP = "overlap"
    HIDDEN = "hidden"


@dataclass(frozen=True, slots=True)
class GainIndexedEvidence:
    stage: GainStage
    indexed_matches: tuple[tuple[int, int, int, float, float], ...]


def build_gain_indexed_evidence(
    *,
    peaks,
    records,
    stage: GainStage,
    base_fwhm: float,
) -> GainIndexedEvidence:
    """Create one-to-one hkl/observed pairs from the lines that support Gain."""

    strong = sorted(
        (
            peak
            for peak in peaks
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
            and (int(getattr(peak, "h", 0)), int(getattr(peak, "k", 0)), int(getattr(peak, "l", 0))) != (0, 0, 0)
        ),
        key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0),
        reverse=True,
    )[:42]
    available = set(range(len(records)))
    matches: list[tuple[int, int, int, float, float]] = []

    def record_value(record, attribute: str, index: int) -> float:
        value = getattr(record, attribute, None)
        if value is None:
            value = record[index]
        return float(value)

    for peak in strong:
        calculated = float(getattr(peak, "two_theta", 0.0) or 0.0)
        best_index = -1
        best_delta = float("inf")
        for index in available:
            record = records[index]
            observed = record_value(record, "two_theta", 0)
            line_fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), float(base_fwhm), 0.05)
            tolerance = max(0.26, min(0.72, line_fwhm * 2.4))
            delta = abs(observed - calculated)
            if delta <= tolerance and delta < best_delta:
                best_index = index
                best_delta = delta
        if best_index < 0:
            continue
        available.remove(best_index)
        record = records[best_index]
        observed = record_value(record, "two_theta", 0)
        area = max(record_value(record, "area", 1), 1.0)
        matches.append(
            (
                int(getattr(peak, "h", 0)),
                int(getattr(peak, "k", 0)),
                int(getattr(peak, "l", 0)),
                observed,
                area,
            )
        )
    return GainIndexedEvidence(stage=stage, indexed_matches=tuple(matches))


@dataclass(frozen=True)
class GainPolicy:
    """All top-level Gain thresholds and score-combination rules."""

    minimum_stage_records: int = 2
    maximum_fit: float = 98.0
    minimum_remaining_fit: float = 1.5
    minimum_residual_share: float = 0.025
    phase_count_for_exhaustion_gate: int = 5
    minimum_profile_support: float = 0.35
    hidden_presence_weight: float = 0.45

    def select_stage(self, *, direct_count: int, overlap_count: int) -> GainStage:
        if direct_count >= self.minimum_stage_records:
            return GainStage.DIRECT
        if overlap_count >= self.minimum_stage_records:
            return GainStage.OVERLAP
        return GainStage.HIDDEN

    def residual_is_exhausted(
        self,
        *,
        selected_phase_count: int,
        before_fit: float,
        residual_share: float,
    ) -> bool:
        remaining_fit = max(0.0, 100.0 - float(before_fit))
        if float(before_fit) >= self.maximum_fit:
            return True
        return (
            int(selected_phase_count) >= self.phase_count_for_exhaustion_gate
            and (
                remaining_fit < self.minimum_remaining_fit
                or float(residual_share) < self.minimum_residual_share
            )
        )

    def combine_line_and_profile(self, *, line_gain: float, profile_gain: float | None) -> float:
        line_gain = max(float(line_gain), 0.0)
        if line_gain <= 0.0:
            return 0.0
        if profile_gain is None:
            return line_gain
        support = float(
            np.clip(
                float(profile_gain) / max(line_gain, 1.0e-6),
                self.minimum_profile_support,
                1.0,
            )
        )
        return line_gain * support

    def hidden_gain(self, *, before_fit: float, presence: float) -> float:
        remaining_fit = max(0.0, 100.0 - float(before_fit))
        return float(
            np.clip(
                remaining_fit * max(float(presence), 0.0) * self.hidden_presence_weight,
                0.0,
                remaining_fit,
            )
        )


DEFAULT_GAIN_POLICY = GainPolicy()


def profile_residual_gain(
    *,
    residual_target: np.ndarray,
    calculated: np.ndarray,
    weights: np.ndarray,
    residual_area: float,
    before_fit: float,
) -> float:
    """Score the additional profile area explained without profile excess."""

    residual_target = np.asarray(residual_target, dtype=float)
    calculated = np.asarray(calculated, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if not (
        len(residual_target)
        and len(calculated) == len(residual_target)
        and len(weights) == len(residual_target)
    ):
        return 0.0
    covered = np.minimum(residual_target, calculated)
    excess = np.clip(calculated - residual_target, 0.0, None)
    covered_area = float(np.trapezoid(covered * weights))
    excess_area = float(np.trapezoid(excess * weights))
    if covered_area <= 0.0:
        return 0.0
    residual_fraction = covered_area / max(float(residual_area), 1.0e-12)
    support_fraction = covered_area / max(covered_area + 3.0 * excess_area, 1.0e-12)
    gain = 100.0 * residual_fraction * support_fraction
    remaining_fit = max(0.0, 100.0 - float(before_fit))
    return float(np.clip(min(gain, remaining_fit), 0.0, 100.0))
