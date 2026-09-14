from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class FingerprintMatchResult:
    score: float = 0.0
    pair_score: float = 0.0
    line_coverage: float = 0.0
    observed_coverage: float = 0.0
    matched_lines: int = 0
    total_lines: int = 0
    q_scale: float = 1.0


def fingerprint_match_score(
    reference_peaks,
    observed_records: list[tuple[float, float]],
    *,
    wavelength: float,
    max_reference_lines: int = 64,
    max_observed_lines: int = 48,
    pair_ratio_tolerance: float = 0.014,
    line_tolerance_two_theta: float = 0.55,
) -> FingerprintMatchResult:
    """Score a candidate by a simple two-stage stick-line comparison.

    Stage 1 asks whether the candidate explains the strongest observed peaks.
    Stage 2 asks whether the candidate's own strong lines are supported by the
    observed pattern. This keeps broad auto-search understandable: a phase with
    a few accidental hits no longer scores well if it misses the observed anchors.
    """

    ref_lines = _reference_lines(reference_peaks, max_reference_lines)
    obs_lines = _observed_lines(observed_records, max_observed_lines, wavelength)
    if len(ref_lines) < 3 or len(obs_lines) < 3:
        return FingerprintMatchResult(total_lines=len(ref_lines))

    q_scale, seed_weight = _direct_scale_estimate(ref_lines, obs_lines, tolerance_two_theta=line_tolerance_two_theta)
    coverage, matched = _scaled_line_coverage(
        ref_lines,
        obs_lines,
        q_scale,
        wavelength,
        tolerance_two_theta=line_tolerance_two_theta,
    )
    observed_coverage, observed_matched = _observed_anchor_coverage(
        ref_lines,
        obs_lines,
        q_scale,
        tolerance_two_theta=line_tolerance_two_theta,
    )
    anchor_count = min(10, len(obs_lines))
    anchor_fraction = observed_matched / max(anchor_count, 1)
    enough_lines = min(min(matched, observed_matched) / 8.0, 1.0)
    seed_bonus = min(seed_weight / 4.0, 1.0)
    score = 100.0 * (
        0.62 * observed_coverage
        + 0.25 * coverage
        + 0.08 * enough_lines
        + 0.05 * seed_bonus
    )
    if observed_matched < 3 or anchor_fraction < 0.22:
        score = min(score, 28.0)
    elif observed_matched < 4 or anchor_fraction < 0.32:
        score = min(score, 48.0)
    elif matched < 3:
        score = min(score, 52.0)
    return FingerprintMatchResult(
        score=float(np.clip(score, 0.0, 100.0)),
        pair_score=seed_bonus,
        line_coverage=coverage,
        observed_coverage=observed_coverage,
        matched_lines=matched,
        total_lines=len(ref_lines),
        q_scale=float(q_scale),
    )


@dataclass(frozen=True, slots=True)
class _Line:
    two_theta: float
    q: float
    weight: float


@dataclass(frozen=True, slots=True)
class _LinePair:
    left: _Line
    right: _Line
    log_q_ratio: float
    log_intensity_ratio: float
    bin_key: int
    weight: float


def _reference_lines(peaks, limit: int) -> list[_Line]:
    lines = []
    for peak in peaks:
        try:
            two_theta = float(getattr(peak, "two_theta", 0.0) or 0.0)
            intensity = max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0)
        except Exception:
            continue
        if intensity < 1.0 or not 5.0 <= two_theta <= 120.0:
            continue
        q = _q_from_two_theta(two_theta)
        if q > 0:
            lines.append(_Line(two_theta=two_theta, q=q, weight=intensity))
    lines.sort(key=lambda line: line.weight, reverse=True)
    strongest = lines[: max(int(limit), 1)]
    max_weight = max((line.weight for line in strongest), default=1.0)
    normalized = [_Line(line.two_theta, line.q, max(line.weight / max_weight, 0.01)) for line in strongest]
    return sorted(normalized, key=lambda line: line.q)


