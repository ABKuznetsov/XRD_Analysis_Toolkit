from __future__ import annotations

import math
from pathlib import Path

from xrd_finder.finder.models import FinderCandidateInput, FinderInput
from xrd_finder.finder.service import FinderService
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.services.refinement_service import RefinementService


DATA_ROOT = Path(
    r"C:\Users\Artem\Desktop\данные аскара\рфа по Ca-Sr5(PO4)3Cl Eu"
    r"\Ca5-xSrx(PO4)3Cl 0.05 Eu 760С 12h"
)
PATTERNS = [
    "Ca5(PO4)3Cl 0.05Eu 740C.txt",
    "Sr1Ca4(PO4)3Cl 0.05Eu 760C 12h.txt",
    "Sr2Ca3(PO4)3Cl 0.05Eu 760C 12h.txt",
    "Sr3Ca2(PO4)3Cl 0.05Eu 760C 12h.txt",
    "Sr4Ca1(PO4)3Cl 0.05Eu 760C 12h.txt",
    "Sr5(PO4)3Cl 0.05Eu 760C 2 batch.txt",
]
REFERENCE_CIF = Path(
    r"C:\Users\Artem\AppData\Local\Sci\apps\xrd_phase_finder"
    r"\data\cod_cache\cif\1010916.cif"
)
WAVELENGTH = 1.5406


def cell_volume(cell) -> float:
    alpha = math.radians(float(cell.alpha))
    beta = math.radians(float(cell.beta))
    gamma = math.radians(float(cell.gamma))
    factor = (
        1.0
        + 2.0 * math.cos(alpha) * math.cos(beta) * math.cos(gamma)
        - math.cos(alpha) ** 2
        - math.cos(beta) ** 2
        - math.cos(gamma) ** 2
    )
    return float(cell.a) * float(cell.b) * float(cell.c) * math.sqrt(max(factor, 0.0))


def indexed_matches(candidate_result, result, refinement, structure):
    peak_positions = list(candidate_result.peak_reference_two_theta or candidate_result.peak_two_theta)
    h_values = list(candidate_result.peak_h)
    k_values = list(candidate_result.peak_k)
    l_values = list(candidate_result.peak_l)
    intensities = list(candidate_result.peak_intensity)
    matches = []
    for reference, observed in zip(
        candidate_result.matched_reference_two_theta,
        candidate_result.matched_observed_two_theta,
    ):
        nearest = min(
            range(len(peak_positions)),
            key=lambda index: abs(float(peak_positions[index]) - float(reference)),
        )
        if abs(float(peak_positions[nearest]) - float(reference)) > 0.25:
            continue
        hkl = (
            int(round(float(h_values[nearest]))),
            int(round(float(k_values[nearest]))),
            int(round(float(l_values[nearest]))),
        )
        if hkl == (0, 0, 0):
            continue
        matches.append(
            (
                *hkl,
                float(observed) - float(result.global_zero_shift),
                max(float(intensities[nearest]), 1.0),
            )
        )
    references = [
        (
            int(round(float(h_values[index]))),
            int(round(float(k_values[index]))),
            int(round(float(l_values[index]))),
            float(position),
            max(float(intensities[index]), 1.0),
        )
        for index, position in enumerate(peak_positions)
        if index < len(h_values) and index < len(k_values) and index < len(l_values)
    ]
    observed_peaks = [
        (float(peak.two_theta), float(peak.intensity), float(peak.fwhm))
        for peak in result.observed_peaks
    ]
    return refinement.complete_direct_indexed_matches(
        structure=structure,
        indexed_matches=matches,
        reference_peaks=references,
        observed_peaks=observed_peaks,
        global_zero_shift=float(result.global_zero_shift),
    )


def main() -> None:
    phase, structure = create_phase_from_cif(REFERENCE_CIF)
    finder = FinderService()
    refinement = RefinementService()
    print("sample\tmatches\ta\tc\tvolume\trms\tmax\tdirect")
    for filename in PATTERNS:
        result = finder.run(
            FinderInput(
                pattern_path=str(DATA_ROOT / filename),
                candidates=[
                    FinderCandidateInput(
                        cif_path=str(REFERENCE_CIF),
                        entry_id="1010916",
                        name=phase.name,
                        formula=phase.formula,
                        source="COD",
                        structure=structure,
                    )
                ],
                wavelength=WAVELENGTH,
                snap_peak_positions=False,
            )
        )
        candidate = result.candidates[0]
        matches = indexed_matches(candidate, result, refinement, structure)
        fit = refinement.fit_indexed_cell(
            phase_id="1010916",
            phase_name=phase.name,
            structure=structure,
            wavelength=WAVELENGTH,
            indexed_matches=matches,
        )
        cell = fit.refined_cell
        direct = []
        variable_names = refinement._cell_variable_names(structure.cell, structure=structure)
        for h, k, l, observed_two_theta, _weight in matches:
            variable = refinement._isolated_cell_variable(
                structure.cell,
                variable_names,
                (h, k, l),
            )
            if variable:
                direct.append(f"{variable}:{h}{k}{l}@{observed_two_theta:.3f}")
        print(
            f"{filename}\t{fit.matched_peaks}\t{cell.a:.5f}\t{cell.c:.5f}\t"
            f"{cell_volume(cell):.3f}\t{fit.rms_delta_two_theta:.4f}\t"
            f"{fit.max_delta_two_theta:.4f}\t{','.join(direct)}"
        )


if __name__ == "__main__":
    main()
