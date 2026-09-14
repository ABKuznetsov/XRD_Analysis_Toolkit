from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class GainEvidence:
    accepted: bool
    factor: float
    delta_bic: float
    testable_lines: int
    supported_lines: int
    independent_lines: int
    missing_lines: int
    strongest_independent_snr: float


def evaluate_gain_evidence(
    *,
    x: np.ndarray,
    target: np.ndarray,
    model_before: np.ndarray,
    model_after: np.ndarray,
    candidate_curve: np.ndarray,
    peak_positions: np.ndarray,
    peak_amplitudes: np.ndarray,
    selected_peak_positions: np.ndarray,
    fwhm: float,
    stage: str,
    noise_sigma: float | None = None,
    sigma_threshold: float = 3.0,
) -> GainEvidence:
    x_values = np.asarray(x, dtype=float)
    observed = np.asarray(target, dtype=float)
    before = np.asarray(model_before, dtype=float)
    after = np.asarray(model_after, dtype=float)
    candidate = np.asarray(candidate_curve, dtype=float)
    if (
        len(x_values) < 5
        or len(observed) != len(x_values)
        or len(before) != len(x_values)
        or len(after) != len(x_values)
        or len(candidate) != len(x_values)
        or float(np.nanmax(candidate, initial=0.0)) <= 0.0
    ):
        return _empty_evidence()

    finite = (
        np.isfinite(x_values)
        & np.isfinite(observed)
        & np.isfinite(before)
        & np.isfinite(after)
        & np.isfinite(candidate)
    )
    if np.count_nonzero(finite) < 5:
        return _empty_evidence()

    residual_before = observed - before
    residual_after = observed - after
    estimated_sigma = estimate_noise_sigma(residual_before[finite])
    global_sigma = max(
        float(noise_sigma) if noise_sigma is not None and np.isfinite(noise_sigma) else 0.0,
        estimated_sigma,
        1.0e-9,
    )
    amplitude_floor = max(global_sigma * float(sigma_threshold), 1.0e-9)
    tolerance = max(0.14, min(0.62, max(float(fwhm), 0.05) * 1.35))
    line_positions = _merge_peak_positions(
        x_values,
        np.asarray(peak_positions, dtype=float),
        np.asarray(peak_amplitudes, dtype=float),
        merge_tolerance=max(0.08, tolerance * 0.55),
    )
    if not line_positions:
        return _empty_evidence()

    selected_positions = np.asarray(selected_peak_positions, dtype=float)
    selected_positions = np.sort(selected_positions[np.isfinite(selected_positions)])
    signal_curve = residual_before if stage == "direct" else observed
    testable = 0
    supported = 0
    independent = 0
    independent_testable = 0
    missing = 0
    independent_snrs: list[float] = []
    evidence_positions: list[tuple[float, float, bool]] = []

    for line_position, predicted_height in line_positions:
        local_sigma = _local_noise_sigma(
            x_values,
            residual_before,
            line_position,
            fwhm=max(float(fwhm), 0.05),
            fallback=global_sigma,
        )
        threshold = max(local_sigma * float(sigma_threshold), amplitude_floor * 0.55)
        if predicted_height < threshold:
            continue
        testable += 1

        left = int(np.searchsorted(x_values, line_position - tolerance, side="left"))
        right = int(np.searchsorted(x_values, line_position + tolerance, side="right"))
        if right <= left:
            continue
        local_values = signal_curve[left:right]
        if not len(local_values):
            continue
        local_index = int(np.nanargmax(local_values))
        signal_height = max(float(local_values[local_index]), 0.0)
        signal_position = float(x_values[left + local_index])
        line_snr = signal_height / max(local_sigma, 1.0e-9)
        position_ok = abs(signal_position - line_position) <= tolerance
        amplitude_ok = signal_height >= max(
            local_sigma * 2.5,
            min(predicted_height * 0.42, local_sigma * 4.5),
        )
        # A residual at a selected phase line can be caused by texture,
        # microstructure or imperfect profile width. It is therefore not
        # independent evidence for an additional phase.
        selected_overlap = _nearest_delta(selected_positions, line_position) <= tolerance
        evidence_positions.append((line_position, predicted_height, not selected_overlap))
        if not selected_overlap:
            independent_testable += 1
        if position_ok and amplitude_ok:
            supported += 1
            if not selected_overlap:
                independent += 1
                independent_snrs.append(line_snr)
        elif not selected_overlap:
            missing += 1

    if testable == 0 or not evidence_positions:
        return _empty_evidence()

    mask = np.zeros(len(x_values), dtype=bool)
    profile_half_width = max(tolerance, max(float(fwhm), 0.05) * 3.5)
    for position, amplitude, is_independent in evidence_positions:
        if stage == "direct" and not is_independent:
            continue
        if float(amplitude) < amplitude_floor * 0.55:
            continue
        left = int(np.searchsorted(x_values, position - profile_half_width, side="left"))
        right = int(np.searchsorted(x_values, position + profile_half_width, side="right"))
        mask[left:right] = True
    mask &= finite
    delta_bic = _delta_bic(residual_before[mask], residual_after[mask])

    if stage == "direct":
        support_fraction = independent / max(independent_testable, 1)
        missing_fraction = missing / max(independent_testable, 1)
    else:
        support_fraction = supported / max(testable, 1)
        missing_fraction = missing / max(testable, 1)
    strongest_independent_snr = max(independent_snrs, default=0.0)
    if stage == "direct":
        # A single line can satisfy an analytical LoD check, but it is not
        # specific enough for an automated search across a large database.
        line_gate = independent >= 2 and supported >= 2
        bic_gate = delta_bic >= 2.0
    else:
        line_gate = supported >= 2
        bic_gate = delta_bic >= 10.0
    accepted = bool(
        line_gate
        and bic_gate
        and support_fraction >= 0.42
        and missing_fraction <= 0.55
    )
    if not accepted:
        return GainEvidence(
            accepted=False,
            factor=0.0,
            delta_bic=float(delta_bic),
            testable_lines=testable,
            supported_lines=supported,
            independent_lines=independent,
            missing_lines=missing,
            strongest_independent_snr=float(strongest_independent_snr),
        )

    bic_factor = float(np.clip(math.log1p(max(delta_bic, 0.0)) / math.log(26.0), 0.30, 1.0))
    missing_factor = max(0.15, 1.0 - 1.25 * missing_fraction)
    independence_factor = 1.0 if independent >= 2 else 0.82
    factor = support_fraction * missing_factor * bic_factor * independence_factor
    return GainEvidence(
        accepted=True,
        factor=float(np.clip(factor, 0.05, 1.0)),
        delta_bic=float(delta_bic),
        testable_lines=testable,
        supported_lines=supported,
        independent_lines=independent,
        missing_lines=missing,
        strongest_independent_snr=float(strongest_independent_snr),
    )


