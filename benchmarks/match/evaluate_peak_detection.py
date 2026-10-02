from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass

import numpy as np

from xrd_finder.finder.residual_peak_refinement import pseudo_voigt_unit_height
from xrd_finder.services.profile_matched_peak_detector import (
    is_broad_rescue_candidate,
    profile_matched_peak_hypotheses,
)
from xrd_finder.ui.peak_matching import observed_peak_records


@dataclass(frozen=True, slots=True)
class MatchedRescueFeature:
    case_index: int
    truth_position: float
    detected_position: float
    prominence: float
    local_snr: float
    area_snr: float
    width_ratio: float
    profile_match: float
    curvature: float
    centroid_offset: float


@dataclass(frozen=True, slots=True)
class WidthStratumResult:
    label: str
    true_peaks: int
    legacy_recall: float
    matched_recall: float
    union_recall: float
    diagnostic_union_recall: float


@dataclass(frozen=True, slots=True)
class PeakDetectionBenchmarkResult:
    cases: int
    true_peaks: int
    legacy_recall: float
    matched_recall: float
    legacy_precision: float
    matched_precision: float
    legacy_median_seconds: float
    matched_median_seconds: float
    legacy_overlap_recall: float
    matched_overlap_recall: float
    hybrid_recall: float
    diagnostic_union_recall: float
    matched_unique_rescues: int
    accepted_broad_rescues: int
    rescue_features: tuple[MatchedRescueFeature, ...]
    width_strata: tuple[WidthStratumResult, ...]


