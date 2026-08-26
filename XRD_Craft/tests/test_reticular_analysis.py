from __future__ import annotations

from crystal_viewer.analysis.organic.components import ComponentReport, MolecularComponent
from crystal_viewer.analysis.organic.model import BondLayerReport, ChemicalEdge, ChemicalEdgeKind
from crystal_viewer.analysis.organic.reticular import build_reticular_network
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _edge(identity, first, second, image=(0, 0, 0), confidence=1.0):
    return ChemicalEdge(
        identity, first, second, image, 2.0, ChemicalEdgeKind.COORDINATION,
        confidence, "test",
    )


def test_two_connected_organic_components_contract_to_periodic_underlying_edges() -> None:
    sites = [
        AtomSite("Zn1", "Zn", (0.1, 0.5, 0.5)),
        AtomSite("Zn2", "Zn", (0.9, 0.5, 0.5)),
        AtomSite("C1", "C", (0.3, 0.5, 0.5)),
        AtomSite("C2", "C", (0.7, 0.5, 0.5)),
        AtomSite("C3", "C", (0.3, 0.6, 0.5)),
        AtomSite("C4", "C", (0.7, 0.6, 0.5)),
    ]
    structure = CrystalStructure("reticular", UnitCell(10, 10, 10), sites, sites)
    components = ComponentReport(
        (
            MolecularComponent("M1", (2, 3), (), 0, (), "C2", 1.0, "m1"),
            MolecularComponent("M2", (4, 5), (), 0, (), "C2", 1.0, "m2"),
        ), (), (),
    )
    bonds = BondLayerReport(
        (),
        (
            _edge("e1", 0, 2), _edge("e2", 1, 3),
            _edge("e3", 0, 4), _edge("e4", 1, 5, (1, 0, 0)),
        ),
        (), True,
    )

    report = build_reticular_network(structure, bonds, components)

    assert len(report.coordination_nodes) == 2
    assert len(report.linkers) == 2
    assert len(report.underlying_edges) == 2
    assert report.periodic_rank == 1
    assert report.recommended_representation == "single-metal nodes"
    assert report.graph_digest
    assert report.representation_notes
    assert not hasattr(report, "net_symbol")


def test_terminal_component_is_context_not_a_network_object() -> None:
    sites = [
        AtomSite("Zn1", "Zn", (0.1, 0.5, 0.5)),
        AtomSite("C1", "C", (0.3, 0.5, 0.5)),
        AtomSite("O1", "O", (0.7, 0.5, 0.5)),
    ]
    structure = CrystalStructure("complex", UnitCell(10, 10, 10), sites, sites)
    components = ComponentReport(
        (
            MolecularComponent("M1", (1,), (), 0, (), "C", 1.0, "m1"),
            MolecularComponent("M2", (2,), (), 0, (), "O", 1.0, "m2"),
        ), (), (),
    )
    bonds = BondLayerReport((), (_edge("e1", 0, 1),), (), True)

    report = build_reticular_network(structure, bonds, components)

    assert report.guests
    assert all(guest.id not in report.network_object_ids for guest in report.guests)
    assert report.periodic_rank == 0


def test_carbon_free_bridge_groups_metal_centres_into_one_sbu_candidate() -> None:
    sites = [
        AtomSite("Zn1", "Zn", (0.2, 0.5, 0.5)),
        AtomSite("O1", "O", (0.5, 0.5, 0.5)),
        AtomSite("Zn2", "Zn", (0.8, 0.5, 0.5)),
    ]
    structure = CrystalStructure("bridged cluster", UnitCell(10, 10, 10), sites, sites)
    components = ComponentReport(
        (MolecularComponent("M1", (1,), (), 0, (), "O", 1.0, "m1"),), (), (),
    )
    bonds = BondLayerReport(
        (), (_edge("e1", 0, 1), _edge("e2", 2, 1)), (), True,
    )

    report = build_reticular_network(structure, bonds, components)

    assert len(report.coordination_nodes) == 1
    assert report.coordination_nodes[0].atom_indices == (0, 2)
    assert len(report.sbus) == 1
    assert report.sbus[0].representation == "metal cluster"