def _empty_evidence() -> GainEvidence:
    return GainEvidence(
        accepted=False,
        factor=0.0,
        delta_bic=float("-inf"),
        testable_lines=0,
        supported_lines=0,
        independent_lines=0,
        missing_lines=0,
        strongest_independent_snr=0.0,
    )


def estimate_noise_sigma(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) < 3:
        return 1.0
    differences = np.diff(finite)
    center = float(np.nanmedian(differences))
    mad = float(np.nanmedian(np.abs(differences - center)))
    if mad > 0.0:
        return max(1.4826 * mad / math.sqrt(2.0), 1.0e-9)
    center = float(np.nanmedian(finite))
    mad = float(np.nanmedian(np.abs(finite - center)))
    return max(1.4826 * mad, 1.0e-9)


def _local_noise_sigma(
    x: np.ndarray,
    residual: np.ndarray,
    position: float,
    *,
    fwhm: float,
    fallback: float,
) -> float:
    half_width = max(1.0, float(fwhm) * 8.0)
    left = int(np.searchsorted(x, position - half_width, side="left"))
    right = int(np.searchsorted(x, position + half_width, side="right"))
    local = np.asarray(residual[left:right], dtype=float)
    sigma = estimate_noise_sigma(local) if len(local) >= 7 else float(fallback)
    return float(np.clip(sigma, max(float(fallback) * 0.65, 1.0e-9), max(float(fallback) * 2.5, 1.0e-9)))


def _merge_peak_positions(
    x: np.ndarray,
    positions: np.ndarray,
    amplitudes: np.ndarray,
    *,
    merge_tolerance: float,
) -> list[tuple[float, float]]:
    x_min = float(np.nanmin(x))
    x_max = float(np.nanmax(x))
    usable: list[tuple[float, float]] = []
    for position, amplitude in zip(positions, amplitudes, strict=False):
        if not np.isfinite(position) or position < x_min or position > x_max:
            continue
        usable.append((float(position), max(float(amplitude), 0.0)))
    usable.sort(key=lambda item: item[0])
    merged: list[tuple[float, float]] = []
    for position, amplitude in usable:
        if merged and position - merged[-1][0] <= merge_tolerance:
            if amplitude > merged[-1][1]:
                merged[-1] = (position, amplitude)
            continue
        merged.append((position, amplitude))
    merged.sort(key=lambda item: item[1], reverse=True)
    return merged[:42]


def _local_max(
    x: np.ndarray,
    values: np.ndarray,
    position: float,
    half_width: float,
) -> float:
    left = int(np.searchsorted(x, position - half_width, side="left"))
    right = int(np.searchsorted(x, position + half_width, side="right"))
    if right <= left:
        return 0.0
    return max(float(np.nanmax(values[left:right])), 0.0)


def _nearest_delta(sorted_values: np.ndarray, value: float) -> float:
    if not len(sorted_values):
        return float("inf")
    index = int(np.searchsorted(sorted_values, value, side="left"))
    deltas: list[float] = []
    if index < len(sorted_values):
        deltas.append(abs(float(sorted_values[index]) - value))
    if index > 0:
        deltas.append(abs(float(sorted_values[index - 1]) - value))
    return min(deltas) if deltas else float("inf")


def _delta_bic(residual_before: np.ndarray, residual_after: np.ndarray) -> float:
    before = np.asarray(residual_before, dtype=float)
    after = np.asarray(residual_after, dtype=float)
    finite = np.isfinite(before) & np.isfinite(after)
    count = int(np.count_nonzero(finite))
    if count < 5:
        return float("-inf")
    rss_before = float(np.dot(before[finite], before[finite]))
    rss_after = float(np.dot(after[finite], after[finite]))
    if rss_before <= 1.0e-12:
        return float("-inf")
    return float(
        count * math.log(rss_before / max(rss_after, 1.0e-12))
        - math.log(count)
    )
