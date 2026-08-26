"""Explainable candidate viewing directions for side-by-side structures."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import numpy as np

from crystal_viewer.core.document import StructureDocument


@dataclass(frozen=True, slots=True)
class ProjectionCandidate:
    first_direction: str
    second_direction: str
    evidence: str
    score_components: Mapping[str, float]
    mirrored: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "score_components",
            MappingProxyType(dict(self.score_components)),
        )


def _axis_data(document: StructureDocument) -> dict[str, tuple[float, tuple[float, float]]]:
    cell = document.structure.cell
    return {
        "a": (cell.a, tuple(sorted((cell.beta, cell.gamma)))),
        "b": (cell.b, tuple(sorted((cell.alpha, cell.gamma)))),
        "c": (cell.c, tuple(sorted((cell.alpha, cell.beta)))),
    }


def _maximum_periodic_rank(document: StructureDocument) -> int | None:
    topology = document.inorganic_topology
    if topology is None or not topology.interpretable:
        return None
    return max((component.periodic_rank for component in topology.components), default=None)


def projection_candidates(
    first: StructureDocument,
    second: StructureDocument,
    limit: int = 3,
) -> tuple[ProjectionCandidate, ...]:
    if limit < 1:
        return ()
    first_axes = _axis_data(first)
    second_axes = _axis_data(second)
    first_rank = _maximum_periodic_rank(first)
    second_rank = _maximum_periodic_rank(second)
    rank_penalty = (
        abs(first_rank - second_rank) / 3.0
        if first_rank is not None and second_rank is not None
        else 0.0
    )
    mirrored = bool(
        np.linalg.det(first.structure.cell.matrix)
        * np.linalg.det(second.structure.cell.matrix)
        < 0
    )

    ranked: list[tuple[float, ProjectionCandidate]] = []
    for first_name, (first_length, first_angles) in first_axes.items():
        for second_name, (second_length, second_angles) in second_axes.items():
            length_delta = abs(first_length - second_length) / max(first_length, second_length)
            angle_delta = sum(
                abs(left - right)
                for left, right in zip(first_angles, second_angles, strict=True)
            ) / 360.0
            score = length_delta + 0.25 * angle_delta + 0.5 * rank_penalty
            evidence = (
                f"length {first_name}={first_length:.4g} Å vs "
                f"{second_name}={second_length:.4g} Å; "
                f"angle signature Δ={angle_delta:.3g}"
            )
            if first_rank is not None and second_rank is not None:
                evidence += f"; periodic rank {first_rank} vs {second_rank}"
            if mirrored:
                evidence += "; mirrored handedness candidate"
            ranked.append(
                (
                    score,
                    ProjectionCandidate(
                        first_name,
                        second_name,
                        evidence,
                        {
                            "length_delta": length_delta,
                            "angle_signature_delta": angle_delta,
                            "rank_penalty": rank_penalty,
                            "ordering_score": score,
                        },
                        mirrored,
                    ),
                )
            )
    ranked.sort(key=lambda item: (item[0], item[1].first_direction, item[1].second_direction))
    return tuple(candidate for _, candidate in ranked[:limit])
