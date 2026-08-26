from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterator

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer, HierarchyReport
from crystal_viewer.analysis.inorganic_topology import (
    InorganicTopologyReport,
    build_inorganic_topology,
)
from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult, build_periodic_bonds
from crystal_viewer.analysis.organic.bond_layers import build_bond_layers
from crystal_viewer.analysis.organic.pipeline import (
    OrganicAnalysisBundle,
    iter_analyze_organic,
)
from crystal_viewer.analysis.structure_profile import (
    ProfileDecision,
    ResolvedProfile,
    resolve_structure_profile,
)
from crystal_viewer.analysis.structural_analysis import (
    CoordinationEnvironment,
    RingCandidate,
    StructuralAnalysis,
    StructuralAnalysisSettings,
    StructuralUnitCandidate,
)
from crystal_viewer.analysis.structural_domains import StructuralDomain
from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence
from crystal_viewer.core.model import CrystalStructure


class AnalysisStage(StrEnum):
    BONDS = "bonds"
    POLYHEDRA = "polyhedra"
    UNITS = "units"
    TOPOLOGY = "topology"


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    stage: AnalysisStage
    periodic_bonds: PeriodicBondResult
    coordination_environments: tuple[CoordinationEnvironment, ...] = ()
    polyhedron_roles: tuple[PolyhedronRoleEvidence, ...] = ()
    hierarchy: HierarchyReport = field(default_factory=HierarchyReport)
    structural_analysis: StructuralAnalysis | None = None
    inorganic_topology: InorganicTopologyReport | None = None
    profile_decision: ProfileDecision | None = None


def _unit_candidates(
    hierarchy: HierarchyReport,
    *,
    complete: bool,
) -> tuple[tuple[RingCandidate, ...], tuple[StructuralUnitCandidate, ...]]:
    rings: list[RingCandidate] = []
    units: list[StructuralUnitCandidate] = []
    for unit in hierarchy.structural_units:
        is_ring = "-membered ring · " in unit.classification
        composition = (
            unit.classification.rsplit(" · ", 1)[1]
            if " · " in unit.classification
            else ""
        )
        kind = (
            "ring"
            if is_ring
            else "interstitial coordination"
            if unit.classification == "interlayer polyhedron"
            else unit.classification
        )
        units.append(
            StructuralUnitCandidate(
                kind=kind,
                member_ids=unit.polyhedron_ids,
                atom_indices=unit.atom_indices,
                periodic_rank=unit.periodic_rank,
                composition=composition,
                confidence=1.0,
                primary=unit.classification != "coordination context",
                complete=complete,
            )
        )
        if is_ring:
            rings.append(
                RingCandidate(
                    member_ids=unit.polyhedron_ids,
                    member_images=((0, 0, 0),) * len(unit.polyhedron_ids),
                    atom_indices=unit.atom_indices,
                    size=len(unit.polyhedron_ids),
                    composition=composition,
                    confidence=1.0,
                )
            )
    return tuple(rings), tuple(units)


def _nomenclature(
    hierarchy: HierarchyReport,
    rings: tuple[RingCandidate, ...],
    roles: tuple[PolyhedronRoleEvidence, ...],
):
    from crystal_viewer.analysis.nomenclature import assign_nomenclature

    items = [
        assignment
        for domain in hierarchy.structural_domains
        if (
            assignment := assign_nomenclature(domain, hierarchy.polyhedra, rings)
        ) is not None
    ]
    named_members = {
        frozenset(domain.polyhedron_ids)
        for domain in hierarchy.structural_domains
        if any(item.domain_id == domain.id for item in items)
    }
    role_by_center = {item.center_index: item for item in roles}
    polyhedron_by_id = {item.id: item for item in hierarchy.polyhedra}
    for unit in hierarchy.structural_units:
        if frozenset(unit.polyhedron_ids) in named_members or unit.classification in {
            "interlayer polyhedron",
            "ambiguous coordination environment",
        }:
            continue
        evidence = [
            role_by_center[polyhedron_by_id[identifier].center_index]
            for identifier in unit.polyhedron_ids
            if polyhedron_by_id[identifier].center_index in role_by_center
        ]
        confidence = (
            math.fsum(item.confidence for item in evidence) / len(evidence)
            if evidence
            else 0.0
        )
        candidate = StructuralDomain(
            id=unit.id,
            polyhedron_ids=unit.polyhedron_ids,
            atom_indices=unit.atom_indices,
            periodic_rank=unit.periodic_rank,
            classification=(
                "ring" if "-membered ring" in unit.classification else unit.classification
            ),
            role_confidence=confidence,
        )
        assignment = assign_nomenclature(candidate, hierarchy.polyhedra, rings)
        if assignment is not None:
            items.append(assignment)
    return tuple(items)


