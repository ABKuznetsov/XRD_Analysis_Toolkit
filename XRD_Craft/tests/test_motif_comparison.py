from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import math

import pytest

import crystal_viewer.analysis.motif_comparison as motif_comparison_module
from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyReport,
    PeriodicSiteRef,
    PolyhedronConnection,
    StructuralUnit,
)
from crystal_viewer.analysis.motif_comparison import (
    MatchLimits,
    compare_motifs,
    score_nodes,
)
from crystal_viewer.analysis.motif_graph import MotifNode
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _octahedron(
    center_element: str,
    *,
    occupancies: tuple[tuple[str, float], ...] | None = None,
) -> MotifNode:
    return MotifNode(
        id=f"{center_element}-octahedron",
        kind="polyhedron",
        coordination_number=6,
        center_element=center_element,
        ligand_elements=("O",) * 6,
        normalized_bond_lengths=(1.0,) * 6,
        distortion=0.0,
        angle_dispersion=0.0,
        unit_ids=(),
        occupancies=(
            ((center_element, 1.0),) if occupancies is None else occupancies
        ),
    )


def _comparison_document(
    element: str,
    *,
    node_count: int = 4,
    coordination_number: int = 4,
    edges: tuple[
        tuple[str, str, str, tuple[int, int, int]], ...
    ] | None = None,
    classification: str = "chain",
    periodic_rank: int = 1,
    extra_interstitial: bool = False,
    name: str | None = None,
) -> StructureDocument:
    ligand_count = max(6, coordination_number)
    centers = [
        AtomSite(f"{element}{index + 1}", element, (0.1 + 0.15 * index, 0.2, 0.2))
        for index in range(node_count)
    ]
    ligands = [
        AtomSite(f"O{index + 1}", "O", (0.40 + 0.01 * index, 0.50, 0.50))
        for index in range(ligand_count)
    ]
    sites = centers + ligands
    if extra_interstitial:
        sites.append(AtomSite("Na1", "Na", (0.45, 0.50, 0.50)))
    polyhedra = [
        CoordinationPolyhedron(
            id=f"P{index + 1}",
            center_index=index,
            center_element=element,
            ligand_element="O",
            ligands=tuple(
                PeriodicSiteRef(node_count + ligand_index)
                for ligand_index in range(coordination_number)
            ),
            bond_lengths=(2.0,) * coordination_number,
            vertex_coordinates=((0.0, 0.0, 0.0),) * coordination_number,
            distortion=0.0,
            angle_dispersion=0.0,
        )
        for index in range(node_count)
    ]
    if edges is None:
        edges = (
            ("P1", "P2", "corner", (0, 0, 0)),
            ("P2", "P3", "corner", (0, 0, 0)),
            ("P3", "P4", "corner", (0, 0, 0)),
            ("P4", "P1", "corner", (1, 0, 0)),
        )
    connections = [
        PolyhedronConnection(
            first,
            second,
            (PeriodicSiteRef(node_count),),
            kind,
            True,
            translation,
        )
        for first, second, kind, translation in edges
    ]
    units = [
        StructuralUnit(
            "SU1",
            tuple(polyhedron.id for polyhedron in polyhedra),
            tuple(range(node_count + coordination_number)),
            classification,
            periodic_rank,
        )
    ]
    structure = CrystalStructure(
        name=name or f"{element}-{node_count}-{classification}",
        cell=UnitCell(20.0, 20.0, 20.0),
        asymmetric_sites=sites,
        sites=sites,
    )
    return StructureDocument.from_structure(
        structure,
        HierarchyReport(
            polyhedra=polyhedra,
            polyhedron_connections=connections,
            structural_units=units,
        ),
    )


def test_same_octahedral_shape_matches_after_center_substitution() -> None:
    score = score_nodes(_octahedron("Mo"), _octahedron("W"))

    assert score is not None
    assert score.topology == 1.0
    assert score.geometry > 0.95
    assert score.chemistry < 1.0
    assert score.total == pytest.approx(
        0.55 * score.topology + 0.30 * score.geometry + 0.15 * score.chemistry
    )


