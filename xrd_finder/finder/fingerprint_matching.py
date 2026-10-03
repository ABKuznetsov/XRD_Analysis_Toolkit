from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class MatchWeights:
    observed_coverage: float
    reference_coverage: float
    sufficient_lines: float
    alignment_seed: float

    def __post_init__(self) -> None:
        values = (
            self.observed_coverage,
            self.reference_coverage,
            self.sufficient_lines,
            self.alignment_seed,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("Match weights must be finite and non-negative.")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1.0e-9):
            raise ValueError("Match weights must sum to one.")

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (
            self.observed_coverage,
            self.reference_coverage,
            self.sufficient_lines,
            self.alignment_seed,
        )


DEFAULT_MATCH_WEIGHTS = MatchWeights(0.44, 0.43, 0.08, 0.05)
MATCH_OBSERVED_LINE_LIMIT = 48
MATCH_REFERENCE_LINE_LIMIT = 64


@dataclass(frozen=True, slots=True)
class FingerprintMatchFeatures:
    observed_coverage: float = 0.0
    reference_coverage: float = 0.0
    sufficient_lines: float = 0.0
    alignment_seed: float = 0.0
    observed_matched: int = 0
    reference_matched: int = 0
    anchor_count: int = 0


def apply_match_weights(
    features: FingerprintMatchFeatures,
    weights: MatchWeights = DEFAULT_MATCH_WEIGHTS,
) -> float:
    score = 100.0 * (
        weights.observed_coverage * features.observed_coverage
        + weights.reference_coverage * features.reference_coverage
        + weights.sufficient_lines * features.sufficient_lines
        + weights.alignment_seed * features.alignment_seed
    )
    anchor_fraction = features.observed_matched / max(features.anchor_count, 1)
    if features.observed_matched < 3 or anchor_fraction < 0.22:
        score = min(score, 28.0)
    elif features.observed_matched < 4 or anchor_fraction < 0.32:
        score = min(score, 48.0)
    elif features.reference_matched < 3:
        score = min(score, 52.0)
    return float(np.clip(score, 0.0, 100.0))


@dataclass(frozen=True, slots=True)
class FingerprintMatchResult:
    score: float = 0.0
    pair_score: float = 0.0
    line_coverage: float = 0.0
    observed_coverage: float = 0.0
    matched_lines: int = 0
    total_lines: int = 0
    q_scale: float = 1.0
    position_scale: float = 1.0
    zero_shift: float = 0.0
    profile_fwhm: float = 0.18
    features: FingerprintMatchFeatures = FingerprintMatchFeatures()


def fingerprint_match_score(
    reference_peaks,
    observed_records: list[tuple[float, float]],
    *,
    wavelength: float,
    max_reference_lines: int = MATCH_REFERENCE_LINE_LIMIT,
    max_observed_lines: int = MATCH_OBSERVED_LINE_LIMIT,
    pair_ratio_tolerance: float = 0.014,
    line_tolerance_two_theta: float = 0.55,
    refine_alignment: bool = True,
    weights: MatchWeights = DEFAULT_MATCH_WEIGHTS,
    adaptive_line_tolerance: bool = False,
    fixed_zero_shift: float | None = None,
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
    if adaptive_line_tolerance:
        line_tolerance_two_theta = _adaptive_tolerance(
            obs_lines,
            fallback=line_tolerance_two_theta,
        )

    if refine_alignment:
        position_scale, zero_shift, seed_weight = _best_position_alignment(
            ref_lines,
            obs_lines,
            tolerance_two_theta=line_tolerance_two_theta,
            fixed_zero_shift=fixed_zero_shift,
        )
        q_scale = _representative_q_scale(ref_lines, position_scale, zero_shift)
        coverage, matched = _scaled_line_coverage(
            ref_lines,
            obs_lines,
            position_scale,
            zero_shift,
            wavelength,
            tolerance_two_theta=line_tolerance_two_theta,
        )
        observed_coverage, observed_matched = _observed_anchor_coverage(
            ref_lines,
            obs_lines,
            position_scale,
            zero_shift,
            tolerance_two_theta=line_tolerance_two_theta,
        )
    else:
        q_scale, seed_weight = _direct_scale_estimate(
            ref_lines,
            obs_lines,
            tolerance_two_theta=line_tolerance_two_theta,
        )
        position_scale = 1.0
        zero_shift = 0.0
        coverage, matched = _q_scaled_line_coverage(
            ref_lines,
            obs_lines,
            q_scale,
            tolerance_two_theta=line_tolerance_two_theta,
        )
        observed_coverage, observed_matched = _q_observed_anchor_coverage(
            ref_lines,
            obs_lines,
            q_scale,
            tolerance_two_theta=line_tolerance_two_theta,
        )
    anchor_count = min(10, len(obs_lines))
    enough_lines = min(min(matched, observed_matched) / 8.0, 1.0)
    seed_bonus = min(seed_weight / 4.0, 1.0)
    features = FingerprintMatchFeatures(
        observed_coverage=float(observed_coverage),
        reference_coverage=float(coverage),
        sufficient_lines=float(enough_lines),
        alignment_seed=float(seed_bonus),
        observed_matched=int(observed_matched),
        reference_matched=int(matched),
        anchor_count=int(anchor_count),
    )
    score = apply_match_weights(features, weights)
    profile_fwhm = _matched_profile_fwhm(
        ref_lines,
        obs_lines,
        position_scale,
        zero_shift,
        tolerance_two_theta=line_tolerance_two_theta,
    )
    return FingerprintMatchResult(
        score=float(np.clip(score, 0.0, 100.0)),
        pair_score=seed_bonus,
        line_coverage=coverage,
        observed_coverage=observed_coverage,
        matched_lines=matched,
        total_lines=len(ref_lines),
        q_scale=float(q_scale),
        position_scale=float(position_scale),
        zero_shift=float(zero_shift),
        profile_fwhm=float(profile_fwhm),
        features=features,
    )


@dataclass(frozen=True, slots=True)
class _Line:
    two_theta: float
    q: float
    weight: float
    fwhm: float = 0.0


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
            try:
                fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), 0.0)
            except (TypeError, ValueError):
                fwhm = 0.0
            lines.append(_Line(two_theta=two_theta, q=q, weight=strength, fwhm=fwhm))
    lines.sort(key=lambda line: line.weight, reverse=True)
    strongest = lines[: max(int(limit), 1)]
    max_weight = max((line.weight for line in strongest), default=1.0)
    normalized = [
        _Line(line.two_theta, line.q, max(line.weight / max_weight, 0.01), line.fwhm)
        for line in strongest
    ]
    return sorted(normalized, key=lambda line: line.q)


