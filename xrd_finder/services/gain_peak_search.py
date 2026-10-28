"""Additional-phase search on measured peaks, without fitting phase amplitudes."""
from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Iterable
from functools import lru_cache

from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY
from xrd_finder.services.gain_shortlist import significant_residual_records
from xrd_finder.services.phase_pattern_equivalence import phase_patterns_equivalent
from xrd_finder.services.profile_matched_peak_detector import is_broad_rescue_candidate


def _number(obj, name, default=0.0):
    try:
        value = float(getattr(obj, name, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


@dataclass(frozen=True, slots=True)
class GainPeakRecord:
    two_theta: float
    area: float
    fwhm: float
    height: float
    prominence: float
    local_snr: float | None
    area_snr: float
    broadening_scale: float
    profile_match: float
    curvature: float
    width_persistence: int
    fit_quality: float


@dataclass(frozen=True, slots=True)
class GainSearchLine:
    two_theta: float
    intensity: float
    d: float
    h: int
    k: int
    l: int


@dataclass(frozen=True, slots=True)
class GainPeakSearchContext:
    records: tuple[GainPeakRecord, ...]
    direct_records: tuple[GainPeakRecord, ...]
    overlap_records: tuple[GainPeakRecord, ...]
    accepted_patterns: tuple[tuple[GainSearchLine, ...], ...]
    base_fwhm: float
    two_theta_range: tuple[float, float] | None = None


def _line(obj) -> GainSearchLine | None:
    position = _number(obj, 'two_theta', math.nan)
    intensity = _number(obj, 'intensity')
    if not math.isfinite(position) or intensity <= 0.0:
        return None
    return GainSearchLine(position, intensity, _number(obj, 'd'),
                          *(int(_number(obj, name)) for name in ('h', 'k', 'l')))


def build_gain_peak_search_context(
    records: Iterable[object], accepted_patterns: Iterable[Iterable[object]], *, base_fwhm: float,
    two_theta_range: tuple[float, float] | None = None,
) -> GainPeakSearchContext:
    width = max(float(base_fwhm), 0.05) if math.isfinite(float(base_fwhm)) else 0.18
    patterns = tuple(tuple(line for item in pattern if (line := _line(item)) is not None
                           and (two_theta_range is None or two_theta_range[0] <= line.two_theta <= two_theta_range[1]))
                     for pattern in accepted_patterns)
    measured = []
    for item in records:
        if not significant_residual_records((item,)) and not is_broad_rescue_candidate(item):
            continue
        position = _number(item, 'two_theta', math.nan)
        area = _number(item, 'area')
        if not math.isfinite(position) or area <= 0.0:
            continue
        if two_theta_range is not None and not two_theta_range[0] <= position <= two_theta_range[1]:
            continue
        snr = getattr(item, 'local_snr', None)
        measured.append(GainPeakRecord(
            position, area, max(_number(item, 'fwhm', width), .01),
            max(_number(item, 'height'), 0.0), max(_number(item, 'prominence'), 0.0),
            None if snr is None else _number(item, 'local_snr'), _number(item, 'area_snr'),
            _number(item, 'broadening_scale', 1.0), _number(item, 'profile_match'),
            _number(item, 'curvature'), int(_number(item, 'width_persistence')), _number(item, 'fit_quality'),
        ))
    unique = []
    for item in sorted(measured, key=lambda r: (-r.area, r.two_theta)):
        if all(abs(item.two_theta-r.two_theta) > .01 for r in unique):
            unique.append(item)
    unique.sort(key=lambda r: r.two_theta)
    selected_positions = tuple(line.two_theta for pattern in patterns for line in pattern)
    direct, overlap = [], []
    for item in unique:
        tolerance = max(.26, min(.72, max(width, item.fwhm)*2.4))
        group = overlap if any(abs(p-item.two_theta) <= tolerance for p in selected_positions) else direct
        group.append(item)
    return GainPeakSearchContext(tuple(unique), tuple(direct), tuple(overlap), patterns, width, two_theta_range)


def gain_peak_retrieval_records(
    context: GainPeakSearchContext,
) -> tuple[tuple[GainPeakRecord, ...], tuple[GainPeakRecord, ...]]:
    """Keep adjacent maxima searchable without asserting a new phase.

    Use each measured half-width with a small coordinate allowance, rather
    than the global candidate-search window. These groups only feed candidate
    retrieval; the conservative context still determines displayed Gain.
    """
    positions = tuple(line.two_theta for phase in context.accepted_patterns for line in phase)
    direct, shared = [], []
    for record in context.records:
        tolerance = max(.05, .5*record.fwhm)
        group = shared if any(abs(position-record.two_theta) <= tolerance for position in positions) else direct
        group.append(record)
    return tuple(direct), tuple(shared)


@dataclass(frozen=True, slots=True)
class GainPeakCandidateScore:
    score: float = 0.0
    direct_score: float = 0.0
    overlap_score: float = 0.0
    matched_lines: int = 0
    direct_matches: int = 0
    overlap_matches: int = 0
    missing_strong_lines: int = 0
    equivalent_to_accepted: bool = False
    retrieval_score: float = 0.0


@lru_cache(maxsize=4096)
def _equivalent(reference, candidate, width):
    return phase_patterns_equivalent(reference, candidate, fwhm=width)


def score_gain_peak_candidate(
    peaks: Iterable[object], context: GainPeakSearchContext,
) -> GainPeakCandidateScore:
    full_pattern = tuple(line for item in peaks if (line := _line(item)) is not None
                         and (context.two_theta_range is None
                              or context.two_theta_range[0] <= line.two_theta <= context.two_theta_range[1]))
    if any(_equivalent(pattern, full_pattern, context.base_fwhm) for pattern in context.accepted_patterns):
        return GainPeakCandidateScore(equivalent_to_accepted=True)
    lines = sorted((line for line in full_pattern if context.two_theta_range is None
                    or context.two_theta_range[0] <= line.two_theta <= context.two_theta_range[1]),
                   key=lambda line: (-line.intensity, line.two_theta))
    if not lines or not context.records:
        return GainPeakCandidateScore()
    maximum = lines[0].intensity
    independent = []
    for line in lines:
        if line.intensity/maximum < .03:
            continue
        if all(abs(line.two_theta-other.two_theta) > .01 for other in independent):
            independent.append(line)
        if len(independent) >= 42:
            break
    opportunities = []
    for index, line in enumerate(independent):
        weight = math.sqrt(line.intensity/maximum)
        for record_index, record in enumerate(context.records):
            width = max(.26, min(.72, max(context.base_fwhm, record.fwhm)*2.4))
            distance = abs(line.two_theta-record.two_theta)
            if distance <= width:
                quality = math.exp(-.5*(distance/width)**2)
                opportunities.append((quality*weight, index, record_index, quality))
    used_lines, used_records = set(), set()
    pairs = []
    for _, index, record_index, quality in sorted(opportunities, reverse=True):
        if index in used_lines or record_index in used_records:
            continue
        used_lines.add(index)
        used_records.add(record_index)
        pairs.append((index, record_index, quality))
    if len(pairs) < 2:
        return GainPeakCandidateScore(matched_lines=len(pairs), missing_strong_lines=len(independent)-len(used_lines))
    matched_weight = sum(math.sqrt(independent[i].intensity/maximum)*quality for i, _, quality in pairs)
    missing_weight = sum(math.sqrt(line.intensity/maximum) for i, line in enumerate(independent) if i not in used_lines)
    support = matched_weight/max(matched_weight + .15*missing_weight, 1e-12)
    direct_positions = {r.two_theta for r in context.direct_records}
    direct_pairs = [(i, j, q) for i,j,q in pairs if context.records[j].two_theta in direct_positions]
    overlap_pairs = [(i, j, q) for i,j,q in pairs if context.records[j].two_theta not in direct_positions]

    def coverage(pairs, records):
        total = sum(r.area for r in records)
        return sum(context.records[j].area*q for _,j,q in pairs)/max(total, 1e-12) if total > 0 else 0.0

    direct = 100*coverage(direct_pairs, context.direct_records)*min(len(direct_pairs)/3, 1)
    overlap = 100*coverage(overlap_pairs, context.overlap_records)*min(len(pairs)/3, 1)
    score = DEFAULT_GAIN_POLICY.combine_evidence(
        direct_gain=direct, overlap_gain=overlap*DEFAULT_GAIN_POLICY.overlap_evidence_weight,
        hidden_gain=0, profile_gain=None, remaining_fit=100,
        residual_line_count=len(context.records), direct_reliability=1, phase_snr=None,
    )
    # Apply missing-line support after the limited-evidence cap. Otherwise two
    # matching lines can saturate the cap despite strong unsupported lines.
    retrieval_score = float(score*support)
    total_area = sum(record.area for record in context.records)
    novel_area = sum(context.records[j].area*q for _,j,q in direct_pairs)
    novelty = novel_area/max(total_area, 1e-12)
    # Shared positions keep a candidate retrievable, but cannot establish an
    # additional component on their own. Normalizing only by unexplained area
    # would amplify tiny remnants of a one-phase pattern into large Gain.
    corroboration = 1 + DEFAULT_GAIN_POLICY.corroboration_weight*coverage(overlap_pairs, context.overlap_records)
    final_score = min(100., 100*novelty*support*min(len(pairs)/3, 1)*corroboration)
    return GainPeakCandidateScore(float(final_score), float(direct*support), float(overlap*support), len(pairs),
                                  len(direct_pairs), len(overlap_pairs), len(independent)-len(used_lines),
                                  retrieval_score=retrieval_score)