def test_identical_nodes_have_full_similarity_and_frozen_result() -> None:
    node = _octahedron("Mo")

    score = score_nodes(node, node)

    assert score is not None
    assert score.topology == 1.0
    assert score.geometry == 1.0
    assert score.chemistry == 1.0
    assert score.total == 1.0
    with pytest.raises(FrozenInstanceError):
        score.total = 0.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "incompatible",
    [
        replace(_octahedron("Mo"), kind="interstitial"),
        replace(
            _octahedron("Mo"),
            coordination_number=5,
            ligand_elements=("O",) * 5,
            normalized_bond_lengths=(1.0,) * 5,
        ),
    ],
    ids=("kind", "coordination-number"),
)
def test_topology_mismatch_is_rejected(incompatible: MotifNode) -> None:
    assert score_nodes(_octahedron("Mo"), incompatible) is None


@pytest.mark.parametrize(
    "incompatible",
    [
        replace(
            _octahedron("Mo"),
            normalized_bond_lengths=(0.5, 0.5, 0.5, 1.5, 1.5, 1.5),
        ),
        replace(_octahedron("Mo"), distortion=0.20),
        replace(_octahedron("Mo"), angle_dispersion=0.20),
    ],
    ids=("bond-shape", "distortion", "angle-dispersion"),
)
def test_geometry_outside_tolerance_is_rejected(incompatible: MotifNode) -> None:
    assert score_nodes(_octahedron("Mo"), incompatible) is None


def test_ideal_octahedron_does_not_match_ideal_regular_trigonal_prism() -> None:
    ideal_octahedron = replace(
        _octahedron("Mo"), angle_dispersion=0.3333333333333333
    )
    ideal_regular_trigonal_prism = replace(
        _octahedron("Mo"), angle_dispersion=0.255120657057315
    )

    assert score_nodes(ideal_octahedron, ideal_regular_trigonal_prism) is None


def test_geometry_score_combines_sorted_bonds_distortion_and_angles() -> None:
    first = replace(
        _octahedron("Mo"),
        normalized_bond_lengths=(0.90, 0.95, 1.00, 1.00, 1.05, 1.10),
        distortion=0.02,
        angle_dispersion=0.03,
    )
    second = replace(
        _octahedron("Mo"),
        normalized_bond_lengths=(1.11, 0.99, 0.91, 1.04, 0.96, 0.99),
        distortion=0.04,
        angle_dispersion=0.06,
    )

    score = score_nodes(first, second)

    assert score is not None
    # Bond RMS = 0.01; normalized deviations are 1/15, 1/5, and 3/5.
    assert score.geometry == pytest.approx(0.632828630, abs=1e-9)


@pytest.mark.parametrize(
    ("first_lengths", "second_lengths"),
    [
        ((1.0,) * 5, (1.0,) * 6),
        ((), ()),
    ],
    ids=("unequal-tuples", "positive-coordination-with-empty-tuples"),
)
def test_malformed_bond_vector_is_rejected(
    first_lengths: tuple[float, ...], second_lengths: tuple[float, ...]
) -> None:
    first = replace(_octahedron("Mo"), normalized_bond_lengths=first_lengths)
    second = replace(_octahedron("Mo"), normalized_bond_lengths=second_lengths)

    assert score_nodes(first, second) is None


def test_zero_coordination_interstitials_have_well_defined_empty_geometry() -> None:
    first = MotifNode(
        id="I1",
        kind="interstitial",
        coordination_number=0,
        center_element="Na",
        ligand_elements=(),
        normalized_bond_lengths=(),
        distortion=0.0,
        angle_dispersion=0.0,
        unit_ids=(),
        occupancies=(("Na", 1.0),),
    )
    second = replace(first, id="I2")

    score = score_nodes(first, second)

    assert score is not None
    assert score.geometry == 1.0
    assert score.total == 1.0


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf])
def test_non_finite_geometry_is_rejected(invalid: float) -> None:
    malformed = replace(_octahedron("Mo"), distortion=invalid)

    assert score_nodes(_octahedron("Mo"), malformed) is None


def test_extreme_finite_bond_difference_is_rejected_without_overflow() -> None:
    extreme = replace(
        _octahedron("Mo"), normalized_bond_lengths=(1e200,) * 6
    )

    assert score_nodes(_octahedron("Mo"), extreme) is None


