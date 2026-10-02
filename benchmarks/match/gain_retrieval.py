from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from benchmarks.match.generate_profiles import ReferenceLine
from xrd_finder.services.gain_shortlist import (
    dominant_line_candidate_scores,
    rare_line_candidate_scores,
    summarize_residual_evidence,
)
from xrd_finder.services.geometric_fingerprint import (
    peak_geometric_hashes,
    rank_fingerprint_candidates,
)
from xrd_finder.services.phase_pattern_equivalence import phase_patterns_equivalent


@dataclass(frozen=True, slots=True)
class JointGainCandidatePool:
    required_ids: tuple[str, ...]
    optional_ids: tuple[str, ...]
    raw_candidate_ids: tuple[str, ...]
    family_assignments: tuple[tuple[str, str], ...]
    target_present_before_collapse: bool | None
    target_present_after_collapse: bool | None

    def family_for(self, phase_id: str) -> str:
        for key, family_key in self.family_assignments:
            if key == phase_id:
                return family_key
        raise KeyError(phase_id)


def joint_gain_candidate_pool(
    references: Mapping[str, Sequence[ReferenceLine]],
    *,
    original_scores: Mapping[str, object],
    residual_scores: Mapping[str, object],
    rare_candidate_ids: Sequence[str],
    accepted_phase_ids: Sequence[str],
    original_limit: int = 40,
    residual_limit: int = 40,
    rare_limit: int = 12,
    optional_limit: int = 60,
    target_phase_id: str | None = None,
    fwhm: float = 0.18,
) -> JointGainCandidatePool:
    """Fuse retrieval channels and collapse equivalent powder patterns."""

    known_ids = tuple(sorted(str(key) for key in references))
    accepted = tuple(
        sorted({str(key) for key in accepted_phase_ids if str(key) in references})
    )
    equivalence_cache: dict[tuple[str, str], bool] = {}

    def equivalent(first: str, second: str) -> bool:
        if first == second:
            return True
        pair = tuple(sorted((first, second)))
        cached = equivalence_cache.get(pair)
        if cached is not None:
            return cached
        value = phase_patterns_equivalent(
            references[first],
            references[second],
            fwhm=fwhm,
        )
        equivalence_cache[pair] = bool(value)
        return bool(value)

    def is_accepted_family(phase_id: str) -> bool:
        return any(equivalent(phase_id, accepted_id) for accepted_id in accepted)

    original_order = tuple(
        sorted(
            known_ids,
            key=lambda key: (-_score_value(original_scores.get(key, 0.0)), key),
        )
    )
    residual_order = tuple(
        sorted(
            known_ids,
            key=lambda key: (-_score_value(residual_scores.get(key, 0.0)), key),
        )
    )
    rare_order = tuple(
        dict.fromkeys(
            str(key) for key in rare_candidate_ids if str(key) in references
        )
    )

    original_selected = _take_distinct_pattern_families(
        original_order,
        references=references,
        limit=original_limit,
        is_accepted_family=is_accepted_family,
        equivalent=equivalent,
    )
    residual_selected = _take_distinct_pattern_families(
        residual_order,
        references=references,
        limit=residual_limit,
        is_accepted_family=is_accepted_family,
        equivalent=equivalent,
    )
    rare_selected = _take_distinct_pattern_families(
        rare_order,
        references=references,
        limit=rare_limit,
        is_accepted_family=is_accepted_family,
        equivalent=equivalent,
    )
    raw_optional = tuple(
        dict.fromkeys((*original_selected, *residual_selected, *rare_selected))
    )
    cluster_ids = tuple(sorted({*accepted, *raw_optional}))
    clusters = _pattern_clusters(cluster_ids, equivalent=equivalent)
    family_by_id: dict[str, str] = {}
    for members in clusters:
        family_key = f"pattern:{min(members)}"
        for phase_id in members:
            family_by_id[phase_id] = family_key

    cluster_representatives: dict[str, str] = {}
    for phase_id in raw_optional:
        family_key = family_by_id[phase_id]
        previous = cluster_representatives.get(family_key)
        if previous is None or (
            -_score_value(original_scores.get(phase_id, 0.0)),
            phase_id,
        ) < (
            -_score_value(original_scores.get(previous, 0.0)),
            previous,
        ):
            cluster_representatives[family_key] = phase_id

    channel_ranks = (
        {key: rank for rank, key in enumerate(original_selected, start=1)},
        {key: rank for rank, key in enumerate(residual_selected, start=1)},
        {key: rank for rank, key in enumerate(rare_selected, start=1)},
    )

    def family_retrieval_score(family_key: str) -> float:
        members = [
            phase_id
            for phase_id in raw_optional
            if family_by_id[phase_id] == family_key
        ]
        reciprocal_ranks = [
            1.0 / (8.0 + min(ranks[member] for member in members if member in ranks))
            for ranks in channel_ranks
            if any(member in ranks for member in members)
        ]
        if not reciprocal_ranks:
            return 0.0
        reciprocal_ranks.sort(reverse=True)
        return reciprocal_ranks[0] + (
            0.20 * reciprocal_ranks[1] if len(reciprocal_ranks) > 1 else 0.0
        )

    optional_ids = tuple(
        cluster_representatives[family_key]
        for family_key in sorted(
            cluster_representatives,
            key=lambda family_key: (
                -family_retrieval_score(family_key),
                -_score_value(
                    original_scores.get(cluster_representatives[family_key], 0.0)
                ),
                cluster_representatives[family_key],
            ),
        )[: max(0, int(optional_limit))]
    )

    # Assign every known card to a selected/required pattern family when it is
    # equivalent, so diagnostics can identify collapsed cards by ID.
    representatives = tuple(
        sorted({*accepted, *cluster_representatives.values()})
    )
    for phase_id in known_ids:
        if phase_id in family_by_id:
            continue
        matched = next(
            (
                representative
                for representative in representatives
                if equivalent(phase_id, representative)
            ),
            None,
        )
        family_by_id[phase_id] = (
            family_by_id[matched]
            if matched is not None
            else f"pattern:{phase_id}"
        )

    target_before: bool | None = None
    target_after: bool | None = None
    if target_phase_id is not None and target_phase_id in references:
        target_before = any(
            equivalent(target_phase_id, phase_id) for phase_id in raw_optional
        )
        target_after = any(
            equivalent(target_phase_id, phase_id) for phase_id in optional_ids
        )

    return JointGainCandidatePool(
        required_ids=accepted,
        optional_ids=optional_ids,
        raw_candidate_ids=raw_optional,
        family_assignments=tuple(sorted(family_by_id.items())),
        target_present_before_collapse=target_before,
        target_present_after_collapse=target_after,
    )


