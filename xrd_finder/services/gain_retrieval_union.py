from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from xrd_finder.services.gain_retrieval_channels import RetrievalChannelRun
from xrd_finder.services.geometric_fingerprint import peak_geometric_hashes
from xrd_finder.services.phase_pattern_equivalence import phase_patterns_equivalent


@dataclass(frozen=True, slots=True)
class GainRetrievalConfig:
    channel_limits: tuple[tuple[str, int], ...]
    union_limit: int = 80
    profile_limit: int = 24
    missing_line_weight: float = 0.15
    rank_corroboration: float = 0.20
    pair_bin_deg: float = 0.08
    ratio_bin: float = 0.02

    def channel_limit(self, channel: str) -> int:
        for configured_channel, limit in self.channel_limits:
            if str(configured_channel) == str(channel):
                return max(0, int(limit))
        return 0


@dataclass(frozen=True, slots=True)
class GainRetrievalPool:
    optional_ids: tuple[str, ...]
    family_assignments: tuple[tuple[str, str], ...]
    channel_runs: tuple[RetrievalChannelRun, ...]
    raw_union_count: int
    collapsed_family_count: int
    raw_candidate_ids: tuple[str, ...] = ()

    def family_for(self, phase_id: str) -> str:
        key = str(phase_id)
        for member, family in self.family_assignments:
            if member == key:
                return family
        raise KeyError(key)


def build_gain_retrieval_pool(
    channel_runs: tuple[RetrievalChannelRun, ...],
    reference_lines: Mapping[str, Sequence[object]],
    accepted_ids: Iterable[str],
    residual_records: Iterable[object],
    overlap_positions: Iterable[float] = (),
    *,
    config: GainRetrievalConfig,
    wavelength: float = 1.5406,
    zero_shift: float = 0.0,
) -> GainRetrievalPool:
    """Fuse bounded channel prefixes and return diffraction-family representatives."""

    known = {str(phase_id): tuple(lines) for phase_id, lines in reference_lines.items()}
    accepted = tuple(sorted({str(value) for value in accepted_ids if str(value) in known}))
    runs = tuple(channel_runs)
    prefixes = _bounded_channel_prefixes(runs, known, config)
    raw_union = _round_robin_union(prefixes, limit=max(0, int(config.union_limit)))
    if not raw_union:
        assignments = tuple((phase_id, f"pattern:{phase_id}") for phase_id in accepted)
        return GainRetrievalPool((), assignments, runs, 0, 0, ())

    resolver = _PatternEquivalence(known)
    cluster_ids = tuple(sorted({*accepted, *raw_union}))
    clusters = _pattern_clusters(cluster_ids, resolver.equivalent)
    family_by_id: dict[str, str] = {}
    accepted_families: set[str] = set()
    for members in clusters:
        family = f"pattern:{min(members)}"
        for phase_id in members:
            family_by_id[phase_id] = family
        if any(phase_id in accepted for phase_id in members):
            accepted_families.add(family)

    channel_evidence = _normalized_channel_evidence(prefixes)
    residual = _residual_evidence(
        residual_records,
        wavelength=wavelength,
        zero_shift=zero_shift,
    )
    overlap = tuple(
        q
        for raw_value in overlap_positions
        if (value := _finite_float(raw_value)) is not None
        and (q := _q_from_two_theta(value - zero_shift, wavelength)) is not None
    )
    family_members: dict[str, list[str]] = {}
    for phase_id in raw_union:
        family = family_by_id[phase_id]
        if family in accepted_families:
            continue
        family_members.setdefault(family, []).append(phase_id)

    family_rows: list[tuple[float, str, str]] = []
    for family, members in family_members.items():
        representative = min(
            members,
            key=lambda phase_id: (
                -_candidate_retrieval_score(
                    phase_id, channel_evidence, config.rank_corroboration
                ),
                phase_id,
            ),
        )
        best_member_score = -math.inf
        for phase_id in members:
            retrieval_score = _candidate_retrieval_score(
                phase_id, channel_evidence, config.rank_corroboration
            )
            coverage, missing_fraction = _line_level_terms(
                known[phase_id],
                residual,
                overlap,
                wavelength=wavelength,
            )
            total = (
                retrieval_score
                + coverage
                - max(0.0, float(config.missing_line_weight)) * missing_fraction
            )
            if not math.isfinite(total):
                total = 0.0
            if total > best_member_score or (
                total == best_member_score and phase_id < representative
            ):
                best_member_score = total
                representative = phase_id
        family_rows.append((best_member_score, representative, family))

    family_rows.sort(key=lambda row: (-row[0], row[1]))
    optional_ids = tuple(
        representative
        for _score, representative, _family in family_rows[
            : max(0, int(config.profile_limit))
        ]
    )
    return GainRetrievalPool(
        optional_ids=optional_ids,
        family_assignments=tuple(sorted(family_by_id.items())),
        channel_runs=runs,
        raw_union_count=len(raw_union),
        collapsed_family_count=len(family_members),
        raw_candidate_ids=raw_union,
    )


