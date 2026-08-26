from __future__ import annotations

from crystal_viewer.analysis.organic.components import (
    ComponentReport,
    MolecularComponent,
    MolecularRing,
    PiSystem,
    build_components,
)
from crystal_viewer.analysis.organic.contacts import ContactKind, build_contacts
from crystal_viewer.analysis.organic.model import BondLayerReport, ChemicalEdge, ChemicalEdgeKind
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _edge(identity: str, first: int, second: int) -> ChemicalEdge:
    return ChemicalEdge(identity, first, second, (0, 0, 0), 1.0, ChemicalEdgeKind.COVALENT, 1.0, "test")


def _case(*, hydrogen: bool = True, intramolecular: bool = False):
    elements = ["O", "H", "O"] if hydrogen else ["O", "O"]
    coordinates = [(0.1, 0.5, 0.5), (0.2, 0.5, 0.5), (0.37, 0.5, 0.5)] if hydrogen else [(0.1, 0.5, 0.5), (0.37, 0.5, 0.5)]
    sites = [AtomSite(f"{element}{i}", element, xyz) for i, (element, xyz) in enumerate(zip(elements, coordinates, strict=True))]
    structure = CrystalStructure("contact", UnitCell(10, 10, 10), sites, sites)
    covalent = [_edge("oh", 0, 1)] if hydrogen else []
    if intramolecular:
        covalent.append(_edge("oo", 0, 2))
    bonds = BondLayerReport(tuple(covalent), (), (), True)
    return structure, bonds, build_components(structure, bonds)


def test_hydrogen_bond_requires_explicit_hydrogen_and_good_geometry() -> None:
    valid = build_contacts(*_case())
    missing = build_contacts(*_case(hydrogen=False))

    assert len(valid.hydrogen_bonds) == 1
    assert valid.hydrogen_bonds_evaluated
    assert not missing.hydrogen_bonds_evaluated
    assert any("hydrogen" in warning.lower() for warning in missing.warnings)


def test_contacts_are_intercomponent_and_do_not_mutate_bonds() -> None:
    structure, bonds, components = _case(intramolecular=True)
    before = bonds.covalent
    report = build_contacts(structure, bonds, components)

    assert not report.contacts
    assert bonds.covalent == before


def test_generic_short_contact_is_not_promoted_to_named_interaction() -> None:
    sites = [AtomSite("Cl1", "Cl", (0.1, 0.5, 0.5)), AtomSite("Cl2", "Cl", (0.35, 0.5, 0.5))]
    structure = CrystalStructure("short", UnitCell(10, 10, 10), sites, sites)
    components = build_components(structure, (_edge("dummy", 0, 0), _edge("dummy2", 1, 1)))

    report = build_contacts(structure, BondLayerReport((), (), (), True), components)

    assert report.contacts[0].kind is ContactKind.SHORT


def test_parallel_pi_systems_create_a_named_pi_stack_contact() -> None:
    sites = [
        AtomSite(f"C{index + 1}", "C", coordinate)
        for index, coordinate in enumerate(
            (
                (0.40, 0.40, 0.30), (0.60, 0.40, 0.30), (0.50, 0.60, 0.30),
                (0.40, 0.40, 0.65), (0.60, 0.40, 0.65), (0.50, 0.60, 0.65),
            )
        )
    ]
    structure = CrystalStructure("pi stack", UnitCell(10, 10, 10), sites, sites)
    components = ComponentReport(
        (
            MolecularComponent("M1", (0, 1, 2), (), 0, (), "C3", 1.0, "m1"),
            MolecularComponent("M2", (3, 4, 5), (), 0, (), "C3", 1.0, "m2"),
        ),
        (
            MolecularRing("R1", "M1", (0, 1, 2), 0.0, True, 1.0),
            MolecularRing("R2", "M2", (3, 4, 5), 0.0, True, 1.0),
        ),
        (
            PiSystem("PI1", ("R1",), (0.5, 0.4667, 0.30), (0.0, 0.0, 1.0), 1.0),
            PiSystem("PI2", ("R2",), (0.5, 0.4667, 0.65), (0.0, 0.0, 1.0), 1.0),
        ),
    )

    report = build_contacts(structure, BondLayerReport((), (), (), True), components)

    assert any(contact.kind is ContactKind.PI_STACK for contact in report.contacts)


def test_explicit_c_h_pointing_at_pi_centroid_creates_ch_pi_contact() -> None:
    sites = [
        AtomSite("C1", "C", (0.5, 0.5, 0.15)),
        AtomSite("H1", "H", (0.5, 0.5, 0.25)),
        AtomSite("C2", "C", (0.4, 0.4, 0.50)),
        AtomSite("C3", "C", (0.6, 0.4, 0.50)),
        AtomSite("C4", "C", (0.5, 0.6, 0.50)),
    ]
    structure = CrystalStructure("ch pi", UnitCell(10, 10, 10), sites, sites)
    components = ComponentReport(
        (
            MolecularComponent("M1", (0, 1), ("ch",), 0, (), "CH", 1.0, "m1"),
            MolecularComponent("M2", (2, 3, 4), (), 0, (), "C3", 1.0, "m2"),
        ),
        (MolecularRing("R1", "M2", (2, 3, 4), 0.0, True, 1.0),),
        (PiSystem("PI1", ("R1",), (0.5, 0.4667, 0.50), (0.0, 0.0, 1.0), 1.0),),
    )
    bonds = BondLayerReport((_edge("ch", 0, 1),), (), (), True)

    report = build_contacts(structure, bonds, components)

    assert any(contact.kind is ContactKind.CH_PI for contact in report.contacts)
