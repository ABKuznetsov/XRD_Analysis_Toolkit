from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class XrdMatchingOptions:
    tolerance_two_theta: float = 0.25
    intensity_min: float = 5.0
    max_reference_peaks: int = 30
    good_score: float = 0.35
    ok_score: float = 0.18
    min_matched_peaks: int = 2


@dataclass(slots=True)
class XrdPeakMatch:
    reference_two_theta: float
    observed_two_theta: float
    delta_two_theta: float
    reference_intensity: float


@dataclass(slots=True)
class XrdPeakMatchScore:
    matched_peaks: int = 0
    total_peaks: int = 0
    coverage: float = 0.0
    mean_delta_two_theta: float = 0.0
    matches: list[XrdPeakMatch] | None = None


@dataclass(slots=True)
class XrdSearchMatchResult:
    score: float = 0.0
    status: str = "unmatched"
    matched_peaks: int = 0
    total_peaks: int = 0
    mean_delta_two_theta: float = 0.0
    matches: list[XrdPeakMatch] = field(default_factory=list)


def classify_peak_match(score: XrdPeakMatchScore, options: XrdMatchingOptions | None = None) -> str:
    options = options or XrdMatchingOptions()
    if score.matched_peaks < max(int(options.min_matched_peaks), 0):
        return "weak"
    if score.coverage >= float(options.good_score):
        return "good"
    if score.coverage >= float(options.ok_score):
        return "ok"
    return "weak"


def search_match_result(
    reference_peaks,
    observed_positions,
    options: XrdMatchingOptions | None = None,
) -> XrdSearchMatchResult:
    options = options or XrdMatchingOptions()
    score = score_peak_positions(reference_peaks, observed_positions, options)
    return XrdSearchMatchResult(
        score=float(score.coverage),
        status=classify_peak_match(score, options),
        matched_peaks=score.matched_peaks,
        total_peaks=score.total_peaks,
        mean_delta_two_theta=score.mean_delta_two_theta,
        matches=list(score.matches or []),
    )


def score_peak_positions(
    reference_peaks,
    observed_positions,
    options: XrdMatchingOptions | None = None,
) -> XrdPeakMatchScore:
    options = options or XrdMatchingOptions()
    observed = np.asarray(observed_positions, dtype=float)
    observed = observed[np.isfinite(observed)]
    strong = sorted(
        [
            peak for peak in reference_peaks
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= options.intensity_min
        ],
        key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0),
        reverse=True,
    )[: max(int(options.max_reference_peaks), 1)]
    if not strong:
        return XrdPeakMatchScore(matches=[])
    if not len(observed):
        return XrdPeakMatchScore(total_peaks=len(strong), matches=[])
    observed.sort()
    matches: list[XrdPeakMatch] = []
    tolerance = max(float(options.tolerance_two_theta), 0.0)
    for peak in strong:
        two_theta = float(getattr(peak, "two_theta", 0.0) or 0.0)
        index = int(np.searchsorted(observed, two_theta))
        candidates = []
        if index < len(observed):
            candidates.append(float(observed[index]))
        if index > 0:
            candidates.append(float(observed[index - 1]))
        if not candidates:
            continue
        nearest = min(candidates, key=lambda value: abs(value - two_theta))
        delta = nearest - two_theta
        if abs(delta) <= tolerance:
            matches.append(
                XrdPeakMatch(
                    reference_two_theta=two_theta,
                    observed_two_theta=nearest,
                    delta_two_theta=float(delta),
                    reference_intensity=float(getattr(peak, "intensity", 0.0) or 0.0),
                )
            )
    matched = len(matches)
    total = len(strong)
    mean_delta = float(np.mean([abs(match.delta_two_theta) for match in matches])) if matches else 0.0
    return XrdPeakMatchScore(
        matched_peaks=matched,
        total_peaks=total,
        coverage=float(matched / max(total, 1)),
        mean_delta_two_theta=mean_delta,
        matches=matches,
    )