def run_peak_detection_benchmark(
    *,
    cases: int = 40,
    seed: int = 15036,
) -> PeakDetectionBenchmarkResult:
    """Compare legacy maxima and profile-bank detection on two-phase mixtures."""

    rng = np.random.default_rng(seed)
    legacy_recovered = 0
    matched_recovered = 0
    true_total = 0
    legacy_supported = 0
    matched_supported = 0
    legacy_detected = 0
    matched_detected = 0
    legacy_overlap_recovered = 0
    matched_overlap_recovered = 0
    overlap_total = 0
    hybrid_recovered = 0
    diagnostic_union_recovered = 0
    matched_unique_rescues = 0
    accepted_broad_rescues = 0
    rescue_features: list[MatchedRescueFeature] = []
    legacy_times: list[float] = []
    matched_times: list[float] = []
    stratum_counts = {
        label: [0, 0, 0, 0, 0]
        for label in ("k<1.5", "1.5<=k<2.5", "2.5<=k<3.5", "k>=3.5")
    }
    for case_index in range(max(1, int(cases))):
        x, y, true_peaks, overlap_truth = _synthetic_two_phase_case(rng)
        started = time.perf_counter()
        legacy = observed_peak_records(
            x,
            y,
            limit=80,
            instrument_profile=None,
            sigma_threshold=3.0,
        )
        legacy_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        matched = profile_matched_peak_hypotheses(
            x,
            y,
            fwhm_at=lambda _position: 0.10,
            broadening_scales=(0.7, 1.0, 1.4, 2.0, 2.5, 3.0, 4.0, 5.0),
            sigma_threshold=3.0,
            limit=80,
        )
        matched_times.append(time.perf_counter() - started)
        legacy_positions = [record.two_theta for record in legacy]
        matched_positions = [record.position for record in matched]
        broad_rescue_positions = [
            record.position for record in matched if is_broad_rescue_candidate(record)
        ]
        true_total += len(true_peaks)
        legacy_matches = _matched_pairs(true_peaks, legacy_positions)
        matched_matches = _matched_pairs(true_peaks, matched_positions)
        diagnostic_union_matches = _matched_pairs(
            true_peaks, [*legacy_positions, *matched_positions]
        )
        hybrid_matches = _matched_pairs(
            true_peaks, [*legacy_positions, *broad_rescue_positions]
        )
        legacy_recovered += len(legacy_matches)
        matched_recovered += len(matched_matches)
        legacy_supported += len(legacy_matches)
        matched_supported += len(matched_matches)
        legacy_detected += len(legacy_positions)
        matched_detected += len(matched_positions)
        hybrid_recovered += len(hybrid_matches)
        diagnostic_union_recovered += len(diagnostic_union_matches)
        legacy_truth_indices = {
            truth_index for truth_index, _detected_index in legacy_matches
        }
        matched_truth_indices = {
            truth_index for truth_index, _detected_index in matched_matches
        }
        hybrid_truth_indices = {
            truth_index for truth_index, _detected_index in hybrid_matches
        }
        diagnostic_union_truth_indices = {
            truth_index for truth_index, _detected_index in diagnostic_union_matches
        }
        for truth_index, (_position, width) in enumerate(true_peaks):
            label = _width_stratum(float(width) / 0.10)
            counts = stratum_counts[label]
            counts[0] += 1
            counts[1] += int(truth_index in legacy_truth_indices)
            counts[2] += int(truth_index in matched_truth_indices)
            counts[3] += int(truth_index in hybrid_truth_indices)
            counts[4] += int(truth_index in diagnostic_union_truth_indices)
        for truth_index, detected_index in matched_matches:
            if truth_index in legacy_truth_indices:
                continue
            matched_unique_rescues += 1
            hypothesis = matched[detected_index]
            accepted_broad_rescues += int(is_broad_rescue_candidate(hypothesis))
            centroid_offset = _rescue_centroid_offset(
                x, y, hypothesis.position, hypothesis.effective_fwhm
            )
            rescue_features.append(
                MatchedRescueFeature(
                    case_index=case_index,
                    truth_position=float(true_peaks[truth_index][0]),
                    detected_position=float(hypothesis.position),
                    prominence=float(hypothesis.prominence),
                    local_snr=float(hypothesis.local_snr),
                    area_snr=float(hypothesis.area_snr),
                    width_ratio=float(hypothesis.broadening_scale),
                    profile_match=float(hypothesis.profile_match),
                    curvature=float(hypothesis.curvature),
                    centroid_offset=float(centroid_offset),
                )
            )
        legacy_overlap_recovered += sum(
            1 for truth_index, _detected_index in legacy_matches if truth_index in overlap_truth
        )
        matched_overlap_recovered += sum(
            1 for truth_index, _detected_index in matched_matches if truth_index in overlap_truth
        )
        overlap_total += len(overlap_truth)
    return PeakDetectionBenchmarkResult(
        cases=max(1, int(cases)),
        true_peaks=true_total,
        legacy_recall=legacy_recovered / max(true_total, 1),
        matched_recall=matched_recovered / max(true_total, 1),
        legacy_precision=legacy_supported / max(legacy_detected, 1),
        matched_precision=matched_supported / max(matched_detected, 1),
        legacy_median_seconds=float(np.median(legacy_times)),
        matched_median_seconds=float(np.median(matched_times)),
        legacy_overlap_recall=legacy_overlap_recovered / max(overlap_total, 1),
        matched_overlap_recall=matched_overlap_recovered / max(overlap_total, 1),
        hybrid_recall=hybrid_recovered / max(true_total, 1),
        diagnostic_union_recall=diagnostic_union_recovered / max(true_total, 1),
        matched_unique_rescues=matched_unique_rescues,
        accepted_broad_rescues=accepted_broad_rescues,
        rescue_features=tuple(rescue_features),
        width_strata=tuple(
            WidthStratumResult(
                label=label,
                true_peaks=counts[0],
                legacy_recall=counts[1] / max(counts[0], 1),
                matched_recall=counts[2] / max(counts[0], 1),
                union_recall=counts[3] / max(counts[0], 1),
                diagnostic_union_recall=counts[4] / max(counts[0], 1),
            )
            for label, counts in stratum_counts.items()
        ),
    )


def _rescue_centroid_offset(
    x: np.ndarray,
    residual: np.ndarray,
    position: float,
    fwhm: float,
) -> float:
    width = max(float(fwhm), 0.04)
    left = int(np.searchsorted(x, position - 2.0 * width, side="left"))
    right = int(np.searchsorted(x, position + 2.0 * width, side="right"))
    local_x = np.asarray(x[left:right], dtype=float)
    local_y = np.asarray(residual[left:right], dtype=float)
    if len(local_x) < 7:
        return 0.0
    offset = local_x - float(position)
    scaled = offset / width
    edge = np.abs(scaled) >= 1.1
    if np.count_nonzero(edge) >= 3:
        baseline_coefficients = np.polyfit(offset[edge], local_y[edge], 1)
        baseline = np.polyval(baseline_coefficients, offset)
    else:
        baseline = np.full_like(local_y, float(np.nanmedian(local_y)))
    detrended = local_y - baseline
    positive = np.maximum(detrended, 0.0)
    total = float(np.sum(positive))
    centroid = (
        float(np.dot(local_x, positive) / total)
        if total > 0.0
        else float(position)
    )
    return centroid - float(position)


