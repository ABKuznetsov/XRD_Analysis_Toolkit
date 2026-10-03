from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from xrd_finder.services.gain_shortlist import significant_residual_records


DEFAULT_WAVELENGTH_ANGSTROM = 1.5406


@dataclass(frozen=True, slots=True)
class PowderDShell:
    """One observable powder line after coincident reflections are collapsed."""

    q: float
    d: float
    intensity: float
    multiplicity: int
    family_count: int
    hkl_directions: tuple[tuple[int, int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _GeometryPosting:
    phase_id: str
    weight: float
    shell_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ResidualGeometryIndex:
    phase_count: int
    q_log_bin: float
    pair_log_bin: float
    triplet_span_log_bin: float
    triplet_ratio_bin: float
    shell_postings: Mapping[int, tuple[_GeometryPosting, ...]]
    pair_postings: Mapping[int, tuple[_GeometryPosting, ...]]
    triplet_postings: Mapping[tuple[int, int], tuple[_GeometryPosting, ...]]


def powder_d_shells(
    records: Iterable[object],
    *,
    wavelength: float = DEFAULT_WAVELENGTH_ANGSTROM,
    zero_shift: float = 0.0,
    shell_relative_tolerance: float = 7.5e-4,
    strength_name: str = "intensity",
    max_shells: int | None = None,
    selection: str = "strongest",
    minimum_relative_intensity: float = 0.0,
) -> tuple[PowderDShell, ...]:
    """Collapse reflections into symmetry-independent powder d-shells.

    Candidate records preferentially use their crystallographic ``d`` value.
    Experimental records are converted from corrected 2theta with the active
    wavelength.  Consequently the resulting geometry is independent of the
    X-ray tube used to collect the pattern.
    """

    parsed: list[
        tuple[float, float, int, tuple[int, int, int] | None]
    ] = []
    for record in records:
        q = _record_q(record, wavelength=wavelength, zero_shift=zero_shift)
        strength = _record_strength(record, strength_name=strength_name)
        if q is None or strength is None:
            continue
        multiplicity = _positive_int(getattr(record, "multiplicity", 1), default=1)
        parsed.append((q, strength, multiplicity, _hkl_direction(record)))
    if not parsed:
        return ()

    parsed.sort(key=lambda item: item[0])
    tolerance = max(float(shell_relative_tolerance), 1.0e-6)
    grouped: list[list[tuple[float, float, int, tuple[int, int, int] | None]]] = []
    for row in parsed:
        if not grouped:
            grouped.append([row])
            continue
        previous = grouped[-1]
        weighted_q = sum(value[0] * value[1] for value in previous) / max(
            sum(value[1] for value in previous), 1.0e-12
        )
        relative_delta = abs(row[0] - weighted_q) / max(weighted_q, row[0], 1.0e-12)
        if relative_delta <= tolerance:
            previous.append(row)
        else:
            grouped.append([row])

    shells: list[PowderDShell] = []
    for group in grouped:
        intensity = sum(row[1] for row in group)
        q = sum(row[0] * row[1] for row in group) / max(intensity, 1.0e-12)
        directions = tuple(
            sorted({row[3] for row in group if row[3] is not None})
        )
        shells.append(
            PowderDShell(
                q=float(q),
                d=float(1.0 / q),
                intensity=float(intensity),
                multiplicity=sum(row[2] for row in group),
                family_count=len(group),
                hkl_directions=directions,
            )
        )

    maximum_intensity = max((shell.intensity for shell in shells), default=0.0)
    relative_floor = max(float(minimum_relative_intensity), 0.0)
    if relative_floor > 0.0 and maximum_intensity > 0.0:
        shells = [
            shell
            for shell in shells
            if shell.intensity / maximum_intensity >= relative_floor
        ]
    if selection == "low_q":
        shells = sorted(shells, key=lambda shell: shell.q)
    elif selection == "strongest":
        shells = sorted(shells, key=lambda shell: (-shell.intensity, shell.q))
    elif selection == "hybrid":
        limit = max(0, int(max_shells or len(shells)))
        low_q_count = (limit + 1) // 2
        low_q = sorted(shells, key=lambda shell: shell.q)[:low_q_count]
        selected_ids = {id(shell) for shell in low_q}
        strongest = [
            shell
            for shell in sorted(
                shells, key=lambda shell: (-shell.intensity, shell.q)
            )
            if id(shell) not in selected_ids
        ][: max(0, limit - len(low_q))]
        shells = [*low_q, *strongest]
    else:
        raise ValueError(f"Unsupported powder-shell selection: {selection}")
    if max_shells is not None:
        shells = shells[: max(0, int(max_shells))]
    shells = sorted(shells, key=lambda shell: shell.q)
    return tuple(shells)


def build_residual_geometry_index(
    candidate_peaks: Mapping[str, Iterable[object]],
    *,
    max_lines: int = 12,
    q_log_bin: float = 0.006,
    pair_log_bin: float = 0.010,
    triplet_ratio_bin: float = 0.025,
    shell_relative_tolerance: float = 7.5e-4,
    wavelength: float = DEFAULT_WAVELENGTH_ANGSTROM,
    shell_selection: str = "low_q",
    minimum_relative_intensity: float = 0.01,
    # Compatibility aliases for callers of the first experimental index.
    pair_bin_deg: float | None = None,
    ratio_bin: float | None = None,
) -> ResidualGeometryIndex:
    """Precompute scale-tolerant pair/triplet fingerprints of powder shells."""

    if pair_bin_deg is not None:
        pair_log_bin = max(float(pair_bin_deg) * 0.075, 0.0015)
    if ratio_bin is not None:
        triplet_ratio_bin = float(ratio_bin)
    pair_width = max(float(pair_log_bin), 0.0015)
    q_width = max(float(q_log_bin), 0.0015)
    ratio_width = max(float(triplet_ratio_bin), 0.004)
    span_width = pair_width
    shell_lists: dict[int, list[_GeometryPosting]] = {}
    pair_lists: dict[int, list[_GeometryPosting]] = {}
    triplet_lists: dict[tuple[int, int], list[_GeometryPosting]] = {}

    for raw_phase_id, peaks in candidate_peaks.items():
        phase_id = str(raw_phase_id)
        shells = powder_d_shells(
            peaks,
            wavelength=wavelength,
            shell_relative_tolerance=shell_relative_tolerance,
            strength_name="intensity",
            max_shells=max_lines,
            selection=shell_selection,
            minimum_relative_intensity=minimum_relative_intensity,
        )
        weights = _shell_weights(shells)
        for shell_id, shell in enumerate(shells):
            key = int(round(math.log(shell.q) / q_width))
            shell_lists.setdefault(key, []).append(
                _GeometryPosting(
                    phase_id,
                    weights[shell_id] * _shell_metadata_bonus(shell),
                    (shell_id,),
                )
            )
        for first_id, second_id in itertools.combinations(range(len(shells)), 2):
            first, second = shells[first_id], shells[second_id]
            log_ratio = math.log(second.q / first.q)
            if log_ratio <= 0.0:
                continue
            key = int(round(log_ratio / pair_width))
            weight = (
                math.sqrt(weights[first_id] * weights[second_id])
                * _hkl_pair_diversity(first, second)
                * _shell_metadata_bonus(first, second)
            )
            pair_lists.setdefault(key, []).append(
                _GeometryPosting(phase_id, weight, (first_id, second_id))
            )

        for first_id, middle_id, last_id in itertools.combinations(
            range(len(shells)), 3
        ):
            first, middle, last = (
                shells[first_id], shells[middle_id], shells[last_id]
            )
            log_span = math.log(last.q / first.q)
            q_span = last.q - first.q
            if log_span <= pair_width or q_span <= 0.0:
                continue
            inner_ratio = (middle.q - first.q) / q_span
            key = (
                int(round(log_span / span_width)),
                int(round(inner_ratio / ratio_width)),
            )
            weight = (
                (weights[first_id] * weights[middle_id] * weights[last_id])
                ** (1.0 / 3.0)
                * _hkl_triplet_diversity(first, middle, last)
                * _shell_metadata_bonus(first, middle, last)
            )
            triplet_lists.setdefault(key, []).append(
                _GeometryPosting(
                    phase_id, weight, (first_id, middle_id, last_id)
                )
            )

    return ResidualGeometryIndex(
        phase_count=len(candidate_peaks),
        q_log_bin=q_width,
        pair_log_bin=pair_width,
        triplet_span_log_bin=span_width,
        triplet_ratio_bin=ratio_width,
        shell_postings={
            key: tuple(sorted(value, key=lambda posting: posting.phase_id))
            for key, value in shell_lists.items()
        },
        pair_postings={
            key: tuple(sorted(value, key=lambda posting: posting.phase_id))
            for key, value in pair_lists.items()
        },
        triplet_postings={
            key: tuple(sorted(value, key=lambda posting: posting.phase_id))
            for key, value in triplet_lists.items()
        },
    )


def residual_geometry_scores(
    index: ResidualGeometryIndex,
    residual_records: Iterable[object],
    *,
    max_lines: int = 12,
    wavelength: float = DEFAULT_WAVELENGTH_ANGSTROM,
    zero_shift: float = 0.0,
    shell_relative_tolerance: float = 7.5e-4,
) -> tuple[dict[str, float], dict[str, int]]:
    """Vote by pair/triplet geometry expressed entirely in reciprocal space."""

    significant = significant_residual_records(residual_records)
    shells = powder_d_shells(
        significant,
        wavelength=wavelength,
        zero_shift=zero_shift,
        shell_relative_tolerance=shell_relative_tolerance,
        strength_name="area",
        max_shells=max_lines,
    )
    if len(shells) < 2:
        return {}, {}
    weights = _shell_weights(shells)
    scores: dict[str, float] = {}
    supported_shells: dict[str, set[int]] = {}
    best_evidence: dict[tuple[str, tuple[int, ...], str], float] = {}

    for shell_id, shell in enumerate(shells):
        center_key = int(round(math.log(shell.q) / index.q_log_bin))
        for key in range(center_key - 2, center_key + 3):
            postings = index.shell_postings.get(key, ())
            rarity = _posting_rarity(index.phase_count, postings)
            reliability = 1.0 / (1.0 + abs(key - center_key))
            for posting in postings:
                evidence_key = (posting.phase_id, posting.shell_ids, "shell")
                contribution = (
                    weights[shell_id] * posting.weight * reliability * rarity
                )
                best_evidence[evidence_key] = max(
                    best_evidence.get(evidence_key, 0.0), contribution
                )

    for first_id, second_id in itertools.combinations(range(len(shells)), 2):
        first, second = shells[first_id], shells[second_id]
        log_ratio = math.log(second.q / first.q)
        if log_ratio <= 0.0:
            continue
        center_key = int(round(log_ratio / index.pair_log_bin))
        observation_weight = math.sqrt(weights[first_id] * weights[second_id])
        for key in range(center_key - 1, center_key + 2):
            reliability = 1.0 / (1.0 + abs(key - center_key))
            postings = index.pair_postings.get(key, ())
            rarity = _posting_rarity(index.phase_count, postings)
            for posting in postings:
                evidence_key = (posting.phase_id, posting.shell_ids, "pair")
                contribution = (
                    observation_weight * posting.weight * reliability * rarity
                )
                best_evidence[evidence_key] = max(
                    best_evidence.get(evidence_key, 0.0), contribution
                )

    if len(shells) >= 3:
        for first_id, middle_id, last_id in itertools.combinations(
            range(len(shells)), 3
        ):
            first, middle, last = (
                shells[first_id], shells[middle_id], shells[last_id]
            )
            log_span = math.log(last.q / first.q)
            q_span = last.q - first.q
            if log_span <= index.pair_log_bin or q_span <= 0.0:
                continue
            inner_ratio = (middle.q - first.q) / q_span
            span_key = int(round(log_span / index.triplet_span_log_bin))
            ratio_key = int(round(inner_ratio / index.triplet_ratio_bin))
            observation_weight = (
                weights[first_id] * weights[middle_id] * weights[last_id]
            ) ** (1.0 / 3.0)
            for span_neighbor in range(span_key - 1, span_key + 2):
                for ratio_neighbor in range(ratio_key - 1, ratio_key + 2):
                    distance = abs(span_neighbor - span_key) + abs(
                        ratio_neighbor - ratio_key
                    )
                    reliability = 1.0 / (1.0 + distance)
                    postings = index.triplet_postings.get(
                        (span_neighbor, ratio_neighbor), ()
                    )
                    rarity = _posting_rarity(index.phase_count, postings)
                    for posting in postings:
                        evidence_key = (posting.phase_id, posting.shell_ids, "triplet")
                        contribution = (
                            observation_weight
                            * posting.weight
                            * reliability
                            * rarity
                        )
                        best_evidence[evidence_key] = max(
                            best_evidence.get(evidence_key, 0.0), contribution
                        )

    for (phase_id, shell_ids, evidence_type), contribution in best_evidence.items():
        type_weight = {"shell": 0.35, "pair": 0.75, "triplet": 1.0}[evidence_type]
        scores[phase_id] = scores.get(phase_id, 0.0) + contribution * type_weight
        supported_shells.setdefault(phase_id, set()).update(shell_ids)

    return scores, {
        phase_id: len(shell_ids)
        for phase_id, shell_ids in supported_shells.items()
    }


def _record_q(
    record: object,
    *,
    wavelength: float,
    zero_shift: float,
) -> float | None:
    try:
        d_spacing = float(getattr(record, "d"))
    except (TypeError, ValueError, AttributeError):
        d_spacing = math.nan
    if math.isfinite(d_spacing) and d_spacing > 0.0:
        return 1.0 / d_spacing
    try:
        two_theta = float(getattr(record, "two_theta")) - float(zero_shift)
        radiation = float(wavelength)
    except (TypeError, ValueError, AttributeError):
        return None
    if (
        not math.isfinite(two_theta)
        or not math.isfinite(radiation)
        or radiation <= 0.0
        or two_theta <= 0.0
        or two_theta >= 180.0
    ):
        return None
    q = 2.0 * math.sin(math.radians(two_theta / 2.0)) / radiation
    return q if math.isfinite(q) and q > 0.0 else None


def _record_strength(record: object, *, strength_name: str) -> float | None:
    values = (
        getattr(record, strength_name, 0.0),
        getattr(record, "area", 0.0),
        getattr(record, "height", 0.0),
        getattr(record, "prominence", 0.0),
        getattr(record, "intensity", 0.0),
    )
    for raw_value in values:
        try:
            value = float(raw_value or 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0.0:
            return value
    return None


def _shell_weights(shells: tuple[PowderDShell, ...]) -> tuple[float, ...]:
    maximum = max((shell.intensity for shell in shells), default=0.0)
    if maximum <= 0.0:
        return tuple(1.0 for _shell in shells)
    # Geometry remains dominant: intensity only changes a shell weight by 25%.
    return tuple(
        0.75 + 0.25 * math.sqrt(max(shell.intensity, 0.0) / maximum)
        for shell in shells
    )


def _shell_metadata_bonus(*shells: PowderDShell) -> float:
    information = sum(
        math.log1p(max(shell.multiplicity, 1))
        + 0.5 * math.log1p(max(shell.family_count, 1))
        for shell in shells
    ) / max(len(shells), 1)
    return min(1.20, 1.0 + 0.035 * information)


def _posting_rarity(
    phase_count: int,
    postings: tuple[_GeometryPosting, ...],
) -> float:
    if not postings:
        return 0.0
    distinct_phases = len({posting.phase_id for posting in postings})
    return 1.0 + math.log(
        (max(int(phase_count), 1) + 1.0) / (distinct_phases + 1.0)
    )


def _hkl_pair_diversity(first: PowderDShell, second: PowderDShell) -> float:
    if not first.hkl_directions or not second.hkl_directions:
        return 1.0
    return 0.25 if set(first.hkl_directions) == set(second.hkl_directions) else 1.0


def _hkl_triplet_diversity(
    first: PowderDShell,
    middle: PowderDShell,
    last: PowderDShell,
) -> float:
    directions = [
        shell.hkl_directions[0]
        for shell in (first, middle, last)
        if shell.hkl_directions
    ]
    if len(directions) < 2:
        return 1.0
    distinct = len(set(directions))
    if distinct <= 1:
        return 0.20
    if distinct == 2:
        return 0.60
    return 1.0


def _hkl_direction(record: object) -> tuple[int, int, int] | None:
    raw_hkl = getattr(record, "hkl", None)
    if raw_hkl is not None:
        try:
            h, k, l = (int(round(float(value))) for value in raw_hkl[:3])
        except (TypeError, ValueError, IndexError):
            return None
    else:
        try:
            h = int(round(float(getattr(record, "h"))))
            k = int(round(float(getattr(record, "k"))))
            l = int(round(float(getattr(record, "l"))))
        except (TypeError, ValueError, AttributeError):
            return None
    divisor = math.gcd(math.gcd(abs(h), abs(k)), abs(l))
    if divisor <= 0:
        return None
    direction = (h // divisor, k // divisor, l // divisor)
    for component in direction:
        if component < 0:
            direction = tuple(-value for value in direction)
            break
        if component > 0:
            break
    return direction


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


__all__ = [
    "PowderDShell",
    "ResidualGeometryIndex",
    "build_residual_geometry_index",
    "powder_d_shells",
    "residual_geometry_scores",
]
