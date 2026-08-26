from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import linear_sum_assignment

from crystal_viewer.knowledge.model import (
    InterpretationChanges,
    KnowledgePreset,
    MotifFingerprint,
)


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    topology_score: float
    chemistry_score: float
    geometry_score: float
    node_pairs: tuple[tuple[int, int], ...]
    summary: str
    diagnostics: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PresetProposal:
    preset_id: str
    name: str
    confidence: float
    evidence: MatchEvidence
    changes: InterpretationChanges


def _element_similarity(first: str, second: str) -> float:
    if first == second:
        return 1.0
    if "__vacancy__" in {first, second}:
        return 0.0
    try:
        from pymatgen.core import Element

        left = Element(first)
        right = Element(second)
    except (KeyError, TypeError, ValueError):
        return 0.0
    if left.group == right.group:
        return 0.8
    row_gap = abs(int(left.row) - int(right.row))
    group_gap = abs(int(left.group) - int(right.group))
    atomic_gap = abs(int(left.Z) - int(right.Z))
    return max(
        0.0,
        0.55
        * math.exp(-0.7 * row_gap - 0.35 * group_gap - 0.04 * atomic_gap),
    )


def _distribution(payload) -> dict[str, float] | None:
    result: dict[str, float] = {}
    try:
        for element, scaled in payload:
            value = float(scaled) / 1_000_000.0
            if not math.isfinite(value) or value < 0.0:
                return None
            result[str(element)] = result.get(str(element), 0.0) + value
    except (TypeError, ValueError):
        return None
    total = math.fsum(result.values())
    if total < 1.0:
        result["__vacancy__"] = 1.0 - total
    return result


def _distribution_similarity(first_payload, second_payload) -> float | None:
    first = _distribution(first_payload)
    second = _distribution(second_payload)
    if first is None or second is None:
        return None
    denominator = max(math.fsum(first.values()), math.fsum(second.values()), 1.0)
    candidates = sorted(
        (
            (_element_similarity(left, right), left, right)
            for left in first
            for right in second
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    left_mass = dict(first)
    right_mass = dict(second)
    score = 0.0
    for similarity, left, right in candidates:
        if similarity <= 0.0:
            continue
        flow = min(left_mass[left], right_mass[right])
        if flow <= 0.0:
            continue
        score += flow * similarity
        left_mass[left] -= flow
        right_mass[right] -= flow
    return min(1.0, max(0.0, score / denominator))


def _geometry_similarity(first, second) -> float | None:
    try:
        first_ratios = tuple(float(value) for value in first[4])
        second_ratios = tuple(float(value) for value in second[4])
        if len(first_ratios) != len(second_ratios):
            return 0.0
        values = (*first_ratios, *second_ratios, float(first[5]), float(second[5]), float(first[6]), float(second[6]))
        if not all(math.isfinite(value) for value in values):
            return None
        ratio_rms = (
            math.sqrt(
                math.fsum((left - right) ** 2 for left, right in zip(first_ratios, second_ratios, strict=True))
                / len(first_ratios)
            )
            / 1000.0
            if first_ratios
            else 0.0
        )
        distortion = abs(float(first[5]) - float(second[5])) / 500.0
        angle = abs(float(first[6]) - float(second[6])) / 500.0
    except (IndexError, TypeError, ValueError, OverflowError):
        return None
    scaled_rms = math.sqrt((ratio_rms**2 + distortion**2 + angle**2) / 3.0)
    return min(1.0, max(0.0, math.exp(-scaled_rms)))


def _node_scores(first, second) -> tuple[float, float] | None:
    try:
        if first[0] != "node" or second[0] != "node" or int(first[1]) != int(second[1]):
            return None
        if tuple(first[7]) != tuple(second[7]):
            return None
        center = _distribution_similarity(first[2], second[2])
        ligand = _distribution_similarity(first[3], second[3])
        geometry = _geometry_similarity(first, second)
    except (IndexError, TypeError, ValueError):
        return None
    if center is None or ligand is None or geometry is None:
        return None
    return (center + ligand) / 2.0, geometry


def _compatible_topology(first: MotifFingerprint, second: MotifFingerprint) -> bool:
    return (
        first.algorithm == second.algorithm
        and bool(first.topology_digest)
        and first.topology_digest == second.topology_digest
        and first.periodic_rank == second.periodic_rank
        and len(first.nodes) == len(second.nodes)
        and len(first.edges) == len(second.edges)
    )


def _score(target: MotifFingerprint, preset: KnowledgePreset) -> tuple[float, MatchEvidence] | None:
    candidate = preset.fingerprint
    if candidate is None or not _compatible_topology(target, candidate):
        return None
    count = len(target.nodes)
    chemistry = np.full((count, count), -1.0, dtype=float)
    geometry = np.full((count, count), -1.0, dtype=float)
    combined = np.full((count, count), -1.0, dtype=float)
    for first_index, first in enumerate(target.nodes):
        for second_index, second in enumerate(candidate.nodes):
            scores = _node_scores(first, second)
            if scores is None:
                continue
            chemistry[first_index, second_index], geometry[first_index, second_index] = scores
            combined[first_index, second_index] = 0.625 * scores[0] + 0.375 * scores[1]
    if count == 0 or np.any(np.max(combined, axis=1) < 0.0):
        return None
    rows, columns = linear_sum_assignment(-combined)
    if any(combined[row, column] < 0.0 for row, column in zip(rows, columns, strict=True)):
        return None
    chemistry_score = float(np.mean([chemistry[row, column] for row, column in zip(rows, columns, strict=True)]))
    geometry_score = float(np.mean([geometry[row, column] for row, column in zip(rows, columns, strict=True)]))
    total = 0.60 + 0.25 * chemistry_score + 0.15 * geometry_score
    evidence = MatchEvidence(
        topology_score=1.0,
        chemistry_score=chemistry_score,
        geometry_score=geometry_score,
        node_pairs=tuple((int(row), int(column)) for row, column in zip(rows, columns, strict=True)),
        summary=(
            "periodic topology matched; "
            f"chemistry {chemistry_score:.2f}; geometry {geometry_score:.2f}"
        ),
    )
    return min(1.0, max(0.0, total)), evidence


def best_preset_proposal(
    target: MotifFingerprint,
    presets: Iterable[KnowledgePreset],
    *,
    minimum_confidence: float = 0.85,
    minimum_margin: float = 0.10,
    maximum_states: int = 50_000,
    maximum_seconds: float = 5.0,
) -> PresetProposal | None:
    if not (0.0 <= minimum_confidence <= 1.0 and 0.0 <= minimum_margin <= 1.0):
        raise ValueError("confidence and margin must be between zero and one")
    if maximum_states < 1 or not math.isfinite(maximum_seconds) or maximum_seconds <= 0.0:
        raise ValueError("matching limits must be positive")
    started = time.monotonic()
    scored: list[tuple[float, str, KnowledgePreset, MatchEvidence]] = []
    for state, preset in enumerate(presets, start=1):
        if state > maximum_states or time.monotonic() - started >= maximum_seconds:
            return None
        if preset.scope != "reusable":
            continue
        result = _score(target, preset)
        if result is None:
            continue
        score, evidence = result
        scored.append((score, preset.id, preset, evidence))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored or scored[0][0] < minimum_confidence:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < minimum_margin:
        return None
    score, _identifier, preset, evidence = scored[0]
    return PresetProposal(
        preset_id=preset.id,
        name=preset.changes.name or preset.id,
        confidence=score,
        evidence=evidence,
        changes=preset.changes,
    )


__all__ = [
    "MatchEvidence",
    "PresetProposal",
    "best_preset_proposal",
]