def iter_analyze_structure(
    structure: CrystalStructure,
    settings: StructuralAnalysisSettings | None = None,
    *,
    periodic_bonds: PeriodicBondResult | None = None,
    profile_decision: ProfileDecision | None = None,
) -> Iterator[AnalysisSnapshot]:
    settings = settings or StructuralAnalysisSettings()
    settings.validate()
    periodic_bonds = periodic_bonds or build_periodic_bonds(
        structure, settings.bond_settings
    )
    yield AnalysisSnapshot(
        AnalysisStage.BONDS,
        periodic_bonds,
        profile_decision=profile_decision,
    )

    from crystal_viewer.analysis.coordination import describe_coordination
    from crystal_viewer.analysis.structural_roles import classify_polyhedron_roles

    environments = describe_coordination(structure, periodic_bonds, settings)
    roles = classify_polyhedron_roles(structure, periodic_bonds, environments)
    analyzer = HierarchyAnalyzer()
    polyhedra = analyzer.detect_polyhedra_from_environments(structure, environments)
    connections = analyzer.connect_polyhedra(polyhedra)
    polyhedron_hierarchy = HierarchyReport(
        polyhedra=polyhedra,
        polyhedron_connections=connections,
    )
    yield AnalysisSnapshot(
        AnalysisStage.POLYHEDRA,
        periodic_bonds,
        environments,
        roles,
        polyhedron_hierarchy,
        profile_decision=profile_decision,
    )

    hierarchy = analyzer.assemble(
        structure,
        polyhedra,
        connections,
        role_evidence=roles,
    )
    yield AnalysisSnapshot(
        AnalysisStage.UNITS,
        periodic_bonds,
        environments,
        roles,
        hierarchy,
        profile_decision=profile_decision,
    )

    complete = periodic_bonds.complete and all(item.complete for item in environments)
    exact = complete and not any(item.ambiguous for item in environments) and not any(
        item.role == "ambiguous" for item in roles
    )
    rings, units = _unit_candidates(hierarchy, complete=complete)
    warnings = tuple(
        dict.fromkeys(
            (
                *periodic_bonds.warnings,
                *(warning for item in environments for warning in item.warnings),
            )
        )
    )
    analysis = StructuralAnalysis(
        settings=settings,
        periodic_bonds=periodic_bonds,
        coordination_environments=environments,
        rings=rings,
        structural_units=units,
        polyhedron_roles=roles,
        structural_domains=tuple(hierarchy.structural_domains),
        nomenclature=_nomenclature(hierarchy, rings, roles),
        complete=complete,
        exact=exact,
        warnings=warnings,
    )
    topology = build_inorganic_topology(structure, hierarchy, roles)
    yield AnalysisSnapshot(
        AnalysisStage.TOPOLOGY,
        periodic_bonds,
        environments,
        roles,
        hierarchy,
        analysis,
        topology,
        profile_decision,
    )


def iter_analyze_document(
    structure: CrystalStructure,
    settings: StructuralAnalysisSettings | None = None,
) -> Iterator[AnalysisSnapshot | OrganicAnalysisBundle]:
    """Analyze one document through exactly one scientific profile branch."""
    settings = settings or StructuralAnalysisSettings()
    settings.validate()
    periodic_bonds = build_periodic_bonds(structure, settings.bond_settings)
    layers = build_bond_layers(structure, periodic_bonds)
    profile = resolve_structure_profile(
        structure,
        periodic_bonds,
        layers,
        requested=settings.profile.requested,
    )
    if profile.resolved is ResolvedProfile.INORGANIC:
        yield from iter_analyze_structure(
            structure,
            settings,
            periodic_bonds=periodic_bonds,
            profile_decision=profile,
        )
        return
    yield from iter_analyze_organic(
        structure,
        settings,
        periodic_bonds=periodic_bonds,
        layers=layers,
        profile=profile,
    )


__all__ = [
    "AnalysisSnapshot",
    "AnalysisStage",
    "iter_analyze_document",
    "iter_analyze_structure",
]
