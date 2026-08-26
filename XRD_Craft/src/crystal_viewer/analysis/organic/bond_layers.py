from __future__ import annotations

from pymatgen.core import Element

from crystal_viewer.analysis.organic.model import (
    BondLayerReport,
    ChemicalEdge,
    ChemicalEdgeKind,
    Translation,
)
from crystal_viewer.analysis.periodic_bonds import PeriodicBond, PeriodicBondResult
from crystal_viewer.core.chemistry import site_elements
from crystal_viewer.core.model import AtomSite, CrystalStructure


def canonical_edge_identity(
    first: int,
    second: int,
    image: Translation,
) -> tuple[int, int, Translation]:
    if first < second:
        return first, second, image
    if first > second:
        return second, first, tuple(-value for value in image)
    reverse = tuple(-value for value in image)
    return first, second, min(image, reverse)


def _is_metal(site: AtomSite) -> bool:
    for symbol in site_elements(site):
        try:
            if Element(symbol).is_metal:
                return True
        except ValueError:
            continue
    return False


def _mutually_exclusive(first: AtomSite, second: AtomSite) -> bool:
    if not first.assembly or first.assembly != second.assembly:
        return False
    if not first.disorder_group or not second.disorder_group:
        return False
    return first.disorder_group != second.disorder_group


def _source_key(site: AtomSite, index: int) -> str:
    return site.source_site_key or f"site:{index}"


def _logical_identity(
    structure: CrystalStructure,
    bond: PeriodicBond,
) -> tuple[str, str, Translation]:
    first_key = _source_key(structure.sites[bond.first], bond.first)
    second_key = _source_key(structure.sites[bond.second], bond.second)
    if first_key < second_key:
        return first_key, second_key, bond.image
    if first_key > second_key:
        return second_key, first_key, tuple(-value for value in bond.image)
    reverse = tuple(-value for value in bond.image)
    return first_key, second_key, min(bond.image, reverse)


def _edge(
    bond: PeriodicBond,
    kind: ChemicalEdgeKind,
    warnings: tuple[str, ...] = (),
) -> ChemicalEdge:
    first, second, image = canonical_edge_identity(bond.first, bond.second, bond.image)
    edge_id = f"{kind.value}:{first}:{second}:{image[0]},{image[1]},{image[2]}"
    return ChemicalEdge(
        edge_id,
        first,
        second,
        image,
        float(bond.distance),
        kind,
        min(1.0, max(0.0, float(bond.confidence))),
        bond.method,
        tuple(bond.warnings) + tuple(warnings),
    )


def _bond_priority(structure: CrystalStructure, bond: PeriodicBond) -> tuple[float, float, int, int]:
    occupancy = min(
        structure.sites[bond.first].effective_occupancy,
        structure.sites[bond.second].effective_occupancy,
    )
    return (float(bond.confidence), occupancy, -bond.first, -bond.second)


def build_bond_layers(
    structure: CrystalStructure,
    periodic_bonds: PeriodicBondResult,
) -> BondLayerReport:
    selected: dict[tuple[str, str, Translation], PeriodicBond] = {}
    duplicate_ids: set[int] = set()
    for bond in periodic_bonds.bonds:
        identity = _logical_identity(structure, bond)
        previous = selected.get(identity)
        if previous is None or _bond_priority(structure, bond) > _bond_priority(structure, previous):
            if previous is not None:
                duplicate_ids.add(id(previous))
            selected[identity] = bond
        else:
            duplicate_ids.add(id(bond))

    covalent: list[ChemicalEdge] = []
    coordination: list[ChemicalEdge] = []
    rejected: list[ChemicalEdge] = []
    for bond in periodic_bonds.bonds:
        first_site = structure.sites[bond.first]
        second_site = structure.sites[bond.second]
        if _mutually_exclusive(first_site, second_site):
            rejected.append(_edge(bond, ChemicalEdgeKind.REJECTED, ("Mutually exclusive disorder alternatives.",)))
            continue
        if id(bond) in duplicate_ids:
            rejected.append(_edge(bond, ChemicalEdgeKind.REJECTED, ("Duplicate split-site alternative edge.",)))
            continue
        first_metal = _is_metal(first_site)
        second_metal = _is_metal(second_site)
        if first_metal ^ second_metal:
            coordination.append(_edge(bond, ChemicalEdgeKind.COORDINATION))
        elif not first_metal and not second_metal:
            covalent.append(_edge(bond, ChemicalEdgeKind.COVALENT))
        else:
            rejected.append(_edge(bond, ChemicalEdgeKind.REJECTED, ("Metal-metal edge is not a molecular bond.",)))

    ordering = lambda edge: (edge.first, edge.second, edge.image, edge.id)
    return BondLayerReport(
        tuple(sorted(covalent, key=ordering)),
        tuple(sorted(coordination, key=ordering)),
        tuple(sorted(rejected, key=ordering)),
        periodic_bonds.complete,
        tuple(periodic_bonds.warnings),
    )


__all__ = ["build_bond_layers", "canonical_edge_identity"]