def test_mixed_occupancy_is_compared_as_a_distribution() -> None:
    first = _octahedron("Mo/W", occupancies=(("Mo", 0.75), ("W", 0.25)))
    same = _octahedron("Mo/W", occupancies=(("W", 0.25), ("Mo", 0.75)))
    changed_minor_component = _octahedron(
        "Mo/Re", occupancies=(("Mo", 0.75), ("Re", 0.25))
    )
    full_substitution = _octahedron("W")

    same_score = score_nodes(first, same)
    mixed_score = score_nodes(first, changed_minor_component)
    substituted_score = score_nodes(first, full_substitution)

    assert same_score is not None
    assert mixed_score is not None
    assert substituted_score is not None
    assert same_score.chemistry == 1.0
    assert substituted_score.chemistry < mixed_score.chemistry < same_score.chemistry


def test_center_chemistry_preserves_vacancy_magnitude() -> None:
    half_occupied = _octahedron("Na", occupancies=(("Na", 0.5),))
    fully_occupied = _octahedron("Na", occupancies=(("Na", 1.0),))

    forward = score_nodes(half_occupied, fully_occupied)
    reverse = score_nodes(fully_occupied, half_occupied)

    assert forward is not None
    assert reverse == forward
    assert forward.chemistry == pytest.approx(0.875)
    assert forward.total == pytest.approx(
        0.55 * forward.topology + 0.30 * forward.geometry + 0.15 * 0.875
    )


def test_center_chemistry_distinguishes_reported_overoccupancy() -> None:
    overoccupied = _octahedron("O", occupancies=(("O", 1.024),))
    fully_occupied = _octahedron("O", occupancies=(("O", 1.0),))

    score = score_nodes(overoccupied, fully_occupied)

    assert score is not None
    assert score.chemistry == pytest.approx(0.994140625)
    assert 0.0 <= score.total < 1.0


def test_duplicate_huge_occupancies_preserve_magnitude_without_overflow() -> None:
    huge = _octahedron(
        "Mo/W",
        occupancies=(("Mo", 1e308), ("Mo", 1e308), ("W", 1e308)),
    )
    equivalent = _octahedron(
        "Mo/W", occupancies=(("Mo", 2.0), ("W", 1.0))
    )

    score = score_nodes(huge, equivalent)

    assert score is not None
    # Element proportions are equal, but the astronomic total occupancy is not
    # chemically equivalent to the finite 3.0 total.
    assert score.chemistry == pytest.approx(0.75)
    assert all(
        math.isfinite(value) and 0.0 <= value <= 1.0
        for value in (
            score.topology,
            score.geometry,
            score.chemistry,
            score.total,
        )
    )


def test_non_finite_occupancies_are_ignored() -> None:
    noisy = _octahedron(
        "Mo/W",
        occupancies=(
            ("Mo", math.nan),
            ("W", math.inf),
            ("Re", -math.inf),
            ("Mo", 0.75),
            ("W", 0.25),
        ),
    )
    finite = _octahedron(
        "Mo/W", occupancies=(("Mo", 0.75), ("W", 0.25))
    )

    score = score_nodes(noisy, finite)

    assert score is not None
    assert score.chemistry == 1.0


def test_empty_occupancy_distribution_falls_back_to_center_element() -> None:
    unspecified = _octahedron("Mo", occupancies=())

    score = score_nodes(unspecified, _octahedron("Mo"))

    assert score is not None
    assert score.chemistry == 1.0


def test_score_is_exactly_symmetric_finite_and_bounded() -> None:
    first = _octahedron(
        "Mo/W/Re",
        occupancies=(("Re", 0.1), ("Mo", 0.7), ("W", 0.2)),
    )
    second = replace(
        _octahedron(
            "Mo/W/Nb",
            occupancies=(("Nb", 0.15), ("W", 0.15), ("Mo", 0.7)),
        ),
        ligand_elements=("F", "O", "O", "O", "O", "O"),
        normalized_bond_lengths=(1.01, 0.99, 1.0, 1.0, 1.0, 1.0),
        distortion=0.01,
        angle_dispersion=0.02,
    )

    forward = score_nodes(first, second)
    reverse = score_nodes(second, first)

    assert forward is not None
    assert reverse is not None
    assert forward == reverse
    assert all(
        math.isfinite(value) and 0.0 <= value <= 1.0
        for value in (
            forward.topology,
            forward.geometry,
            forward.chemistry,
            forward.total,
        )
    )