def _adaptive_tolerance(obs_lines: list[_Line], *, fallback: float) -> float:
    widths = sorted(
        line.fwhm
        for line in obs_lines
        if math.isfinite(line.fwhm) and 0.03 <= line.fwhm <= 1.2
    )
    if len(widths) < 3:
        return float(fallback)
    median = float(np.median(widths))
    return float(np.clip(median * 1.7, 0.18, 0.85))


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


def _best_position_alignment(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    *,
    tolerance_two_theta: float,
    fixed_zero_shift: float | None = None,
) -> tuple[float, float, float]:
    """Fit a small 2theta scale change and zero shift from strong line votes."""

    if not ref_lines or not obs_lines:
        return 1.0, 0.0, 0.0
    pivot = 45.0
    strong_reference = sorted(ref_lines, key=lambda line: line.weight, reverse=True)[:18]
    strong_observed = sorted(obs_lines, key=lambda line: line.weight, reverse=True)[:12]
    initial_shift = 0.0 if fixed_zero_shift is None else float(fixed_zero_shift)
    candidates: list[tuple[float, float, float]] = [(1.0, initial_shift, 0.0)]
    scale_candidates = (0.990, 0.994, 0.997, 1.0, 1.003, 1.006, 1.010)
    for position_scale in scale_candidates:
        if fixed_zero_shift is not None:
            candidates.append((position_scale, float(fixed_zero_shift), 0.0))
            continue
        shift_votes: list[tuple[float, float]] = []
        for ref in strong_reference:
            scaled = pivot + (ref.two_theta - pivot) * position_scale
            for obs in strong_observed:
                shift = obs.two_theta - scaled
                if abs(shift) > 0.80:
                    continue
                intensity_quality = _relative_intensity_quality(ref.weight, obs.weight)
                if intensity_quality <= 0.08:
                    continue
                shift_votes.append(
                    (
                        shift,
                        math.sqrt(max(ref.weight, 0.01) * max(obs.weight, 0.01)) * intensity_quality,
                    )
                )
        clusters: list[tuple[float, float]] = []
        for center, _weight in shift_votes:
            cluster = [(shift, weight) for shift, weight in shift_votes if abs(shift - center) <= 0.055]
            total = sum(weight for _shift, weight in cluster)
            if total <= 0.0:
                continue
            mean = sum(shift * weight for shift, weight in cluster) / total
            clusters.append((float(mean), float(total)))
        clusters.sort(key=lambda item: item[1], reverse=True)
        accepted: list[tuple[float, float]] = []
        for shift, weight in clusters:
            if any(abs(shift - existing) < 0.08 for existing, _value in accepted):
                continue
            accepted.append((shift, weight))
            if len(accepted) >= 3:
                break
        candidates.extend((position_scale, shift, weight) for shift, weight in accepted)

    best = (1.0, 0.0, 0.0)
    best_score = -1.0
    for position_scale, zero_shift, vote_weight in candidates:
        coverage, _matched = _scaled_line_coverage(
            ref_lines,
            obs_lines,
            position_scale,
            zero_shift,
            1.0,
            tolerance_two_theta=tolerance_two_theta,
        )
        observed_coverage, _observed_matched = _observed_anchor_coverage(
            ref_lines,
            obs_lines,
            position_scale,
            zero_shift,
            tolerance_two_theta=tolerance_two_theta,
            limit=10,
        )
        precision = _alignment_precision(
            ref_lines,
            obs_lines,
            position_scale,
            zero_shift,
            tolerance_two_theta,
        )
        deformation_penalty = max(
            0.95,
            1.0 - abs(position_scale - 1.0) * 1.5 - abs(zero_shift) * 0.008,
        )
        score = (0.64 * coverage + 0.24 * observed_coverage + 0.12 * precision) * deformation_penalty
        if score > best_score:
            best_score = score
            best = (position_scale, zero_shift, vote_weight)
    return best