def _take_distinct_pattern_families(
    ordered_ids: Sequence[str],
    *,
    references: Mapping[str, Sequence[ReferenceLine]],
    limit: int,
    is_accepted_family,
    equivalent,
) -> tuple[str, ...]:
    family_limit = max(0, int(limit))
    if family_limit == 0:
        return ()
    selected: list[str] = []
    for phase_id in ordered_ids:
        if phase_id not in references or is_accepted_family(phase_id):
            continue
        if any(equivalent(phase_id, previous) for previous in selected):
            continue
        selected.append(phase_id)
        if len(selected) >= family_limit:
            break
    return tuple(selected)


def _pattern_clusters(phase_ids: Sequence[str], *, equivalent) -> tuple[tuple[str, ...], ...]:
    parents = {phase_id: phase_id for phase_id in phase_ids}

    def find(phase_id: str) -> str:
        while parents[phase_id] != phase_id:
            parents[phase_id] = parents[parents[phase_id]]
            phase_id = parents[phase_id]
        return phase_id

    def union(first: str, second: str) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        lower, higher = sorted((first_root, second_root))
        parents[higher] = lower

    ordered = tuple(sorted(phase_ids))
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if equivalent(first, second):
                union(first, second)
    groups: dict[str, list[str]] = {}
    for phase_id in ordered:
        groups.setdefault(find(phase_id), []).append(phase_id)
    return tuple(tuple(members) for _root, members in sorted(groups.items()))