def test_ligand_substitution_reduces_chemistry_without_breaking_shape_match() -> None:
    substituted = replace(
        _octahedron("Mo"),
        ligand_elements=("O", "O", "O", "O", "O", "F"),
    )

    score = score_nodes(_octahedron("Mo"), substituted)

    assert score is not None
    assert score.topology == 1.0
    assert score.geometry == 1.0
    assert score.chemistry < 1.0


def test_chain_match_preserves_edge_kinds_and_reports_substitution() -> None:
    report = compare_motifs(
        _comparison_document("Mo", name="first-chain"),
        _comparison_document("W", name="second-chain"),
    )

    assert len(report.matches) == 1
    match = report.matches[0]
    assert match.classification == "chain"
    assert match.periodic_rank == 1
    assert match.node_pairs == (
        ("P1", "P1"),
        ("P2", "P2"),
        ("P3", "P3"),
        ("P4", "P4"),
    )
    assert len(match.edge_pairs) == 4
    assert match.edge_kinds == ("corner",) * 4
    assert len(report.substitutions) == 4
    assert report.substitutions[0].first_element == "Mo"
    assert report.substitutions[0].second_element == "W"
    assert report.unmatched_first == ()
    assert report.unmatched_second == ()
    assert not report.approximate


def test_extra_branch_and_interstitial_are_explicitly_unmatched() -> None:
    branch_edges = (
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P2", "P3", "corner", (0, 0, 0)),
        ("P3", "P4", "corner", (0, 0, 0)),
        ("P4", "P1", "corner", (1, 0, 0)),
        ("P2", "P5", "corner", (0, 0, 0)),
    )
    first = _comparison_document("Mo", name="plain-chain")
    second = _comparison_document(
        "Mo",
        node_count=5,
        edges=branch_edges,
        extra_interstitial=True,
        name="branched-chain",
    )

    report = compare_motifs(first, second)

    assert len(report.matches[0].node_pairs) == 4
    assert report.unmatched_first == ()
    assert {(node.node_id, node.kind) for node in report.unmatched_second} == {
        ("P5", "polyhedron"),
        ("I11", "interstitial"),
    }


def test_reported_topology_coverage_penalizes_unmatched_branch() -> None:
    chain_edges = (
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P2", "P3", "corner", (0, 0, 0)),
    )
    branched_edges = chain_edges + (("P2", "P4", "corner", (0, 0, 0)),)
    first = _comparison_document(
        "Mo",
        node_count=3,
        edges=chain_edges,
        classification="island",
        periodic_rank=0,
        name="three-node-chain",
    )
    second = _comparison_document(
        "Mo",
        node_count=4,
        edges=branched_edges,
        classification="island",
        periodic_rank=0,
        name="branched-chain",
    )

    report = compare_motifs(first, second)
    match = report.matches[0]

    # Symmetric coverage: mean(2*3/(3+4), 2*2/(2+3)) = 29/35.
    assert match.topology_score == pytest.approx(29.0 / 35.0)
    assert match.total_score == pytest.approx(
        0.55 * match.topology_score
        + 0.30 * match.geometry_score
        + 0.15 * match.chemistry_score
    )


def test_no_compatible_nodes_reports_no_common_motif() -> None:
    first = _comparison_document(
        "Mo",
        node_count=1,
        coordination_number=4,
        edges=(),
        classification="island",
        periodic_rank=0,
        name="tetrahedron",
    )
    second = _comparison_document(
        "W",
        node_count=1,
        coordination_number=6,
        edges=(),
        classification="island",
        periodic_rank=0,
        name="octahedron",
    )

    report = compare_motifs(first, second)

    assert report.matches == ()
    assert report.substitutions == ()
    assert tuple(node.node_id for node in report.unmatched_first) == ("P1",)
    assert tuple(node.node_id for node in report.unmatched_second) == ("P1",)
    assert not report.approximate


