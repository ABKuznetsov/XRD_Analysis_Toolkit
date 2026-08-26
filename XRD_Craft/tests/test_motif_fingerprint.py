from __future__ import annotations

from types import SimpleNamespace

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyReport,
    PeriodicSiteRef,
    PolyhedronConnection,
)
from crystal_viewer.analysis.structural_domains import StructuralDomain
from crystal_viewer.core.model import AtomSite, SiteComponent
from crystal_viewer.knowledge.fingerprint import (
    build_motif_fingerprint,
    fingerprint_digest,
)


def _document(
    identifiers=("P1", "P2", "P3"),
    *,
    edge_translation=(0, 0, 0),
    mixed_center=False,
):
    center_components = (
        (SiteComponent("Na", 0.5), SiteComponent("Li", 0.5))
        if mixed_center
        else (SiteComponent("B", 1.0),)
    )
    sites = [
        AtomSite(
            f"C{index}",
            "Na/Li" if mixed_center else "B",
            (0.1 * index, 0.0, 0.0),
            components=center_components,
        )
        for index in range(3)
    ]
    sites.extend(
        AtomSite(f"O{index}", "O", (0.0, 0.1 * index, 0.0))
        for index in range(3)
    )
    polyhedra = [
        CoordinationPolyhedron(
            id=identifier,
            center_index=index,
            center_element=sites[index].element,
            ligand_element="O",
            ligands=(
                PeriodicSiteRef(3 + index),
                PeriodicSiteRef(3 + ((index + 1) % 3)),
                PeriodicSiteRef(3 + ((index + 2) % 3)),
            ),
            bond_lengths=(1.45, 1.50, 1.55),
            vertex_coordinates=((0.0, 0.0, 0.0),) * 3,
            distortion=0.01,
            angle_dispersion=0.02,
        )
        for index, identifier in enumerate(identifiers)
    ]
    connections = [
        PolyhedronConnection(
            identifiers[0],
            identifiers[1],
            (PeriodicSiteRef(3),),
            "corner",
            True,
            edge_translation,
        ),
        PolyhedronConnection(
            identifiers[1], identifiers[2], (PeriodicSiteRef(4),), "corner", True
        ),
        PolyhedronConnection(
            identifiers[2], identifiers[0], (PeriodicSiteRef(5),), "corner", True
        ),
    ]
    domain = StructuralDomain(
        "renamed-domain" if identifiers[0] != "P1" else "D1",
        tuple(identifiers),
        tuple(range(6)),
        0,
        "ring",
        0.9,
    )
    return SimpleNamespace(
        structure=SimpleNamespace(sites=sites),
        hierarchy=HierarchyReport(
            polyhedra=polyhedra,
            polyhedron_connections=connections,
            structural_domains=[domain],
        ),
        structural_analysis=SimpleNamespace(
            rings=(SimpleNamespace(member_ids=tuple(identifiers), size=3),)
        ),
    )


def test_fingerprint_is_invariant_to_domain_ids_node_ids_and_input_order():
    first = build_motif_fingerprint(_document(), "D1")
    renamed = _document(("Q9", "Q2", "Q5"))
    renamed.hierarchy.polyhedra.reverse()
    renamed.hierarchy.polyhedron_connections.reverse()
    second = build_motif_fingerprint(renamed, "renamed-domain")

    assert first == second
    assert fingerprint_digest(first) == fingerprint_digest(second)


def test_periodic_edge_translation_changes_the_fingerprint():
    finite = build_motif_fingerprint(_document(), "D1")
    translated = build_motif_fingerprint(
        _document(edge_translation=(1, 0, 0)), "D1"
    )

    assert fingerprint_digest(finite) != fingerprint_digest(translated)


def test_translation_orientation_is_canonical():
    positive = build_motif_fingerprint(
        _document(edge_translation=(1, -2, 0)), "D1"
    )
    negative = build_motif_fingerprint(
        _document(edge_translation=(-1, 2, 0)), "D1"
    )

    assert positive == negative


def test_mixed_site_occupancies_are_preserved_in_node_chemistry():
    pure = build_motif_fingerprint(_document(), "D1")
    mixed = build_motif_fingerprint(_document(mixed_center=True), "D1")

    assert pure != mixed
    assert any(("Li", 500000) in node[2] for node in mixed.nodes)
    assert any(("Na", 500000) in node[2] for node in mixed.nodes)
