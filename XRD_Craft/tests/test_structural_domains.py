from __future__ import annotations

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    PeriodicSiteRef,
    PolyhedronConnection,
)
from crystal_viewer.analysis.structural_domains import derive_structural_domains
from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence


def _polyhedron(identifier: int) -> CoordinationPolyhedron:
    return CoordinationPolyhedron(
        id=f"P{identifier}",
        center_index=identifier - 1,
        center_element="X",
        ligand_element="O",
        ligands=(PeriodicSiteRef(100 + identifier),),
        bond_lengths=(1.5,),
        vertex_coordinates=((float(identifier), 0.0, 0.0),),
        distortion=0.0,
        angle_dispersion=0.0,
    )


def _connection(
    first: int,
    second: int,
    translation: tuple[int, int, int] = (0, 0, 0),
) -> PolyhedronConnection:
    return PolyhedronConnection(
        first=f"P{first}",
        second=f"P{second}",
        shared_ligands=(PeriodicSiteRef(200 + first + second),),
        kind="corner",
        flexible=True,
        translation=translation,
    )


def _roles(count: int, role: str = "structural") -> tuple[PolyhedronRoleEvidence, ...]:
    return tuple(
        PolyhedronRoleEvidence(index, role, 0.8, 0.9, "test")
        for index in range(count)
    )


def test_finite_cycle_is_one_ring_domain() -> None:
    polyhedra = [_polyhedron(index) for index in range(1, 4)]
    connections = [_connection(1, 2), _connection(2, 3), _connection(3, 1)]

    domains = derive_structural_domains(polyhedra, connections, _roles(3))

    assert len(domains) == 1
    assert domains[0].polyhedron_ids == ("P1", "P2", "P3")
    assert domains[0].periodic_rank == 0
    assert domains[0].classification == "ring"


def test_translation_rank_classifies_chain_ribbon_layer_and_framework() -> None:
    polyhedron = [_polyhedron(1)]
    cases = (
        ([_connection(1, 1, (1, 0, 0))], 1, "chain"),
        (
            [_connection(1, 1, (1, 0, 0)), _connection(1, 1, (0, 0, 0))],
            1,
            "ribbon",
        ),
        (
            [_connection(1, 1, (1, 0, 0)), _connection(1, 1, (0, 1, 0))],
            2,
            "layer",
        ),
        (
            [
                _connection(1, 1, (1, 0, 0)),
                _connection(1, 1, (0, 1, 0)),
                _connection(1, 1, (0, 0, 1)),
            ],
            3,
            "framework",
        ),
    )

    for connections, expected_rank, expected_name in cases:
        domains = derive_structural_domains(polyhedron, connections, _roles(1))
        assert [(item.periodic_rank, item.classification) for item in domains] == [
            (expected_rank, expected_name)
        ]


def test_interstitial_and_ambiguous_polyhedra_do_not_glue_structural_domains() -> None:
    polyhedra = [_polyhedron(index) for index in range(1, 5)]
    connections = [
        _connection(1, 2),
        _connection(2, 3),
        _connection(3, 4),
    ]
    roles = (
        PolyhedronRoleEvidence(0, "structural", 0.8, 0.9, "test"),
        PolyhedronRoleEvidence(1, "interstitial", 0.1, 0.9, "test"),
        PolyhedronRoleEvidence(2, "ambiguous", 0.35, 0.5, "test"),
        PolyhedronRoleEvidence(3, "structural", 0.8, 0.9, "test"),
    )

    domains = derive_structural_domains(polyhedra, connections, roles)

    assert [item.polyhedron_ids for item in domains] == [("P1",), ("P4",)]
    assert all(item.classification == "island" for item in domains)


def test_domain_result_is_independent_of_input_order() -> None:
    polyhedra = [_polyhedron(index) for index in range(1, 4)]
    connections = [_connection(1, 2), _connection(2, 3), _connection(3, 1)]

    first = derive_structural_domains(polyhedra, connections, _roles(3))
    second = derive_structural_domains(
        list(reversed(polyhedra)),
        list(reversed(connections)),
        tuple(reversed(_roles(3))),
    )

    assert first == second