def _observed_lines(records: list[tuple[float, float]], limit: int, wavelength: float) -> list[_Line]:
    lines = []
    for record in records:
        try:
            two_theta_value = getattr(record, "two_theta", None)
            two_theta = float(two_theta_value if two_theta_value is not None else record[0])
            strength_value = getattr(record, "height", None)
            if strength_value is None:
                strength_value = getattr(record, "area", None)
            strength = max(float(strength_value if strength_value is not None else record[1]), 0.0)
        except Exception:
            continue
        if strength <= 0.0 or not 5.0 <= two_theta <= 120.0:
            continue
        q = _q_from_two_theta(two_theta)
        if q > 0:
            lines.append(_Line(two_theta=two_theta, q=q, weight=strength))
    lines.sort(key=lambda line: line.weight, reverse=True)
    strongest = lines[: max(int(limit), 1)]
    max_weight = max((line.weight for line in strongest), default=1.0)
    normalized = [_Line(line.two_theta, line.q, max(line.weight / max_weight, 0.01)) for line in strongest]
    return sorted(normalized, key=lambda line: line.q)


def _line_pairs(lines: list[_Line], bin_width: float) -> list[_LinePair]:
    pairs = []
    for left_index, left in enumerate(lines):
        neighbors = lines[left_index + 1 : left_index + 9]
        for right in neighbors:
            if left.q <= 0 or right.q <= left.q:
                continue
            log_q_ratio = math.log(right.q / left.q)
            if log_q_ratio <= 0.004:
                continue
            log_intensity_ratio = math.log(max(right.weight, 1.0e-6) / max(left.weight, 1.0e-6))
            weight = math.sqrt(max(left.weight, 0.0) * max(right.weight, 0.0))
            pairs.append(
                _LinePair(
                    left=left,
                    right=right,
                    log_q_ratio=log_q_ratio,
                    log_intensity_ratio=log_intensity_ratio,
                    bin_key=int(round(log_q_ratio / max(bin_width, 1.0e-6))),
                    weight=weight,
                )
            )
    return pairs


def _best_scale_cluster(votes: list[tuple[float, float]]) -> tuple[float, float]:
    if not votes:
        return 1.0, 0.0
    ordered = sorted(votes, key=lambda item: item[0])
    best_center = ordered[0][0]
    best_weight = 0.0
    half_width = 0.004
    for center, _weight in ordered:
        cluster = [(scale, weight) for scale, weight in ordered if abs(scale - center) <= half_width]
        total = sum(weight for _scale, weight in cluster)
        if total > best_weight:
            best_weight = total
            best_center = sum(scale * weight for scale, weight in cluster) / max(total, 1.0e-12)
    return float(best_center), float(best_weight)


def _direct_scale_estimate(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    *,
    tolerance_two_theta: float,
) -> tuple[float, float]:
    if not ref_lines or not obs_lines:
        return 1.0, 0.0
    votes = []
    observed_two_theta = np.asarray([line.two_theta for line in obs_lines], dtype=float)
    for ref in sorted(ref_lines, key=lambda line: line.weight, reverse=True)[:24]:
        index = int(np.argmin(np.abs(observed_two_theta - ref.two_theta)))
        obs = obs_lines[index]
        delta = abs(float(obs.two_theta) - ref.two_theta)
        if delta > tolerance_two_theta:
            continue
        scale = obs.q / max(ref.q, 1.0e-12)
        if not 0.965 <= scale <= 1.035:
            continue
        quality = _flat_window_quality(delta, tolerance_two_theta)
        intensity_quality = _relative_intensity_quality(ref.weight, obs.weight)
        if intensity_quality <= 0.08:
            continue
        votes.append((scale, ref.weight * max(obs.weight, 0.05) * (0.35 + 0.65 * quality) * intensity_quality))
    return _best_scale_cluster(votes) if votes else (1.0, 0.0)