def test_symmetric_matches_choose_smallest_stable_id_tuple() -> None:
    first = _comparison_document(
        "Mo",
        node_count=1,
        edges=(),
        classification="island",
        periodic_rank=0,
        name="one-island",
    )
    second = _comparison_document(
        "Mo",
        node_count=2,
        edges=(),
        classification="island",
        periodic_rank=0,
        name="two-islands",
    )

    reports = tuple(compare_motifs(first, second) for _ in range(3))
    node_pair_runs = tuple(report.matches[0].node_pairs for report in reports)

    assert node_pair_runs == ((("P1", "P1"),),) * 3
    assert all(report.ambiguous for report in reports)
    assert all(report.equivalent_best_count == 2 for report in reports)
    assert all(report.ambiguity_reason == "equivalent_best_mappings" for report in reports)
    assert all(not report.exact for report in reports)


def test_parallel_edges_keep_only_a_rank_consistent_common_subset() -> None:
    periodic_edges = (
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (1, 0, 0)),
    )
    finite_edges = (
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (0, 0, 0)),
    )
    first = _comparison_document(
        "Mo",
        node_count=2,
        edges=periodic_edges,
        name="periodic-pair",
    )
    second = _comparison_document(
        "Mo",
        node_count=2,
        edges=finite_edges,
        classification="ring",
        periodic_rank=0,
        name="finite-pair",
    )

    report = compare_motifs(first, second)

    assert len(report.matches[0].node_pairs) == 2
    assert len(report.matches[0].edge_pairs) == 1
    assert report.matches[0].periodic_rank == 0


def test_parallel_edge_objective_finds_maximum_rank_consistent_subset() -> None:
    first_edges = (
        ("P1", "P1", "corner", (0, 0, 1)),
        ("P1", "P1", "corner", (0, 0, 1)),
        ("P1", "P1", "corner", (0, 0, 1)),
        ("P1", "P1", "corner", (0, 0, 1)),
    )
    second_edges = (
        ("P1", "P1", "corner", (0, 0, 1)),
        ("P1", "P1", "corner", (0, 1, 0)),
        ("P1", "P1", "corner", (0, 1, 1)),
        ("P1", "P1", "corner", (0, 1, 1)),
    )
    first = _comparison_document(
        "Mo",
        node_count=1,
        edges=first_edges,
        name="rank-one-loops",
    )
    second = _comparison_document(
        "Mo",
        node_count=1,
        edges=second_edges,
        classification="layer",
        periodic_rank=2,
        name="rank-two-loops",
    )

    report = compare_motifs(first, second)

    assert len(report.matches[0].edge_pairs) == 2
    assert report.matches[0].periodic_rank == 1
    assert not report.approximate


def test_parallel_edge_objective_can_repair_sorted_edges_before_subsetting() -> None:
    first_edges = (
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (0, 0, 1)),
    )
    second_edges = (
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "corner", (0, 0, 1)),
        ("P1", "P2", "corner", (0, 0, 1)),
        ("P1", "P2", "corner", (0, 1, 0)),
    )
    first = _comparison_document(
        "Mo",
        node_count=2,
        edges=first_edges,
        name="five-edge-rank-one",
    )
    second = _comparison_document(
        "Mo",
        node_count=2,
        edges=second_edges,
        classification="layer",
        periodic_rank=2,
        name="five-edge-rank-two",
    )

    report = compare_motifs(first, second)

    assert len(report.matches[0].node_pairs) == 2
    assert len(report.matches[0].edge_pairs) == 4
    assert report.matches[0].periodic_rank == 1
    assert not report.approximate


