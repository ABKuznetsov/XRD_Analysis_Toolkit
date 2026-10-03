from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Iterable

import numpy as np


class GainStage(StrEnum):
    DIRECT = "direct"
    OVERLAP = "overlap"
    HIDDEN = "hidden"


@dataclass(frozen=True, slots=True)
class GainPolicy:
    minimum_stage_records: int = 2
    sparse_strongest_fraction: float = 0.45
    sparse_two_strongest_fraction: float = 0.65
    maximum_fit: float = 98.0
    minimum_remaining_fit: float = 1.5
    minimum_residual_share: float = 0.025
    phase_count_for_exhaustion_gate: int = 5
    minimum_profile_support: float = 0.35
    hidden_presence_weight: float = 0.45
    sparse_profile_weight: float = 0.0
    overlap_evidence_weight: float = 0.72
    hidden_evidence_weight: float = 0.20
    limited_residual_fraction: float = 0.35
    evidence_combination: str = "baseline"
    corroboration_weight: float = 0.20
    winner_overlap_weight: float = 1.0
    phase_snr_detection: float = 3.0
    phase_snr_full_support: float = 7.0
    minimum_phase_snr_support: float = 0.50
    minimum_reported_gain: float = 3.0

    def combine_evidence(
        self,
        *,
        direct_gain: float,
        overlap_gain: float,
        hidden_gain: float,
        profile_gain: float | None,
        remaining_fit: float,
        residual_line_count: int,
        direct_reliability: float = 1.0,
        phase_snr: float | None = None,
    ) -> float:
        """Combine all Gain evidence without exposing internal search modes."""

        direct = max(float(direct_gain), 0.0)
        overlap = max(float(overlap_gain), 0.0)
        hidden = max(float(hidden_gain), 0.0)
        remaining = max(float(remaining_fit), 0.0)
        overlap_weighted = self.overlap_evidence_weight * overlap
        winner_overlap = self.winner_overlap_weight * overlap
        direct_for_dominance = direct
        if self.evidence_combination == "winner_corroboration":
            line_evidence = max(direct, winner_overlap) + self.corroboration_weight * min(
                direct,
                winner_overlap,
            )
        elif self.evidence_combination == "winner_reliable_direct":
            reliable_direct = direct * float(np.clip(direct_reliability, 0.0, 1.0))
            direct_for_dominance = reliable_direct
            line_evidence = max(reliable_direct, winner_overlap) + self.corroboration_weight * min(
                reliable_direct,
                winner_overlap,
            )
        else:
            line_evidence = max(
                direct,
                overlap_weighted,
                0.82 * direct + 0.24 * overlap,
            )
        combined = max(line_evidence, self.hidden_evidence_weight * hidden)
        if profile_gain is not None and line_evidence > 0.0:
            support = float(
                np.clip(
                    max(float(profile_gain), 0.0) / max(line_evidence, 1.0e-9),
                    self.minimum_profile_support,
                    1.0,
                )
            )
            combined = max(line_evidence * support, self.hidden_evidence_weight * hidden)
        direct_is_dominant = direct_for_dominance >= max(
            winner_overlap,
            self.hidden_evidence_weight * hidden,
        )
        if phase_snr is not None and combined > 0.0 and direct_is_dominant:
            combined *= self.phase_snr_support(phase_snr)
        if int(residual_line_count) <= 2:
            combined = min(combined, remaining * self.limited_residual_fraction)
        return float(np.clip(combined, 0.0, remaining))

    def phase_snr_support(self, phase_snr: float) -> float:
        """Return a soft confidence factor for a jointly fitted candidate."""

        low = float(self.phase_snr_detection)
        high = max(float(self.phase_snr_full_support), low + 1.0e-9)
        scaled = (max(float(phase_snr), 0.0) - low) / (high - low)
        return float(np.clip(scaled, self.minimum_phase_snr_support, 1.0))

    def reportable_gain(
        self,
        gain: float,
        *,
        dominant_evidence: GainStage | str | None = None,
        profile_gain: float | None = None,
        profile_evaluated: bool = False,
    ) -> float:
        """Return a Gain value only when its evidence is safe to display."""

        value = max(float(gain), 0.0)
        try:
            stage = GainStage(str(dominant_evidence)) if dominant_evidence is not None else None
        except ValueError:
            stage = None
        if (
            profile_evaluated
            and stage is GainStage.OVERLAP
            and max(float(profile_gain or 0.0), 0.0) <= 0.0
        ):
            return 0.0
        return value if value >= float(self.minimum_reported_gain) else 0.0

    def select_stage(self, *, direct_count: int, overlap_count: int) -> GainStage:
        if direct_count >= self.minimum_stage_records:
            return GainStage.DIRECT
        if overlap_count >= self.minimum_stage_records:
            return GainStage.OVERLAP
        return GainStage.HIDDEN

    def is_sparse(self, intensities: Iterable[float]) -> bool:
        strongest = sorted(
            (max(float(value), 0.0) for value in intensities if float(value) > 0.0),
            reverse=True,
        )[:10]
        if len(strongest) < 3:
            return bool(strongest)
        total = sum(strongest)
        if total <= 0.0:
            return False
        return (
            strongest[0] / total >= self.sparse_strongest_fraction
            or sum(strongest[:2]) / total >= self.sparse_two_strongest_fraction
        )

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

    def combine_line_and_profile(
        self,
        *,
        line_gain: float,
        profile_gain: float | None,
        sparse: bool = False,
    ) -> float:
        line_gain = max(float(line_gain), 0.0)
        if line_gain <= 0.0:
            return 0.0
        if profile_gain is None:
            return line_gain
        if sparse and self.sparse_profile_weight > 0.0:
            weight = float(np.clip(self.sparse_profile_weight, 0.0, 1.0))
            return (1.0 - weight) * line_gain + weight * max(float(profile_gain), 0.0)
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


DEFAULT_GAIN_POLICY = GainPolicy(evidence_combination="winner_reliable_direct")


__all__ = ["DEFAULT_GAIN_POLICY", "GainPolicy", "GainStage"]
