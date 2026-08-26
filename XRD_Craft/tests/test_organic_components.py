from __future__ import annotations

from crystal_viewer.analysis.organic.components import build_components
from crystal_viewer.analysis.organic.model import (
    BondLayerReport,
    ChemicalEdge,
    ChemicalEdgeKind,
)
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _structure(elements: list[str], coordinates: list[tuple[float, float, float]]) -> CrystalStructure:
    sites = [
        AtomSite(f"{element}{index + 1}", element, coordinate, source_site_key=f"{element}{index + 1}")
        for index, (element, coordinate) in enumerate(zip(elements, coordinates, strict=True))
    ]
    return CrystalStructure("case", UnitCell(10, 10, 10), sites, sites)


def _report(edges: list[tuple[int, int, tuple[int, int, int], float]]) -> BondLayerReport:
    covalent = tuple(
        ChemicalEdge(
            f"e{index}", first, second, image, 1.4,
            ChemicalEdgeKind.COVALENT, confidence, "test",
        )
        for index, (first, second, image, confidence) in enumerate(edges)
    )
    return BondLayerReport(covalent, (), (), True)


def test_boundary_molecule_and_periodic_chain_have_different_rank() -> None:
    structure = _structure(["C", "C"], [(0.95, 0.5, 0.5), (0.05, 0.5, 0.5)])
    molecule = build_components(structure, _report([(0, 1, (1, 0, 0), 1.0)]))
    chain = build_components(
        structure,
        _report([(0, 1, (0, 0, 0), 1.0), (0, 1, (1, 0, 0), 1.0)]),
    )

    assert len(molecule.components) == 1
    assert molecule.components[0].periodic_rank == 0
    assert chain.components[0].periodic_rank == 1


def test_fused_ring_basis_is_minimal_and_order_independent() -> None:
    structure = _structure(
        ["C"] * 6,
        [(0.2, 0.2, 0.5), (0.4, 0.2, 0.5), (0.5, 0.4, 0.5),
         (0.4, 0.6, 0.5), (0.2, 0.6, 0.5), (0.1, 0.4, 0.5)],
    )
    edges = [(0, 1, (0, 0, 0), 1.0), (1, 2, (0, 0, 0), 1.0),
             (2, 3, (0, 0, 0), 1.0), (3, 0, (0, 0, 0), 1.0),
             (3, 4, (0, 0, 0), 1.0), (4, 5, (0, 0, 0), 1.0),
             (5, 0, (0, 0, 0), 1.0)]

    forward = build_components(structure, _report(edges))
    reverse = build_components(structure, _report(list(reversed(edges))))

    assert forward.rings == reverse.rings
    assert len(forward.rings) == 2
    assert all(ring.pi_capable for ring in forward.rings)


def test_ring_confidence_is_not_aromaticity() -> None:
    structure = _structure(
        ["O", "O", "O"],
        [(0.2, 0.2, 0.5), (0.4, 0.2, 0.5), (0.3, 0.4, 0.5)],
    )
    report = build_components(
        structure,
        _report([(0, 1, (0, 0, 0), 0.7), (1, 2, (0, 0, 0), 1.0), (2, 0, (0, 0, 0), 1.0)]),
    )

    assert report.rings[0].confidence == 0.7
    assert not report.rings[0].pi_capable


def test_symmetry_copies_share_one_component_orbit_key() -> None:
    sites = [
        AtomSite("C1", "C", (0.1, 0.1, 0.1), source_site_key="C1"),
        AtomSite("O1", "O", (0.2, 0.1, 0.1), source_site_key="O1"),
        AtomSite("C1·2", "C", (0.6, 0.6, 0.6), source_site_key="C1"),
        AtomSite("O1·2", "O", (0.7, 0.6, 0.6), source_site_key="O1"),
    ]
    structure = CrystalStructure("copies", UnitCell(10, 10, 10), sites[:2], sites)
    report = build_components(
        structure,
        _report([(0, 1, (0, 0, 0), 1.0), (2, 3, (0, 0, 0), 1.0)]),
    )

    assert len(report.components) == 2
    assert len({component.orbit_key for component in report.components}) == 1
