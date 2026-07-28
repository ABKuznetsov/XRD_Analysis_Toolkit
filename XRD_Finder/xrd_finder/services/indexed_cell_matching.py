from __future__ import annotations

from dataclasses import dataclass

from xrd_finder.services.refinement_service import RefinementService


IndexedMatch = tuple[int, int, int, float, float]
ObservedPeak = tuple[float, float, float]


@dataclass(frozen=True)
class IndexedCellMatchingPolicy:
    """Policy for preparing multi-phase hkl observations for cell refinement."""

    direct_minimum_weight: float = 6.0
    direct_maximum_weight: float = 100.0
    direct_per_peak_limit: int = 2
    overlap_weight_multiplier: float = 0.18
    overlap_minimum_weight: float = 1.0
    overlap_maximum_weight: float = 18.0
    overlap_per_peak_limit: int = 1


@dataclass(slots=True)
class PreparedIndexedMatches:
    matches: list[IndexedMatch]
    direct_matches_to_claim: list[IndexedMatch]


class IndexedCellMatchingService:
    """Prepare direct and overlapping observations without UI dependencies."""

    def __init__(
        self,
        refinement_service: RefinementService,
        policy: IndexedCellMatchingPolicy | None = None,
    ) -> None:
        self.refinement_service = refinement_service
        self.policy = policy or IndexedCellMatchingPolicy()

    def prepare_phase_matches(
        self,
        *,
        phase_id: str,
        phase_name: str,
        structure,
        wavelength: float,
        direct_matches: list[IndexedMatch],
        overlapping_matches: list[IndexedMatch],
        observed_peaks: list[ObservedPeak],
        available_observed_peaks: list[ObservedPeak],
    ) -> PreparedIndexedMatches:
        direct = self.refinement_service.weight_indexed_matches(
            direct_matches,
            minimum=self.policy.direct_minimum_weight,
            maximum=self.policy.direct_maximum_weight,
        )
        direct = self.refinement_service.compact_indexed_matches_by_observed(
            direct,
            available_observed_peaks,
            per_peak_limit=self.policy.direct_per_peak_limit,
            tolerance_factor=0.9,
            minimum_tolerance=0.06,
            maximum_tolerance=0.30,
        )
        overlaps = self.refinement_service.weight_indexed_matches(
            overlapping_matches,
            multiplier=self.policy.overlap_weight_multiplier,
            minimum=self.policy.overlap_minimum_weight,
            maximum=self.policy.overlap_maximum_weight,
        )
        overlaps = self.refinement_service.compact_indexed_matches_by_observed(
            overlaps,
            observed_peaks,
            per_peak_limit=self.policy.overlap_per_peak_limit,
            tolerance_factor=1.2,
            minimum_tolerance=0.08,
            maximum_tolerance=0.36,
        )

        provisional = self._fit(
            phase_id=phase_id,
            phase_name=phase_name,
            structure=structure,
            wavelength=wavelength,
            matches=direct,
        )
        if provisional.success:
            accepted_overlaps = self._consistent(
                cell=provisional.refined_cell,
                matches=overlaps,
                observed_peaks=observed_peaks,
                wavelength=wavelength,
            )
            phase_matches = direct + accepted_overlaps
        else:
            phase_matches = self._matches_from_overlap_seed(
                phase_id=phase_id,
                phase_name=phase_name,
                structure=structure,
                wavelength=wavelength,
                direct=direct,
                overlaps=overlaps,
                observed_peaks=observed_peaks,
            )

        final_fit = self._fit(
            phase_id=phase_id,
            phase_name=phase_name,
            structure=structure,
            wavelength=wavelength,
            matches=phase_matches,
        )
        validation_cell = final_fit.refined_cell if final_fit.success else structure.cell
        validated = self._consistent(
            cell=validation_cell,
            matches=phase_matches,
            observed_peaks=observed_peaks,
            wavelength=wavelength,
        )
        if validated:
            phase_matches = validated
        validated_direct = self._consistent(
            cell=validation_cell,
            matches=direct,
            observed_peaks=observed_peaks,
            wavelength=wavelength,
        )
        return PreparedIndexedMatches(
            matches=phase_matches,
            direct_matches_to_claim=validated_direct,
        )

    def _matches_from_overlap_seed(
        self,
        *,
        phase_id: str,
        phase_name: str,
        structure,
        wavelength: float,
        direct: list[IndexedMatch],
        overlaps: list[IndexedMatch],
        observed_peaks: list[ObservedPeak],
    ) -> list[IndexedMatch]:
        overlap_seed = self.refinement_service.cell_consistent_indexed_matches(
            cell=structure.cell,
            indexed_matches=overlaps,
            observed_peaks=observed_peaks,
            wavelength=wavelength,
            tolerance_factor=2.2,
            minimum_tolerance=0.18,
            maximum_tolerance=0.60,
        )
        trial = self._fit(
            phase_id=phase_id,
            phase_name=phase_name,
            structure=structure,
            wavelength=wavelength,
            matches=direct + overlap_seed,
        )
        if not trial.success:
            return direct
        retained_direct = self._consistent(
            cell=trial.refined_cell,
            matches=direct,
            observed_peaks=observed_peaks,
            wavelength=wavelength,
        )
        if len(retained_direct) != len(direct):
            return direct
        accepted_overlaps = self._consistent(
            cell=trial.refined_cell,
            matches=overlaps,
            observed_peaks=observed_peaks,
            wavelength=wavelength,
        )
        return direct + accepted_overlaps

    def _fit(self, *, phase_id, phase_name, structure, wavelength, matches):
        return self.refinement_service.fit_indexed_cell(
            phase_id=phase_id,
            phase_name=phase_name,
            structure=structure,
            wavelength=wavelength,
            indexed_matches=matches,
        )

    def _consistent(self, *, cell, matches, observed_peaks, wavelength):
        return self.refinement_service.cell_consistent_indexed_matches(
            cell=cell,
            indexed_matches=matches,
            observed_peaks=observed_peaks,
            wavelength=wavelength,
        )