def _matched_profile_fwhm(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    position_scale: float,
    zero_shift: float,
    *,
    tolerance_two_theta: float,
) -> float:
    """Estimate width independently for the current candidate's matched lines."""

    observed = [line for line in obs_lines if 0.03 <= line.fwhm <= 1.2]
    if not observed:
        return 0.18
    available = set(range(len(observed)))
    widths: list[tuple[float, float]] = []
    for ref in sorted(ref_lines, key=lambda line: line.weight, reverse=True)[:24]:
        if not available:
            break
        transformed = _transform_two_theta(ref.two_theta, position_scale, zero_shift)
        index = min(available, key=lambda item: abs(observed[item].two_theta - transformed))
        if abs(observed[index].two_theta - transformed) > max(float(tolerance_two_theta), 0.05):
            continue
        available.remove(index)
        widths.append((observed[index].fwhm, math.sqrt(max(ref.weight, 0.01))))
    if len(widths) < 3:
        return 0.18
    widths.sort(key=lambda item: item[0])
    threshold = 0.5 * sum(weight for _width, weight in widths)
    accumulated = 0.0
    for width, weight in widths:
        accumulated += weight
        if accumulated >= threshold:
            return float(np.clip(width, 0.05, 1.2))
    return 0.18


def _alignment_precision(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    position_scale: float,
    zero_shift: float,
    tolerance_two_theta: float,
) -> float:
    observed_positions = np.asarray(sorted(line.two_theta for line in obs_lines), dtype=float)
    weighted = 0.0
    total = 0.0
    for ref in sorted(ref_lines, key=lambda line: line.weight, reverse=True)[:16]:
        transformed = _transform_two_theta(ref.two_theta, position_scale, zero_shift)
        delta = float(np.min(np.abs(observed_positions - transformed)))
        if delta > tolerance_two_theta:
            continue
        weight = max(ref.weight, 0.01) ** 0.6
        weighted += weight * max(0.0, 1.0 - delta / max(tolerance_two_theta, 1.0e-6))
        total += weight
    return weighted / total if total > 0.0 else 0.0


def _scaled_line_coverage(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    position_scale: float,
    zero_shift: float,
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
        scaled_two_theta = _transform_two_theta(ref.two_theta, position_scale, zero_shift)
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


def _q_scaled_line_coverage(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    q_scale: float,
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
    position_scale: float,
    zero_shift: float,
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
        scaled_reference.append(_transform_two_theta(ref.two_theta, position_scale, zero_shift))
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


def _q_observed_anchor_coverage(
    ref_lines: list[_Line],
    obs_lines: list[_Line],
    q_scale: float,
    *,
    tolerance_two_theta: float,
    limit: int = 16,
) -> tuple[float, int]:
    transformed = []
    for ref in ref_lines:
        two_theta = _two_theta_from_q(ref.q * q_scale)
        if two_theta is not None:
            transformed.append(_Line(two_theta=two_theta, q=0.0, weight=ref.weight))
    if not transformed:
        return 0.0, 0
    anchors = sorted(obs_lines, key=lambda line: line.weight, reverse=True)[: max(int(limit), 1)]
    total_weight = sum(line.weight for line in anchors)
    matched_weight = 0.0
    matched = 0
    for obs in anchors:
        quality = _best_line_match_quality(
            obs.two_theta,
            obs.weight,
            transformed,
            tolerance_two_theta=tolerance_two_theta,
        )
        if quality <= 0.0:
            continue
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


def _transform_two_theta(two_theta: float, position_scale: float, zero_shift: float) -> float:
    pivot = 45.0
    return pivot + (float(two_theta) - pivot) * float(position_scale) + float(zero_shift)


def _representative_q_scale(
    ref_lines: list[_Line],
    position_scale: float,
    zero_shift: float,
) -> float:
    if not ref_lines:
        return 1.0
    representative = float(np.median([line.two_theta for line in ref_lines]))
    original_q = _q_from_two_theta(representative)
    transformed_q = _q_from_two_theta(_transform_two_theta(representative, position_scale, zero_shift))
    return transformed_q / max(original_q, 1.0e-12)


def _two_theta_from_q(q_value: float) -> float | None:
    argument = float(q_value)
    if not 0.0 < argument < 1.0:
        return None
    return math.degrees(2.0 * math.asin(argument))