def _bounded_channel_prefixes(
    runs: tuple[RetrievalChannelRun, ...],
    known: Mapping[str, Sequence[object]],
    config: GainRetrievalConfig,
) -> tuple[tuple[str, tuple[object, ...]], ...]:
    prefixes: list[tuple[str, tuple[object, ...]]] = []
    for run in runs:
        limit = config.channel_limit(run.channel)
        if limit <= 0:
            continue
        usable = []
        for hit in sorted(run.hits, key=lambda item: (_safe_rank(item.rank), str(item.phase_id))):
            phase_id = str(hit.phase_id)
            score = _finite_float(hit.score)
            if phase_id not in known or score is None or score <= 0.0:
                continue
            usable.append(hit)
            if len(usable) >= limit:
                break
        prefixes.append((str(run.channel), tuple(usable)))
    return tuple(prefixes)


def _round_robin_union(
    prefixes: tuple[tuple[str, tuple[object, ...]], ...], *, limit: int
) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    depth = 0
    while len(selected) < limit:
        added_at_depth = False
        any_at_depth = False
        for _channel, hits in prefixes:
            if depth >= len(hits):
                continue
            any_at_depth = True
            phase_id = str(hits[depth].phase_id)
            if phase_id in seen:
                continue
            selected.append(phase_id)
            seen.add(phase_id)
            added_at_depth = True
            if len(selected) >= limit:
                break
        if not any_at_depth:
            break
        depth += 1
        if not added_at_depth and all(depth >= len(hits) for _channel, hits in prefixes):
            break
    return tuple(selected)


def _normalized_channel_evidence(
    prefixes: tuple[tuple[str, tuple[object, ...]], ...]
) -> dict[str, dict[str, tuple[float, float]]]:
    evidence: dict[str, dict[str, tuple[float, float]]] = {}
    for channel, hits in prefixes:
        maximum = max((_finite_float(hit.score) or 0.0 for hit in hits), default=0.0)
        channel_values: dict[str, tuple[float, float]] = {}
        for ordinal, hit in enumerate(hits, start=1):
            rank = _safe_rank(getattr(hit, "rank", ordinal), fallback=ordinal)
            rank_term = 1.0 / (8.0 + rank)
            score = _finite_float(hit.score) or 0.0
            score_term = score / maximum if maximum > 0.0 else 0.0
            channel_values[str(hit.phase_id)] = (rank_term, min(max(score_term, 0.0), 1.0))
        evidence[channel] = channel_values
    return evidence


def _candidate_retrieval_score(
    phase_id: str,
    evidence: Mapping[str, Mapping[str, tuple[float, float]]],
    corroboration: float,
) -> float:
    terms: list[float] = []
    for channel_values in evidence.values():
        value = channel_values.get(phase_id)
        if value is None:
            continue
        rank_term, score_term = value
        terms.append(rank_term + 0.02 * score_term)
    if not terms:
        return 0.0
    terms.sort(reverse=True)
    extra = sum(terms[1:]) / max(len(terms) - 1, 1)
    return terms[0] + max(0.0, float(corroboration)) * extra