def test_deadline_expiring_after_parallel_pairing_marks_best_result_approximate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repeated_edges = tuple(
        ("P1", "P1", "corner", (1, 0, 0)) for _ in range(5_000)
    )
    first = _comparison_document(
        "Mo",
        node_count=1,
        edges=repeated_edges,
        name="many-loops-first",
    )
    second = _comparison_document(
        "Mo",
        node_count=1,
        edges=repeated_edges,
        name="many-loops-second",
    )

    class ControlledClock:
        expired = False

        def __call__(self) -> float:
            return 20.0 if self.expired else 0.0

    clock = ControlledClock()
    real_pairing = motif_comparison_module._edge_pairs_for_mapping

    def expire_after_pairing(*args: object, **kwargs: object):
        result = real_pairing(*args, **kwargs)
        clock.expired = True
        return result

    monkeypatch.setattr(
        motif_comparison_module,
        "_edge_pairs_for_mapping",
        expire_after_pairing,
    )
    monkeypatch.setattr(
        motif_comparison_module,
        "_monotonic",
        clock,
        raising=False,
    )

    report = compare_motifs(
        first,
        second,
        MatchLimits(max_states=50_000, max_seconds=10.0, max_nodes=96),
    )

    assert report.matches
    assert report.approximate
    assert "max_seconds" in report.limit_reasons


def test_partial_structural_unit_uses_selected_edge_rank_and_classification() -> None:
    report = compare_motifs(
        _comparison_document("Mo", name="partial-chain-first"),
        _comparison_document("Mo", name="partial-chain-second"),
        MatchLimits(max_states=1, max_seconds=1.0, max_nodes=96),
    )

    assert len(report.matches[0].node_pairs) == 1
    assert report.matches[0].edge_pairs == ()
    assert report.matches[0].periodic_rank == 0
    assert report.matches[0].classification == "island"


def test_reordering_connections_does_not_change_report_edge_semantics() -> None:
    edges = (
        ("P1", "P2", "corner", (0, 0, 0)),
        ("P1", "P2", "edge", (1, 0, 0)),
        ("P1", "P2", "face", (0, 1, 0)),
    )
    first_order = _comparison_document(
        "Mo",
        node_count=2,
        edges=edges,
        classification="layer",
        periodic_rank=2,
        name="order-independent-first",
    )
    reverse_order = _comparison_document(
        "Mo",
        node_count=2,
        edges=tuple(reversed(edges)),
        classification="layer",
        periodic_rank=2,
        name="order-independent-first",
    )
    reference = _comparison_document(
        "W",
        node_count=2,
        edges=edges,
        classification="layer",
        periodic_rank=2,
        name="order-independent-second",
    )

    first_report = compare_motifs(first_order, reference)
    reordered_report = compare_motifs(reverse_order, reference)

    assert first_report == reordered_report