def _width_stratum(k_value: float) -> str:
    if k_value < 1.5:
        return "k<1.5"
    if k_value < 2.5:
        return "1.5<=k<2.5"
    if k_value < 3.5:
        return "2.5<=k<3.5"
    return "k>=3.5"


def _synthetic_two_phase_case(
    rng,
) -> tuple[
    np.ndarray,
    np.ndarray,
    tuple[tuple[float, float], ...],
    set[int],
]:
    x = np.arange(10.0, 80.0, 0.02)
    common_zero = float(rng.uniform(-0.18, 0.18))
    phase_a_scale = float(1.0 + rng.uniform(-0.0035, 0.0035))
    phase_b_scale = float(1.0 + rng.uniform(-0.0035, 0.0035))
    phase_a_width = float(rng.choice((0.10, 0.13, 0.17)))
    phase_b_width = float(
        rng.choice((0.10, 0.14, 0.18, 0.22, 0.28, 0.32, 0.42, 0.50))
    )
    phase_a = np.sort(rng.uniform(14.0, 72.0, 6))
    phase_b = np.sort(rng.uniform(14.0, 72.0, 5))
    phase_b[0] = phase_a[int(rng.integers(0, len(phase_a)))] + float(
        rng.uniform(0.10, 0.34)
    )
    phase_a = 40.0 + (phase_a - 40.0) * phase_a_scale + common_zero
    phase_b = 40.0 + (phase_b - 40.0) * phase_b_scale + common_zero
    accepted_signal = np.zeros_like(x)
    remaining_signal = np.zeros_like(x)
    truth: list[tuple[float, float]] = []
    accepted_amplitudes = rng.uniform(7.0, 18.0, len(phase_a))
    remaining_amplitudes = rng.uniform(3.5, 10.0, len(phase_b))
    for position, amplitude in zip(phase_a, accepted_amplitudes, strict=True):
        accepted_signal += float(amplitude) * pseudo_voigt_unit_height(
            x, float(position), phase_a_width, 0.35
        )
    for position, amplitude in zip(phase_b, remaining_amplitudes, strict=True):
        remaining_signal += float(amplitude) * pseudo_voigt_unit_height(
            x, float(position), phase_b_width, 0.35
        )
        truth.append((float(position), phase_b_width))
    observed = (
        accepted_signal
        + remaining_signal
        + rng.normal(0.0, 0.75, len(x))
    )
    fitted_accepted = np.zeros_like(x)
    amplitude_scale = float(rng.uniform(0.88, 1.10))
    fitted_width = phase_a_width * float(rng.uniform(0.88, 1.16))
    position_error = float(rng.uniform(-0.025, 0.025))
    for position, amplitude in zip(phase_a, accepted_amplitudes, strict=True):
        fitted_accepted += amplitude_scale * float(amplitude) * pseudo_voigt_unit_height(
            x,
            float(position) + position_error,
            fitted_width,
            0.35,
        )
    signed_residual = observed - fitted_accepted
    overlap_truth = {
        index
        for index, position in enumerate(phase_b)
        if any(
            abs(float(position) - float(accepted_position))
            <= 0.75 * (phase_b_width + phase_a_width)
            for accepted_position in phase_a
        )
    }
    return x, signed_residual, tuple(truth), overlap_truth


def _matched_pairs(
    truth: tuple[tuple[float, float], ...],
    detected: list[float],
) -> list[tuple[int, int]]:
    possible = sorted(
        (abs(candidate - position), truth_index, detected_index)
        for truth_index, (position, width) in enumerate(truth)
        for detected_index, candidate in enumerate(detected)
        if abs(candidate - position) <= max(0.06, width * 0.45)
    )
    used_truth: set[int] = set()
    used_detected: set[int] = set()
    matches: list[tuple[int, int]] = []
    for _delta, truth_index, detected_index in possible:
        if truth_index in used_truth or detected_index in used_detected:
            continue
        used_truth.add(truth_index)
        used_detected.add(detected_index)
        matches.append((truth_index, detected_index))
    return matches




def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=40)
    parser.add_argument("--seed", type=int, default=15036)
    args = parser.parse_args()
    print(json.dumps(asdict(run_peak_detection_benchmark(cases=args.cases, seed=args.seed)), indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "MatchedRescueFeature",
    "PeakDetectionBenchmarkResult",
    "WidthStratumResult",
    "run_peak_detection_benchmark",
]