def hybrid_gain_shortlist(
    references: Mapping[str, Sequence[ReferenceLine]],
    observed_records: Sequence[object],
    quick_scores: Mapping[str, object],
    *,
    limit: int,
    geometric_fraction: float = 0.35,
) -> tuple[str, ...]:
    """Combine quick residual-line ranking with affine-invariant retrieval."""

    shortlist_limit = max(1, int(limit))
    fraction = max(0.0, min(float(geometric_fraction), 1.0))
    geometric_count = min(shortlist_limit, int(math.ceil(shortlist_limit * fraction)))
    quick_count = shortlist_limit - geometric_count
    quick_order = sorted(
        references,
        key=lambda key: (-_score_value(quick_scores.get(key, 0.0)), key),
    )
    query_hashes = peak_geometric_hashes(observed_records, expanded=True)
    candidate_hashes = {
        ("BENCHMARK", key): peak_geometric_hashes(lines)
        for key, lines in references.items()
    }
    geometric_order = [
        item.key[1]
        for item in rank_fingerprint_candidates(query_hashes, candidate_hashes)
    ]

    selected: list[str] = []
    seen: set[str] = set()
    for key in quick_order[:quick_count]:
        if key not in seen:
            selected.append(key)
            seen.add(key)
    for key in geometric_order[:geometric_count]:
        if key not in seen:
            selected.append(key)
            seen.add(key)
    for order in (quick_order, geometric_order):
        for key in order:
            if len(selected) >= shortlist_limit:
                break
            if key not in seen:
                selected.append(key)
                seen.add(key)
    return tuple(selected[:shortlist_limit])


def rare_line_gain_shortlist(
    references: Mapping[str, Sequence[ReferenceLine]],
    observed_records: Sequence[object],
    quick_scores: Mapping[str, object],
    *,
    limit: int,
    rare_fraction: float = 0.25,
) -> tuple[str, ...]:
    """Reserve part of the shortlist for candidates matching selective residual lines."""

    shortlist_limit = max(1, int(limit))
    rare_count = min(
        shortlist_limit,
        max(1, int(math.ceil(shortlist_limit * max(0.0, min(float(rare_fraction), 1.0))))),
    )
    quick_count = max(0, shortlist_limit - rare_count)
    quick_order = sorted(
        references,
        key=lambda key: (-_score_value(quick_scores.get(key, 0.0)), key),
    )
    rare_scores = rare_line_candidate_scores(references, observed_records)
    rare_order = sorted(references, key=lambda key: (-rare_scores.get(key, 0.0), key))
    selected: list[str] = []
    seen: set[str] = set()
    for key in quick_order[:quick_count]:
        selected.append(key)
        seen.add(key)
    for key in rare_order[:rare_count]:
        if key not in seen:
            selected.append(key)
            seen.add(key)
    for order in (quick_order, rare_order):
        for key in order:
            if len(selected) >= shortlist_limit:
                break
            if key not in seen:
                selected.append(key)
                seen.add(key)
    return tuple(selected[:shortlist_limit])


def adaptive_gain_shortlist(
    references: Mapping[str, Sequence[ReferenceLine]],
    observed_records: Sequence[object],
    quick_scores: Mapping[str, object],
    *,
    limit: int,
) -> tuple[str, ...]:
    """Mirror the production residual-structure choice between Quick and Rare-line."""

    widths = []
    for record in observed_records:
        try:
            width = float(getattr(record, "fwhm"))
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(width) and width > 0.0:
            widths.append(width)
    expected_fwhm = float(statistics.median(widths)) if widths else 0.18
    summary = summarize_residual_evidence(
        observed_records,
        expected_fwhm=expected_fwhm,
    )
    if summary.kind == "none":
        return ()
    if summary.rare_line_fraction <= 0.0:
        return tuple(
            sorted(
                references,
                key=lambda key: (-_score_value(quick_scores.get(key, 0.0)), key),
            )[: max(1, int(limit))]
        )
    return rare_line_gain_shortlist(
        references,
        summary.significant_records,
        quick_scores,
        limit=limit,
        rare_fraction=summary.rare_line_fraction,
    )


