from __future__ import annotations

from types import MappingProxyType

import pytest

from crystal_viewer.analysis.motif_comparison import (
    AtomSubstitution,
    MotifComparisonReport,
    MotifMatch,
    UnmatchedNode,
)
from crystal_viewer.ui.comparison_highlight import (
    MATCH_PALETTE,
    MUTED_COLOR,
    OUTLINE_RED,
    SUBSTITUTION_YELLOW,
    ComparisonHighlight,
    highlight_pair,
)


def _match(
    match_id: str,
    *node_pairs: tuple[str, str],
) -> MotifMatch:
    return MotifMatch(
        id=match_id,
        classification="chain",
        periodic_rank=1,
        node_pairs=node_pairs,
        edge_pairs=(),
        edge_kinds=(),
        topology_score=1.0,
        geometry_score=0.9,
        chemistry_score=0.8,
        total_score=0.9,
    )


def _substitution(first_node_id: str, second_node_id: str) -> AtomSubstitution:
    return AtomSubstitution(
        match_id="M1",
        first_node_id=first_node_id,
        second_node_id=second_node_id,
        first_site_index=97,
        second_site_index=98,
        first_element="Mo",
        second_element="W",
        first_occupancies=(("Mo", 1.0),),
        second_occupancies=(("W", 1.0),),
    )


def _unmatched(side: str, node_id: str, kind: str) -> UnmatchedNode:
    return UnmatchedNode(
        side=side,
        node_id=node_id,
        kind=kind,
        element="Si",
        site_index=99,
        unit_ids=(),
    )


def _report(
    *,
    matches: tuple[MotifMatch, ...] = (),
    substitutions: tuple[AtomSubstitution, ...] = (),
    unmatched_first: tuple[UnmatchedNode, ...] = (),
    unmatched_second: tuple[UnmatchedNode, ...] = (),
) -> MotifComparisonReport:
    return MotifComparisonReport(
        first_document_id="left",
        second_document_id="right",
        matches=matches,
        substitutions=substitutions,
        unmatched_first=unmatched_first,
        unmatched_second=unmatched_second,
        approximate=False,
        states_explored=4,
    )


def test_pair_uses_deterministic_cross_side_colors_and_direction() -> None:
    report = _report(
        matches=(
            _match("M2", ("P1", "P7"), ("I3", "I8")),
            _match("M9", ("P2", "P6")),
        )
    )

    left, right = highlight_pair(report)
    repeated_left, repeated_right = highlight_pair(report)

    assert left.polyhedron_colors == {"P1": MATCH_PALETTE[0], "P2": MATCH_PALETTE[1]}
    assert right.polyhedron_colors == {"P7": MATCH_PALETTE[0], "P6": MATCH_PALETTE[1]}
    assert left.atom_colors == {3: MATCH_PALETTE[0]}
    assert right.atom_colors == {8: MATCH_PALETTE[0]}
    assert "P7" not in left.polyhedron_colors
    assert "P1" not in right.polyhedron_colors
    assert (left, right) == (repeated_left, repeated_right)


def test_substitution_is_yellow_and_unmatched_state_has_final_precedence() -> None:
    report = _report(
        matches=(_match("M1", ("P1", "P7"), ("I3", "I8")),),
        substitutions=(
            _substitution("P1", "P7"),
            _substitution("I3", "I8"),
        ),
        unmatched_first=(
            _unmatched("first", "P1", "polyhedron"),
            _unmatched("first", "I3", "interstitial"),
        ),
    )

    left, right = highlight_pair(report)

    assert left.polyhedron_colors["P1"] == MUTED_COLOR
    assert left.atom_colors[3] == MUTED_COLOR
    assert left.muted_ids == frozenset({"P1", "I3"})
    assert left.outline_ids == frozenset({"P1", "I3"})
    assert right.polyhedron_colors["P7"] == SUBSTITUTION_YELLOW
    assert right.atom_colors[8] == SUBSTITUTION_YELLOW
    assert right.muted_ids == frozenset()
    assert OUTLINE_RED == "#c94242"


def test_malformed_or_inconsistent_node_ids_do_not_invent_targets() -> None:
    report = _report(
        matches=(
            _match("M1", ("P", "Ibad"), ("X3", "")),
            _match("M2", (None, 7)),  # type: ignore[arg-type]
        ),
        substitutions=(_substitution("bad", "I-8"),),
        unmatched_first=(
            _unmatched("first", "I4", "polyhedron"),
            _unmatched("first", "P4", "interstitial"),
            _unmatched("first", "P5", "unknown"),
        ),
        unmatched_second=(_unmatched("second", "not-a-node", "interstitial"),),
    )

    left, right = highlight_pair(report)

    assert left.polyhedron_colors == {}
    assert left.atom_colors == {}
    assert left.outline_ids == frozenset()
    assert left.muted_ids == frozenset()
    assert right.polyhedron_colors == {}
    assert right.atom_colors == {}


def test_highlight_takes_copy_safe_immutable_snapshots() -> None:
    polyhedron_colors = {"P1": "#123456"}
    atom_colors = {3: "#654321"}
    outline_ids = {"P1"}
    muted_ids = {"I3"}

    highlight = ComparisonHighlight(
        polyhedron_colors,
        atom_colors,
        outline_ids,
        muted_ids,
    )
    polyhedron_colors["P1"] = "#ffffff"
    atom_colors[3] = "#ffffff"
    outline_ids.clear()
    muted_ids.clear()

    assert isinstance(highlight.polyhedron_colors, MappingProxyType)
    assert isinstance(highlight.atom_colors, MappingProxyType)
    assert highlight.polyhedron_colors == {"P1": "#123456"}
    assert highlight.atom_colors == {3: "#654321"}
    assert highlight.outline_ids == frozenset({"P1"})
    assert highlight.muted_ids == frozenset({"I3"})
    with pytest.raises(TypeError):
        highlight.polyhedron_colors["P2"] = "#000000"  # type: ignore[index]


def test_oversized_interstitial_index_is_ignored_without_integer_conversion_error() -> None:
    oversized_id = "I" + "9" * 5002
    report = _report(matches=(_match("M1", (oversized_id, "not-a-node")),))

    left, right = highlight_pair(report)

    assert left.atom_colors == {}
    assert right.atom_colors == {}
