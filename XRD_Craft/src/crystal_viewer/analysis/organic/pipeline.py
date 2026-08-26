from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator

from crystal_viewer.analysis.organic.bond_layers import build_bond_layers
from crystal_viewer.analysis.organic.components import ComponentReport, build_components
from crystal_viewer.analysis.organic.contacts import ContactReport, build_contacts
from crystal_viewer.analysis.organic.model import BondLayerReport
from crystal_viewer.analysis.organic.packing import PackingReport, build_packing
from crystal_viewer.analysis.organic.reticular import ReticularReport, build_reticular_network
from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult, build_periodic_bonds
from crystal_viewer.analysis.structure_profile import (
    ProfileDecision,
    ResolvedProfile,
    resolve_structure_profile,
)
from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings
from crystal_viewer.core.model import CrystalStructure


class OrganicAnalysisStage(StrEnum):
    BONDS_PROFILE = "bonds/profile"
    COMPONENTS = "components"
    CONTACTS = "contacts"
    PACKING = "packing"
    RETICULAR = "reticular"


@dataclass(frozen=True, slots=True)
class OrganicAnalysisReport:
    profile: ProfileDecision
    periodic_bonds: PeriodicBondResult
    bonds: BondLayerReport
    components: ComponentReport | None = None
    contacts: ContactReport | None = None
    packing: PackingReport | None = None
    reticular: ReticularReport | None = None
    complete: bool = False
    warnings: tuple[str, ...] = ()
    method_version: str = "organic-analysis-v1"


@dataclass(frozen=True, slots=True)
class OrganicAnalysisBundle:
    stage: OrganicAnalysisStage
    report: OrganicAnalysisReport


def iter_analyze_organic(
    structure: CrystalStructure,
    settings: StructuralAnalysisSettings | None = None,
    *,
    periodic_bonds: PeriodicBondResult | None = None,
    layers: BondLayerReport | None = None,
    profile: ProfileDecision | None = None,
) -> Iterator[OrganicAnalysisBundle]:
    settings = settings or StructuralAnalysisSettings()
    settings.validate()
    periodic_bonds = periodic_bonds or build_periodic_bonds(structure, settings.bond_settings)
    layers = layers or build_bond_layers(structure, periodic_bonds)
    profile = profile or resolve_structure_profile(
        structure, periodic_bonds, layers, requested=settings.profile.requested
    )
    if profile.resolved is ResolvedProfile.INORGANIC:
        raise ValueError("organic pipeline requires a molecular or reticular profile")

    warnings = tuple(dict.fromkeys((*profile.warnings, *layers.warnings)))
    report = OrganicAnalysisReport(profile, periodic_bonds, layers, warnings=warnings)
    yield OrganicAnalysisBundle(OrganicAnalysisStage.BONDS_PROFILE, report)

    components = build_components(
        structure,
        layers,
        maximum_ring_size=settings.maximum_ring_size,
    )
    component_warnings = tuple(dict.fromkeys((*warnings, *components.warnings)))
    report = OrganicAnalysisReport(
        profile,
        periodic_bonds,
        layers,
        components=components,
        warnings=component_warnings,
    )
    yield OrganicAnalysisBundle(OrganicAnalysisStage.COMPONENTS, report)

    contacts = build_contacts(structure, layers, components)
    contact_warnings = tuple(dict.fromkeys((*component_warnings, *contacts.warnings)))
    report = OrganicAnalysisReport(
        profile,
        periodic_bonds,
        layers,
        components=components,
        contacts=contacts,
        warnings=contact_warnings,
    )
    yield OrganicAnalysisBundle(OrganicAnalysisStage.CONTACTS, report)

    packing = build_packing(structure, components, contacts)
    packing_warnings = tuple(dict.fromkeys((*contact_warnings, *packing.warnings)))
    report = OrganicAnalysisReport(
        profile,
        periodic_bonds,
        layers,
        components=components,
        contacts=contacts,
        packing=packing,
        complete=(
            layers.complete
            and components.complete
            and contacts.complete
            and packing.complete
        ),
        warnings=packing_warnings,
    )
    yield OrganicAnalysisBundle(OrganicAnalysisStage.PACKING, report)

    if profile.resolved is ResolvedProfile.RETICULAR:
        reticular = build_reticular_network(structure, layers, components)
        reticular_warnings = tuple(dict.fromkeys((*packing_warnings, *reticular.warnings)))
        report = OrganicAnalysisReport(
            profile,
            periodic_bonds,
            layers,
            components=components,
            contacts=contacts,
            packing=packing,
            reticular=reticular,
            complete=(
                layers.complete
                and components.complete
                and contacts.complete
                and packing.complete
                and reticular.complete
            ),
            warnings=reticular_warnings,
        )
        yield OrganicAnalysisBundle(OrganicAnalysisStage.RETICULAR, report)


__all__ = [
    "OrganicAnalysisBundle",
    "OrganicAnalysisReport",
    "OrganicAnalysisStage",
    "iter_analyze_organic",
]
