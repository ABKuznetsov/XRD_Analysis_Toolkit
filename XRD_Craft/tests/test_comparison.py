from __future__ import annotations

from crystal_viewer.analysis.comparison import ComparisonState, compare_documents
from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.motif_comparison import (
    AtomSubstitution,
    MotifComparisonReport,
    MotifMatch,
    UnmatchedNode,
)
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import CrystalStructure, UnitCell


def _document(name: str, a: float) -> StructureDocument:
    structure = CrystalStructure(
        name=name,
        cell=UnitCell(a, 10.0, 10.0),
        asymmetric_sites=[],
        sites=[],
    )
    return StructureDocument.from_structure(structure, HierarchyReport())


def test_comparison_uses_descriptor_specific_tolerance() -> None:
    report = compare_documents((_document("first", 10.0), _document("second", 10.05)))
    row = report.row("cell.a")

    assert row.cells[0].state is ComparisonState.SIMILAR
    assert row.cells[1].state is ComparisonState.MODERATE
    assert row.has_difference


def test_cell_angle_ratio_and_space_group_use_explicit_comparison_policy() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)
    first.structure.cell = UnitCell(10.0, 10.0, 10.0, alpha=90.0)
    second.structure.cell = UnitCell(10.0, 10.0, 10.15, alpha=90.3)
    first.structure.space_group = "P 1"
    second.structure.space_group = "P -1"

    report = compare_documents((first, second))

    assert report.row("cell.alpha").cells[1].state is ComparisonState.MODERATE
    assert report.row("cell.c_over_a").cells[1].state is ComparisonState.MODERATE
    assert report.row("cell.space_group").cells[1].state is ComparisonState.DIFFERENT


def test_missing_distribution_is_gray_not_zero() -> None:
    report = compare_documents((_document("first", 10.0), _document("second", 10.0)))
    row = report.row("mo_o.d6_minus_d5")

    assert all(cell.state is ComparisonState.UNAVAILABLE for cell in row.cells)
    assert all(cell.display == "—" for cell in row.cells)


def test_mo_geometry_rows_carry_3d_focus_command() -> None:
    row = compare_documents((_document("first", 10.0),)).row("mo_o.off_centering")

    assert row.focus is not None
    assert row.focus.selector == "polyhedron-type"
    assert row.focus.payload == {"center": "Mo", "coordination": 6}


def _motif_report(first: StructureDocument, second: StructureDocument) -> MotifComparisonReport:
    match = MotifMatch(
        id="motif-1",
        classification="chain",
        periodic_rank=1,
        node_pairs=(
            ("P1", "P7"),
            ("P2", "P8"),
            ("I3", "I8"),
            ("I4", "I9"),
        ),
        edge_pairs=(("edge-a", "edge-b"),),
        edge_kinds=("corner",),
        topology_score=1.0,
        geometry_score=0.9,
        chemistry_score=0.5,
        total_score=0.8,
    )
    substitution = AtomSubstitution(
        match_id="motif-1",
        first_node_id="I3",
        second_node_id="I8",
        first_site_index=3,
        second_site_index=8,
        first_element="Mo",
        second_element="W",
        first_occupancies=(("Mo", 1.0),),
        second_occupancies=(("W", 1.0),),
    )
    unmatched = UnmatchedNode(
        side="second",
        node_id="P9",
        kind="polyhedron",
        element="W",
        site_index=9,
        unit_ids=(),
    )
    return MotifComparisonReport(
        first_document_id=first.id,
        second_document_id=second.id,
        matches=(match,),
        substitutions=(substitution,),
        unmatched_first=(),
        unmatched_second=(unmatched,),
        approximate=False,
        states_explored=12,
    )


def test_descriptor_rows_use_the_six_stable_section_names() -> None:
    report = compare_documents((_document("first", 10.0), _document("second", 10.0)))

    assert {row.section for row in report.rows} <= {
        "Unit Cell",
        "Polyhedra",
        "Structural Motifs",
        "Connections and Interstitial Atoms",
        "Topology",
        "Warnings and Data Quality",
    }
    assert report.row("cell.a").section == "Unit Cell"
    assert report.row("coordination.polyhedron_counts").section == "Polyhedra"
    assert report.row("topology.component_classes").section == "Topology"
    assert report.row("occupancy.out_of_range").section == "Warnings and Data Quality"


def test_motif_report_adds_summary_rows_with_exact_pair_focus() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)

    report = compare_documents((first, second), motif_report=_motif_report(first, second))

    motif_row = report.row("motif.match.motif-1")
    assert motif_row.section == "Structural Motifs"
    assert motif_row.focus is not None
    assert motif_row.focus.payload["first_polyhedron_ids"] == ("P1", "P2")
    assert motif_row.focus.payload["second_polyhedron_ids"] == ("P7", "P8")
    connection_rows = [
        row
        for row in report.rows
        if row.section == "Connections and Interstitial Atoms"
    ]
    assert {row.descriptor_id for row in connection_rows} == {
        "connections.substitutions",
        "connections.unmatched",
    }


