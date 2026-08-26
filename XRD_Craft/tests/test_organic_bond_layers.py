from __future__ import annotations

from crystal_viewer.analysis.organic.bond_layers import build_bond_layers
from crystal_viewer.analysis.organic.model import ChemicalEdgeKind
from crystal_viewer.analysis.periodic_bonds import PeriodicBond, PeriodicBondResult
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _bond(
    first: int,
    second: int,
    *,
    image: tuple[int, int, int] = (0, 0, 0),
    confidence: float = 0.9,
) -> PeriodicBond:
    return PeriodicBond(first, second, image, 1.5, 1.0, "test-neighbours", confidence)


def _case(order: str = "forward") -> tuple[CrystalStructure, PeriodicBondResult]:
    sites = [
        AtomSite("C1", "C", (0.10, 0.5, 0.5)),
        AtomSite("C2", "C", (0.25, 0.5, 0.5)),
        AtomSite("O1", "O", (0.40, 0.5, 0.5)),
        AtomSite("Zn1", "Zn", (0.55, 0.5, 0.5)),
        AtomSite(
            "O2A",
            "O",
            (0.70, 0.5, 0.5),
            occupancy=0.6,
            disorder_group="1",
            assembly="A",
            source_site_key="O2",
        ),
        AtomSite(
            "O2B",
            "O",
            (0.705, 0.5, 0.5),
            occupancy=0.4,
            disorder_group="2",
            assembly="A",
            source_site_key="O2",
        ),
    ]
    bonds = [
        _bond(0, 1),
        _bond(1, 2),
        _bond(2, 3),
        _bond(4, 5),
        _bond(3, 4, confidence=0.8),
        _bond(3, 5, confidence=0.7),
    ]
    if order == "reverse":
        bonds.reverse()
    structure = CrystalStructure("organic layers", UnitCell(10, 10, 10), sites, sites)
    return structure, PeriodicBondResult(tuple(bonds), True)


def test_bond_layers_separate_covalent_coordination_and_rejected_edges() -> None:
    report = build_bond_layers(*_case())

    assert {(edge.first, edge.second) for edge in report.covalent} == {(0, 1), (1, 2)}
    assert {(edge.first, edge.second) for edge in report.coordination} == {(2, 3), (3, 4)}
    assert {(edge.first, edge.second) for edge in report.rejected} == {(4, 5), (3, 5)}
    assert all(edge.kind is ChemicalEdgeKind.COVALENT for edge in report.covalent)
    assert all(edge.kind is ChemicalEdgeKind.COORDINATION for edge in report.coordination)
    assert all(edge.kind is ChemicalEdgeKind.REJECTED for edge in report.rejected)


def test_split_alternatives_are_not_bonded_or_duplicated() -> None:
    report = build_bond_layers(*_case())

    assert all({edge.first, edge.second} != {4, 5} for edge in report.covalent + report.coordination)
    assert sum(edge.first == 3 or edge.second == 3 for edge in report.coordination) == 2
    assert any("alternative" in " ".join(edge.warnings).lower() for edge in report.rejected)


def test_layer_order_and_edge_identity_are_input_order_independent() -> None:
    forward = build_bond_layers(*_case("forward"))
    reverse = build_bond_layers(*_case("reverse"))

    assert forward == reverse
    for edge in forward.covalent + forward.coordination + forward.rejected:
        assert edge.id
        assert edge.method == "test-neighbours"
        assert 0.0 <= edge.confidence <= 1.0
        assert len(edge.image) == 3