def fused_line_gain_shortlist(
    references: Mapping[str, Sequence[ReferenceLine]],
    observed_records: Sequence[object],
    quick_scores: Mapping[str, object],
    *,
    limit: int,
    corroboration: float = 0.20,
) -> tuple[str, ...]:
    """Fuse complete quick and rare-line retrieval pools before profile scoring."""

    shortlist_limit = max(1, int(limit))
    quick_order = sorted(
        references,
        key=lambda key: (-_score_value(quick_scores.get(key, 0.0)), key),
    )
    line_scores = rare_line_candidate_scores(references, observed_records)
    line_order = sorted(references, key=lambda key: (-line_scores.get(key, 0.0), key))
    pool = set(quick_order[:shortlist_limit]) | set(line_order[:shortlist_limit])
    quick_rank = {key: index + 1 for index, key in enumerate(quick_order)}
    line_rank = {key: index + 1 for index, key in enumerate(line_order)}
    beta = max(0.0, min(float(corroboration), 1.0))

    def fused_score(key: str) -> float:
        quick = 1.0 / (8.0 + quick_rank[key])
        line = 1.0 / (8.0 + line_rank[key])
        return max(quick, line) + beta * min(quick, line)

    return tuple(sorted(pool, key=lambda key: (-fused_score(key), key))[:shortlist_limit])


def dominant_line_gain_shortlist(
    references: Mapping[str, Sequence[ReferenceLine]],
    observed_records: Sequence[object],
    quick_scores: Mapping[str, object],
    *,
    limit: int,
    dominant_fraction: float = 0.25,
    extra_limit: int = 0,
) -> tuple[str, ...]:
    """Reserve a small part of the shortlist for sparse-pattern candidates."""

    base_limit = max(1, int(limit))
    extra = max(0, int(extra_limit))
    shortlist_limit = base_limit + extra
    reserve = min(
        shortlist_limit,
        max(1, int(math.ceil(shortlist_limit * max(0.0, min(float(dominant_fraction), 1.0))))),
    )
    quick_order = sorted(
        references, key=lambda key: (-_score_value(quick_scores.get(key, 0.0)), key)
    )
    dominant_scores = dominant_line_candidate_scores(references, observed_records)
    dominant_order = sorted(
        references, key=lambda key: (-dominant_scores.get(key, 0.0), key)
    )
    selected: list[str] = []
    seen: set[str] = set()
    quick_count = base_limit if extra else max(0, shortlist_limit - reserve)
    for key in quick_order[:quick_count]:
        selected.append(key)
        seen.add(key)
    dominant_count = extra if extra else reserve
    for key in dominant_order[:dominant_count]:
        if dominant_scores.get(key, 0.0) > 0.0 and key not in seen:
            selected.append(key)
            seen.add(key)
    for key in quick_order:
        if len(selected) >= shortlist_limit:
            break
        if key not in seen:
            selected.append(key)
            seen.add(key)
    return tuple(selected[:shortlist_limit])


def dual_score_gain_shortlist(
    candidate_ids: Sequence[str],
    *,
    residual_scores: Mapping[str, object],
    original_scores: Mapping[str, object],
    limit: int,
    original_fraction: float = 0.25,
) -> tuple[str, ...]:
    """Combine residual evidence with the already available original Match ranking."""

    shortlist_limit = max(1, int(limit))
    original_count = min(
        shortlist_limit,
        max(1, int(math.ceil(shortlist_limit * max(0.0, min(float(original_fraction), 1.0))))),
    )
    residual_order = sorted(
        candidate_ids, key=lambda key: (-_score_value(residual_scores.get(key, 0.0)), key)
    )
    original_order = sorted(
        candidate_ids, key=lambda key: (-_score_value(original_scores.get(key, 0.0)), key)
    )
    selected: list[str] = []
    seen: set[str] = set()
    for key in residual_order[: max(0, shortlist_limit - original_count)]:
        selected.append(key)
        seen.add(key)
    for key in original_order[:original_count]:
        if key not in seen:
            selected.append(key)
            seen.add(key)
    for order in (residual_order, original_order):
        for key in order:
            if len(selected) >= shortlist_limit:
                break
            if key not in seen:
                selected.append(key)
                seen.add(key)
    return tuple(selected[:shortlist_limit])


def _score_value(value: object) -> float:
    score = getattr(value, "score", value)
    try:
        return float(score)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "JointGainCandidatePool",
    "adaptive_gain_shortlist",
    "dominant_line_gain_shortlist",
    "dual_score_gain_shortlist",
    "fused_line_gain_shortlist",
    "hybrid_gain_shortlist",
    "joint_gain_candidate_pool",
    "rare_line_gain_shortlist",
]
