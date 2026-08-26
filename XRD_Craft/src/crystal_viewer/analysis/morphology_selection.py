from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from crystal_viewer.analysis.morphology import Hkl, MorphologyPlane
from crystal_viewer.analysis.morphology_geometry import (
    InvalidMorphologyError,
    build_morphology_model,
)
from crystal_viewer.core.model import UnitCell


@dataclass(frozen=True, slots=True)
class PrimaryFormSelection:
    active_families: tuple[Hkl, ...]
    reference_area_by_family: Mapping[Hkl, float]
    reference_fraction_by_family: Mapping[Hkl, float]
    coverage: float
    used_full_fallback: bool = False
    warnings: tuple[str, ...] = ()


def with_active_families(
    planes: tuple[MorphologyPlane, ...] | list[MorphologyPlane],
    active_families: tuple[Hkl, ...] | set[Hkl],
) -> tuple[MorphologyPlane, ...]:
    active = set(active_families)
    return tuple(replace(plane, enabled=plane.family.hkl in active) for plane in planes)


def select_primary_forms(
    cell: UnitCell,
    planes: tuple[MorphologyPlane, ...] | list[MorphologyPlane],
    *,
    target: float = 0.80,
) -> PrimaryFormSelection:
    target_value = float(target)
    if not math.isfinite(target_value) or not 0.0 < target_value <= 1.0:
        raise ValueError("Primary-area target must be finite and in the interval (0, 1].")

    plane_tuple = tuple(planes)
    all_families = tuple(plane.family.hkl for plane in plane_tuple)
    reference_planes = with_active_families(plane_tuple, set(all_families))
    reference = build_morphology_model(cell, reference_planes)
    ranked = sorted(
        (
            (family, float(fraction))
            for family, fraction in reference.fraction_by_family.items()
            if fraction > 0.0
        ),
        key=lambda item: (-item[1], item[0]),
    )

    coverage = 0.0
    minimum_count = 0
    for minimum_count, (_family, fraction) in enumerate(ranked, start=1):
        coverage = math.fsum(item[1] for item in ranked[:minimum_count])
        if coverage + 1e-12 >= target_value:
            break

    accepted: tuple[Hkl, ...] | None = None
    accepted_coverage = coverage
    invalid_codes = {"empty", "unbounded", "degenerate", "empty-intersection"}
    for count in range(minimum_count, len(ranked) + 1):
        candidate = tuple(item[0] for item in ranked[:count])
        try:
            build_morphology_model(cell, with_active_families(reference_planes, candidate))
        except InvalidMorphologyError as error:
            if error.code not in invalid_codes:
                raise
            continue
        accepted = candidate
        accepted_coverage = math.fsum(item[1] for item in ranked[:count])
        break

    warnings: tuple[str, ...] = ()
    used_full_fallback = False
    if accepted is None:
        accepted = tuple(item[0] for item in ranked)
        accepted_coverage = math.fsum(item[1] for item in ranked)
        build_morphology_model(cell, with_active_families(reference_planes, accepted))
        used_full_fallback = True
    elif len(accepted) == len(ranked) and minimum_count < len(ranked):
        used_full_fallback = True

    if used_full_fallback:
        warnings = (
            "All manifested BFDH families were retained because a smaller ranked set did not bound a solid.",
        )

    return PrimaryFormSelection(
        active_families=accepted,
        reference_area_by_family=MappingProxyType(dict(reference.area_by_family)),
        reference_fraction_by_family=MappingProxyType(dict(reference.fraction_by_family)),
        coverage=float(accepted_coverage),
        used_full_fallback=used_full_fallback,
        warnings=warnings,
    )


__all__ = ["PrimaryFormSelection", "select_primary_forms", "with_active_families"]