def test_motif_focus_includes_same_chemistry_matched_interstitial_indices() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)

    report = compare_documents((first, second), motif_report=_motif_report(first, second))
    focus = report.row("motif.match.motif-1").focus

    assert focus is not None
    assert focus.payload["first_atom_indices"] == (3, 4)
    assert focus.payload["second_atom_indices"] == (8, 9)


def test_interstitial_substitution_ids_do_not_leak_into_polyhedron_focus() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)

    report = compare_documents((first, second), motif_report=_motif_report(first, second))
    focus = report.row("connections.substitutions").focus

    assert focus is not None
    assert focus.payload["first_polyhedron_ids"] == ()
    assert focus.payload["second_polyhedron_ids"] == ()
    assert focus.payload["first_atom_indices"] == (3,)
    assert focus.payload["second_atom_indices"] == (8,)


def test_unmatched_polyhedron_center_index_is_not_routed_as_an_atom() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)

    report = compare_documents((first, second), motif_report=_motif_report(first, second))
    focus = report.row("connections.unmatched").focus

    assert focus is not None
    assert focus.payload["second_polyhedron_ids"] == ("P9",)
    assert focus.payload["second_atom_indices"] == ()


def test_approximation_reasons_are_on_every_connection_cell() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)
    motif_report = _motif_report(first, second)
    approximate_report = MotifComparisonReport(
        first_document_id=motif_report.first_document_id,
        second_document_id=motif_report.second_document_id,
        matches=motif_report.matches,
        substitutions=motif_report.substitutions,
        unmatched_first=motif_report.unmatched_first,
        unmatched_second=motif_report.unmatched_second,
        approximate=True,
        states_explored=motif_report.states_explored,
        limit_reasons=("max_nodes", "max_seconds"),
    )

    report = compare_documents((first, second), motif_report=approximate_report)

    for descriptor_id in ("connections.substitutions", "connections.unmatched"):
        assert {
            cell.warning for cell in report.row(descriptor_id).cells
        } == {"Approximate motif result: max_nodes, max_seconds"}


def test_incomplete_graph_rows_are_unavailable_without_absence_or_count_claims() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)
    motif_report = MotifComparisonReport(
        first_document_id=first.id,
        second_document_id=second.id,
        matches=(),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=True,
        states_explored=0,
        limit_reasons=("max_nodes",),
        graph_complete=False,
    )

    report = compare_documents((first, second), motif_report=motif_report)

    for descriptor_id in (
        "motif.common",
        "connections.substitutions",
        "connections.unmatched",
    ):
        row = report.row(descriptor_id)
        assert all(cell.display == "Not evaluated" for cell in row.cells)
        assert all(cell.state is ComparisonState.UNAVAILABLE for cell in row.cells)
        assert all(cell.raw is None for cell in row.cells)
        assert all("graph construction incomplete" in cell.warning for cell in row.cells)
        assert all("max_nodes" in cell.warning for cell in row.cells)
    assert any("not evaluated" in warning.lower() for warning in report.warnings)


def test_complete_empty_match_keeps_true_absence_and_zero_count_semantics() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)
    motif_report = MotifComparisonReport(
        first_document_id=first.id,
        second_document_id=second.id,
        matches=(),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=False,
        states_explored=1,
    )

    report = compare_documents((first, second), motif_report=motif_report)

    motif = report.row("motif.common")
    substitutions = report.row("connections.substitutions")
    unmatched = report.row("connections.unmatched")
    assert [cell.display for cell in motif.cells] == ["none", "none"]
    assert all(cell.state is ComparisonState.DIFFERENT for cell in motif.cells)
    assert [cell.display for cell in substitutions.cells] == ["none", "none"]
    assert all(cell.state is ComparisonState.SIMILAR for cell in substitutions.cells)
    assert [cell.display for cell in unmatched.cells] == ["0", "0"]
    assert all(cell.state is ComparisonState.SIMILAR for cell in unmatched.cells)


def test_search_stopped_before_a_result_is_not_evaluated_even_with_complete_graphs() -> None:
    first = _document("first", 10.0)
    second = _document("second", 10.0)
    motif_report = MotifComparisonReport(
        first_document_id=first.id,
        second_document_id=second.id,
        matches=(),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=True,
        states_explored=0,
        limit_reasons=("max_states",),
        graph_complete=True,
        result_interpretable=False,
    )

    report = compare_documents((first, second), motif_report=motif_report)

    for descriptor_id in (
        "motif.common",
        "connections.substitutions",
        "connections.unmatched",
    ):
        row = report.row(descriptor_id)
        assert all(cell.display == "Not evaluated" for cell in row.cells)
        assert all(cell.state is ComparisonState.UNAVAILABLE for cell in row.cells)
        assert all(cell.raw is None for cell in row.cells)
        assert all(
            "search stopped before an interpretable result" in cell.warning
            for cell in row.cells
        )
        assert all("max_states" in cell.warning for cell in row.cells)