def test_dense_mapping_over_python_recursion_limit_returns_bounded_report() -> None:
    node_count = 46
    dense_edges = tuple(
        (f"P{first}", f"P{second}", "corner", (0, 0, 0))
        for first in range(1, node_count + 1)
        for second in range(first + 1, node_count + 1)
    )
    first = _comparison_document(
        "Mo",
        node_count=node_count,
        edges=dense_edges,
        classification="island",
        periodic_rank=0,
        name="dense-first",
    )
    second = _comparison_document(
        "Mo",
        node_count=node_count,
        edges=dense_edges,
        classification="island",
        periodic_rank=0,
        name="dense-second",
    )

    report = compare_motifs(
        first,
        second,
        MatchLimits(max_states=90, max_seconds=10.0, max_nodes=96),
    )

    assert report.matches
    assert len(report.matches[0].node_pairs) == node_count
    assert report.approximate
    assert report.limit_reasons == ("max_states",)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_states": True},
        {"max_states": 1.0},
        {"max_states": math.nan},
        {"max_nodes": False},
        {"max_nodes": 1.0},
        {"max_nodes": math.nan},
        {"max_seconds": True},
        {"max_seconds": math.nan},
        {"max_seconds": math.inf},
        {"max_seconds": -1.0},
    ],
)
def test_match_limits_reject_invalid_numeric_types_and_values(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        MatchLimits(**kwargs)  # type: ignore[arg-type]


def test_state_limit_returns_deterministic_best_so_far_and_marks_approximate() -> None:
    first = _comparison_document("Mo", name="limited-first")
    second = _comparison_document("Mo", name="limited-second")
    limits = MatchLimits(max_states=1, max_seconds=1.0, max_nodes=96)

    reports = tuple(compare_motifs(first, second, limits) for _ in range(3))

    assert all(report.approximate for report in reports)
    assert all(report.limit_reasons == ("max_states",) for report in reports)
    assert all(report.states_explored == 1 for report in reports)
    assert tuple(report.matches[0].node_pairs for report in reports) == (
        (("P1", "P1"),),
    ) * 3


def test_zero_state_limit_marks_complete_graph_search_as_not_interpretable() -> None:
    first = _comparison_document("Mo", name="zero-state-first")
    second = _comparison_document("Mo", name="zero-state-second")

    report = compare_motifs(
        first,
        second,
        MatchLimits(max_states=0, max_seconds=5.0, max_nodes=128),
    )

    assert report.graph_complete is True
    assert report.approximate is True
    assert report.limit_reasons == ("max_states",)
    assert report.matches == ()
    assert report.result_interpretable is False


def test_node_and_time_limits_never_claim_a_complete_result() -> None:
    first = _comparison_document("Mo", node_count=2, edges=(), name="node-first")
    second = _comparison_document("Mo", node_count=2, edges=(), name="node-second")

    node_limited = compare_motifs(
        first,
        second,
        MatchLimits(max_states=50, max_seconds=1.0, max_nodes=1),
    )
    time_limited = compare_motifs(
        first,
        second,
        MatchLimits(max_states=50, max_seconds=0.0, max_nodes=96),
    )

    assert node_limited.approximate
    assert node_limited.limit_reasons == ("max_nodes",)
    assert node_limited.graph_complete is False
    assert node_limited.matches == ()
    # Nodes skipped before graph construction are unknown, not scientifically
    # established unmatched nodes.
    assert node_limited.unmatched_first == ()
    assert node_limited.unmatched_second == ()
    assert time_limited.approximate
    assert time_limited.limit_reasons == ("max_seconds",)
    assert time_limited.graph_complete is False
    assert time_limited.matches == ()


def test_deadline_starts_before_graph_build_and_skips_second_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _comparison_document("Mo", name="build-budget-first")
    second = _comparison_document("Mo", name="build-budget-second")
    real_builder = motif_comparison_module.build_motif_graph
    build_calls: list[str] = []

    class ControlledClock:
        expired = False

        def __call__(self) -> float:
            return 2.0 if self.expired else 0.0

    clock = ControlledClock()

    def instrumented_builder(document, *, budget):
        build_calls.append(document.id)
        graph = real_builder(document, budget=budget)
        clock.expired = True
        return graph

    monkeypatch.setattr(motif_comparison_module, "_monotonic", clock, raising=False)
    monkeypatch.setattr(
        motif_comparison_module,
        "build_motif_graph",
        instrumented_builder,
    )

    report = compare_motifs(
        first,
        second,
        MatchLimits(max_states=100, max_seconds=1.0, max_nodes=96),
    )

    assert build_calls == [first.id]
    assert report.approximate
    assert report.limit_reasons == ("max_seconds",)
    assert report.matches == ()
    assert report.unmatched_first == ()
    assert report.unmatched_second == ()


def test_max_nodes_is_applied_during_each_graph_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _comparison_document("Mo", name="node-build-first")
    second = _comparison_document("Mo", name="node-build-second")
    real_builder = motif_comparison_module.build_motif_graph
    built_node_counts: list[int] = []

    def instrumented_builder(document, *, budget):
        graph = real_builder(document, budget=budget)
        built_node_counts.append(len(graph.nodes))
        return graph

    monkeypatch.setattr(
        motif_comparison_module,
        "build_motif_graph",
        instrumented_builder,
    )

    report = compare_motifs(
        first,
        second,
        MatchLimits(max_states=100, max_seconds=1.0, max_nodes=1),
    )

    assert built_node_counts == [1, 1]
    assert report.matches == ()
    assert report.unmatched_first == ()
    assert report.unmatched_second == ()
    assert report.approximate
    assert report.limit_reasons == ("max_nodes",)


def test_match_limits_and_report_records_are_immutable() -> None:
    report = compare_motifs(
        _comparison_document("Mo", name="immutable-first"),
        _comparison_document("Mo", name="immutable-second"),
    )

    with pytest.raises(FrozenInstanceError):
        report.approximate = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        report.matches[0].classification = "layer"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        MatchLimits().max_states = 1  # type: ignore[misc]