def _scaled_line_coverage(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    q_scale: float,
    wavelength: float,
    *,
    tolerance_two_theta: float,
) -> tuple[float, int]:
    if not ref_lines or not obs_lines:
        return 0.0, 0
    total_weight = sum(line.weight for line in ref_lines)
    matched_weight = 0.0
    matched = 0
    for ref in ref_lines:
        scaled_two_theta = _two_theta_from_q(ref.q * q_scale)
        if scaled_two_theta is None:
            continue
        quality = _best_line_match_quality(
            scaled_two_theta,
            ref.weight,
            obs_lines,
            tolerance_two_theta=tolerance_two_theta,
        )
        if quality <= 0.0:
            continue
        matched += 1
        matched_weight += ref.weight * quality
    return float(np.clip(matched_weight / max(total_weight, 1.0e-12), 0.0, 1.0)), matched


def _observed_anchor_coverage(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    q_scale: float,
    *,
    tolerance_two_theta: float,
    limit: int = 16,
) -> tuple[float, int]:
    """Estimate how well a candidate explains the strongest observed lines."""

    if not ref_lines or not obs_lines:
        return 0.0, 0
    scaled_reference = []
    reference_weights = []
    for ref in ref_lines:
        two_theta = _two_theta_from_q(ref.q * q_scale)
        if two_theta is not None:
            scaled_reference.append(two_theta)
            reference_weights.append(ref.weight)
    if not scaled_reference:
        return 0.0, 0
    reference_lines = [
        _Line(two_theta=two_theta, q=0.0, weight=weight)
        for two_theta, weight in zip(scaled_reference, reference_weights, strict=False)
    ]
    anchors = sorted(obs_lines, key=lambda line: line.weight, reverse=True)[: max(int(limit), 1)]
    total_weight = sum(line.weight for line in anchors)
    matched_weight = 0.0
    matched = 0
    texture_like_misses = 0
    for obs in anchors:
        quality = _best_line_match_quality(
            obs.two_theta,
            obs.weight,
            reference_lines,
            tolerance_two_theta=tolerance_two_theta,
        )
        if quality <= 0.0:
            continue
        if quality < 0.22 and obs.weight >= 0.30:
            texture_like_misses += 1
            if texture_like_misses > 2:
                quality *= 0.35
        matched += 1
        matched_weight += obs.weight * quality
    return float(np.clip(matched_weight / max(total_weight, 1.0e-12), 0.0, 1.0)), matched


def _relative_intensity_quality(reference_weight: float, observed_weight: float) -> float:
    reference = max(float(reference_weight), 1.0e-6)
    observed = max(float(observed_weight), 1.0e-6)
    ratio = min(reference, observed) / max(reference, observed)
    if observed >= 0.55 and reference < 0.08:
        return 0.10
    if observed >= 0.30 and reference < 0.04:
        return 0.14
    return float(np.clip(0.18 + 0.82 * (ratio ** 0.42), 0.0, 1.0))


def _best_line_match_quality(
    target_two_theta: float,
    target_weight: float,
    candidate_lines: list[_Line],
    *,
    tolerance_two_theta: float,
) -> float:
    best_quality = 0.0
    for line in candidate_lines:
        delta = abs(float(line.two_theta) - float(target_two_theta))
        if delta > tolerance_two_theta:
            continue
        position_quality = _flat_window_quality(delta, tolerance_two_theta)
        intensity_quality = _relative_intensity_quality(line.weight, target_weight)
        best_quality = max(best_quality, (0.35 + 0.65 * position_quality) * intensity_quality)
    return float(np.clip(best_quality, 0.0, 1.0))


def _flat_window_quality(delta_two_theta: float, tolerance_two_theta: float) -> float:
    tolerance = max(float(tolerance_two_theta), 1.0e-6)
    plateau = min(0.20, tolerance * 0.45)
    delta = abs(float(delta_two_theta))
    if delta <= plateau:
        return 1.0
    return float(np.clip(1.0 - (delta - plateau) / max(tolerance - plateau, 1.0e-6), 0.0, 1.0))


def _q_from_two_theta(two_theta: float) -> float:
    theta = math.radians(float(two_theta) / 2.0)
    return math.sin(theta)


def _two_theta_from_q(q_value: float) -> float | None:
    argument = float(q_value)
    if not 0.0 < argument < 1.0:
        return None
    return math.degrees(2.0 * math.asin(argument))
