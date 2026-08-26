from __future__ import annotations

from pathlib import Path

import pytest

from crystal_viewer.analysis.descriptors import build_descriptors
from crystal_viewer.core.document import load_document


@pytest.mark.parametrize(
    ("relative_path", "expected_classification", "expected_rank"),
    (
        ("tests/data/structures/lithium_triborate.cif", "framework", 3),
        ("examples/gehlenite_Ca2Al2SiO7.cif", "layer", 2),
    ),
)
def test_real_inorganic_topology_is_consistent_across_consumers(
    relative_path: str,
    expected_classification: str,
    expected_rank: int,
) -> None:
    document = load_document(Path(relative_path))
    report = document.inorganic_topology

    assert report is not None and report.interpretable
    assert report.families
    assert all(family.component_ids for family in report.families)
    assert {family.classification for family in report.families} == {
        expected_classification
    }
    assert {family.periodic_rank for family in report.families} == {expected_rank}
    assert all(
        identifier in report.structural_polyhedron_ids
        for component in report.components
        for identifier in component.polyhedron_ids
    )

    descriptor = build_descriptors(document)["topology.component_classes"]
    assert descriptor.value["family_ids"] == tuple(
        family.id for family in report.families
    )


def test_lithium_triborate_reports_li_as_context_without_changing_borate_framework() -> None:
    document = load_document(Path("tests/data/structures/lithium_triborate.cif"))
    report = document.inorganic_topology

    assert report is not None
    assert {family.classification for family in report.families} == {"framework"}
    assert report.cation_families
    assert {
        unit
        for family in report.cation_families
        for unit in family.building_units
    } == {"LiO4"}
    assert report.cation_polyhedron_ids.isdisjoint(report.structural_polyhedron_ids)
    assert any(edge.mode == "geometric" for edge in report.cation_edges)