def _residual_evidence(
    records: Iterable[object],
    *,
    wavelength: float,
    zero_shift: float,
) -> tuple[tuple[float, float, float], ...]:
    parsed: list[tuple[float, float, float]] = []
    for record in records:
        q = _record_q(record, wavelength=wavelength, zero_shift=zero_shift)
        if q is None:
            continue
        strengths = (
            _finite_float(getattr(record, "area", None)),
            _finite_float(getattr(record, "prominence", None)),
            _finite_float(getattr(record, "height", None)),
        )
        strength = next((value for value in strengths if value is not None and value > 0.0), 0.0)
        if strength > 0.0:
            snr = _finite_float(
                getattr(record, "area_snr", None)
                or getattr(record, "local_snr", None)
                or getattr(record, "snr", None)
            )
            parsed.append((q, strength, max(snr or 0.0, 0.0)))
    maximum = max((strength for _q, strength, _snr in parsed), default=0.0)
    if maximum <= 0.0:
        return ()
    return tuple(
        (q, strength / maximum, snr)
        for q, strength, snr in parsed
    )


def _line_level_terms(
    lines: Sequence[object],
    residual: tuple[tuple[float, float, float], ...],
    overlap_positions: tuple[float, ...],
    *,
    wavelength: float,
    q_log_tolerance: float = 0.012,
) -> tuple[float, float]:
    candidate = _candidate_q_lines(lines, wavelength=wavelength)
    if not candidate:
        return 0.0, 0.0
    tolerance = max(float(q_log_tolerance), 1.0e-4)
    total_residual = sum(weight for _q, weight, _snr in residual)
    coverage = 0.0
    matched_scales: list[float] = []
    for residual_q, residual_weight, _snr in residual:
        support = max(
            (
                math.sqrt(line_weight)
                * math.exp(-0.5 * (math.log(line_q / residual_q) / tolerance) ** 2)
                for line_q, line_weight in candidate
                if abs(math.log(line_q / residual_q)) <= tolerance
            ),
            default=0.0,
        )
        coverage += residual_weight * support
        closest = min(
            (
                (abs(math.log(line_q / residual_q)), line_weight)
                for line_q, line_weight in candidate
                if abs(math.log(line_q / residual_q)) <= tolerance
            ),
            default=None,
        )
        if closest is not None and closest[1] > 0.0:
            matched_scales.append(residual_weight / closest[1])
    coverage = coverage / total_residual if total_residual > 0.0 else 0.0

    if not matched_scales:
        return min(max(coverage, 0.0), 1.0), 0.0
    matched_scales.sort()
    phase_scale = matched_scales[len(matched_scales) // 2]
    observed_floor = min(
        (weight for _q, weight, snr in residual if snr <= 0.0 or snr >= 3.0),
        default=0.16,
    )
    detection_floor = max(0.04, min(0.25, observed_floor * 0.75))
    missing_weight = 0.0
    considered_weight = 0.0
    for line_q, weight in candidate:
        expected_weight = phase_scale * weight
        if expected_weight < detection_floor:
            continue
        considered_weight += expected_weight
        observed = any(
            abs(math.log(line_q / residual_q)) <= tolerance
            for residual_q, _weight, _snr in residual
        )
        accepted_overlap = any(
            abs(math.log(line_q / overlap_q)) <= tolerance
            for overlap_q in overlap_positions
        )
        if not observed and not accepted_overlap:
            missing_weight += expected_weight
    missing_fraction = missing_weight / considered_weight if considered_weight > 0.0 else 0.0
    return min(max(coverage, 0.0), 1.0), min(max(missing_fraction, 0.0), 1.0)


def _candidate_q_lines(
    lines: Sequence[object],
    *,
    wavelength: float,
) -> tuple[tuple[float, float], ...]:
    parsed: list[tuple[float, float]] = []
    for line in lines:
        q = _record_q(line, wavelength=wavelength, zero_shift=0.0)
        intensity = _finite_float(getattr(line, "intensity", None))
        if q is not None and intensity is not None and intensity > 0.0:
            parsed.append((q, intensity))
    maximum = max((intensity for _q, intensity in parsed), default=0.0)
    if maximum <= 0.0:
        return ()
    return tuple(
        (q, intensity / maximum)
        for q, intensity in sorted(parsed, key=lambda value: -value[1])[:24]
        if intensity / maximum >= 0.01
    )


def _candidate_lines(lines: Sequence[object]) -> tuple[tuple[float, float], ...]:
    """Legacy 2theta view used only by diffraction-family collapse."""

    parsed: list[tuple[float, float]] = []
    for line in lines:
        position = _finite_float(getattr(line, "two_theta", None))
        intensity = _finite_float(getattr(line, "intensity", None))
        if position is not None and intensity is not None and intensity > 0.0:
            parsed.append((position, intensity))
    maximum = max((intensity for _position, intensity in parsed), default=0.0)
    if maximum <= 0.0:
        return ()
    return tuple(
        (position, intensity / maximum)
        for position, intensity in sorted(parsed, key=lambda value: -value[1])[:24]
        if intensity / maximum >= 0.01
    )


def _record_q(record: object, *, wavelength: float, zero_shift: float) -> float | None:
    d_spacing = _finite_float(getattr(record, "d", None))
    if d_spacing is not None and d_spacing > 0.0:
        return 1.0 / d_spacing
    two_theta = _finite_float(getattr(record, "two_theta", None))
    if two_theta is None:
        return None
    return _q_from_two_theta(two_theta - float(zero_shift), wavelength)


def _q_from_two_theta(two_theta: float, wavelength: float) -> float | None:
    if not 0.0 < float(two_theta) < 180.0 or float(wavelength) <= 0.0:
        return None
    q = 2.0 * math.sin(math.radians(float(two_theta) / 2.0)) / float(wavelength)
    return q if math.isfinite(q) and q > 0.0 else None


class _PatternEquivalence:
    def __init__(self, references: Mapping[str, Sequence[object]]):
        self.references = references
        self._cache: dict[tuple[str, str], bool] = {}
        self._positions: dict[str, tuple[float, ...]] = {}
        self._hashes: dict[str, frozenset[object]] = {}

    def equivalent(self, first: str, second: str) -> bool:
        if first == second:
            return True
        pair = tuple(sorted((first, second)))
        if pair in self._cache:
            return self._cache[pair]
        if not self._may_be_equivalent(first, second):
            self._cache[pair] = False
            return False
        value = phase_patterns_equivalent(self.references[first], self.references[second])
        self._cache[pair] = bool(value)
        return bool(value)

    def _may_be_equivalent(self, first: str, second: str) -> bool:
        first_positions = self._strong_positions(first)
        second_positions = self._strong_positions(second)
        matches = 0
        used: set[int] = set()
        for first_position in first_positions:
            closest = min(
                (
                    (abs(first_position - value), index)
                    for index, value in enumerate(second_positions)
                    if index not in used and abs(first_position - value) <= 0.28
                ),
                default=None,
            )
            if closest is not None:
                used.add(closest[1])
                matches += 1
        if matches >= 3:
            return True
        return len(self._geometric_hashes(first).intersection(self._geometric_hashes(second))) >= 48

    def _strong_positions(self, phase_id: str) -> tuple[float, ...]:
        if phase_id not in self._positions:
            self._positions[phase_id] = tuple(
                sorted(position for position, _weight in _candidate_lines(self.references[phase_id]))
            )
        return self._positions[phase_id]

    def _geometric_hashes(self, phase_id: str) -> frozenset[object]:
        if phase_id not in self._hashes:
            self._hashes[phase_id] = frozenset(
                peak_geometric_hashes(self.references[phase_id], max_peaks=14)
            )
        return self._hashes[phase_id]


def _pattern_clusters(
    phase_ids: Sequence[str], equivalent
) -> tuple[tuple[str, ...], ...]:
    parents = {phase_id: phase_id for phase_id in phase_ids}

    def find(phase_id: str) -> str:
        while parents[phase_id] != phase_id:
            parents[phase_id] = parents[parents[phase_id]]
            phase_id = parents[phase_id]
        return phase_id

    for index, first in enumerate(phase_ids):
        for second in phase_ids[index + 1 :]:
            if not equivalent(first, second):
                continue
            first_root = find(first)
            second_root = find(second)
            if first_root != second_root:
                lower, higher = sorted((first_root, second_root))
                parents[higher] = lower
    groups: dict[str, list[str]] = {}
    for phase_id in phase_ids:
        groups.setdefault(find(phase_id), []).append(phase_id)
    return tuple(tuple(members) for _root, members in sorted(groups.items()))


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _safe_rank(value: object, *, fallback: int = 1) -> int:
    try:
        rank = int(value)
    except (TypeError, ValueError, OverflowError):
        rank = int(fallback)
    return max(1, rank)


__all__ = [
    "GainRetrievalConfig",
    "GainRetrievalPool",
    "build_gain_retrieval_pool",
]
