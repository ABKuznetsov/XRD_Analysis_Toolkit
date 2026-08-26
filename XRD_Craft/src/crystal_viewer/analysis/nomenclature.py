"""Evidence-only mineralogical names layered over generic topology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from crystal_viewer.analysis.hierarchy import CoordinationPolyhedron
    from crystal_viewer.analysis.structural_analysis import RingCandidate
    from crystal_viewer.analysis.structural_domains import StructuralDomain


@dataclass(frozen=True, slots=True)
class NomenclatureAssignment:
    domain_id: str
    vocabulary: str
    descriptor: str
    evidence: tuple[str, ...]
    confidence: float
    warnings: tuple[str, ...] = ()


def _silicate_descriptor(classification: str, rank: int) -> str | None:
    if rank >= 3:
        return "tectosilicate"
    if rank == 2:
        return "phyllosilicate"
    if rank == 1:
        return "inosilicate"
    return {
        "island": "nesosilicate",
        "dimer": "sorosilicate",
        "ring": "cyclosilicate",
    }.get(classification)


def assign_nomenclature(
    domain: StructuralDomain,
    polyhedra: Iterable[CoordinationPolyhedron],
    rings: Iterable[RingCandidate],
) -> NomenclatureAssignment | None:
    """Name an established domain without changing its graph or membership."""
    del rings  # Reserved for nested-ring evidence in extended domains.
    lookup = {item.id: item for item in polyhedra}
    try:
        members = tuple(lookup[identifier] for identifier in domain.polyhedron_ids)
    except KeyError:
        return None
    if not members:
        return None

    centre_components = [
        tuple(part for part in item.center_element.split("/") if part)
        for item in members
    ]
    if (
        all(item.coordination_number == 4 for item in members)
        and all(set(parts) <= {"Si", "Al"} for parts in centre_components)
        and any("Si" in parts for parts in centre_components)
    ):
        descriptor = _silicate_descriptor(domain.classification, domain.periodic_rank)
        if descriptor is None:
            return None
        return NomenclatureAssignment(
            domain.id,
            "silicate",
            descriptor,
            (
                "Si-led tetrahedral domain",
                f"generic topology: {domain.classification}, rank {domain.periodic_rank}",
            ),
            domain.role_confidence,
        )

    if all(item.center_element == "B" and item.coordination_number in {3, 4} for item in members):
        bo3 = sum(item.coordination_number == 3 for item in members)
        bo4 = sum(item.coordination_number == 4 for item in members)
        counts = " + ".join(
            part
            for part in (
                f"{bo3} BO3" if bo3 else "",
                f"{bo4} BO4" if bo4 else "",
            )
            if part
        )
        prefix = (
            f"{len(members)}-membered borate FBB"
            if domain.classification == "ring"
            else f"borate FBB — {domain.classification}"
            if domain.periodic_rank == 0 and len(members) > 1
            else f"borate {domain.classification}"
        )
        return NomenclatureAssignment(
            domain.id,
            "borate",
            f"{prefix} ({counts})",
            (
                f"B-centred BO3/BO4 domain: {bo3}/{bo4}",
                f"generic topology: {domain.classification}, rank {domain.periodic_rank}",
            ),
            domain.role_confidence,
        )
    return None


__all__ = ["NomenclatureAssignment", "assign_nomenclature"]
