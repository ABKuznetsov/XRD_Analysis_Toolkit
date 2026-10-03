from __future__ import annotations

from dataclasses import dataclass
import hashlib
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class PhaseDescriptor:
    phase_id: str
    family_id: str
    category: str = "inorganic"


@dataclass(frozen=True, slots=True)
class SplitAssignment:
    phase_id: str
    family_id: str
    split: str


def assign_split_families(
    phases: Sequence[PhaseDescriptor],
    *,
    seed: int,
) -> tuple[SplitAssignment, ...]:
    families = sorted({phase.family_id for phase in phases})
    ordered = sorted(
        families,
        key=lambda family: hashlib.sha256(f"{seed}:{family}".encode("utf-8")).digest(),
    )
    count = len(ordered)
    train_end = max(1, round(count * 0.60)) if count else 0
    validation_end = max(train_end + 1, round(count * 0.80)) if count >= 3 else train_end
    validation_end = min(validation_end, max(count - 1, train_end)) if count >= 3 else validation_end
    family_split = {}
    for index, family in enumerate(ordered):
        if index < train_end:
            split = "train"
        elif index < validation_end:
            split = "validation"
        else:
            split = "test"
        family_split[family] = split
    return tuple(
        SplitAssignment(phase.phase_id, phase.family_id, family_split[phase.family_id])
        for phase in sorted(phases, key=lambda item: item.phase_id)
    )


__all__ = ["PhaseDescriptor", "SplitAssignment", "assign_split_families"]
