"""Immutable semantic colors for one directional motif comparison."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import AbstractSet, Mapping

from crystal_viewer.analysis.motif_comparison import MotifComparisonReport


# Okabe-Ito-derived colors, excluding yellow so substitutions remain distinct.
MATCH_PALETTE = (
    "#0072b2",
    "#009e73",
    "#cc79a7",
    "#d55e00",
    "#56b4e9",
    "#6f5aa8",
)
SUBSTITUTION_YELLOW = "#e6ae27"
MUTED_COLOR = "#a8b0ba"
OUTLINE_RED = "#c94242"

_POLYHEDRON_ID = re.compile(r"P[1-9]\d*\Z")
_INTERSTITIAL_ID = re.compile(r"I(?:0|[1-9]\d*)\Z")
_MAX_SITE_INDEX = 2_147_483_647


@dataclass(frozen=True, slots=True)
class ComparisonHighlight:
    """Copy-safe temporary rendering state for one structure viewer."""

    polyhedron_colors: Mapping[str, str]
    atom_colors: Mapping[int, str]
    outline_ids: AbstractSet[str]
    muted_ids: AbstractSet[str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "polyhedron_colors",
            MappingProxyType(dict(self.polyhedron_colors)),
        )
        object.__setattr__(
            self,
            "atom_colors",
            MappingProxyType(dict(self.atom_colors)),
        )
        object.__setattr__(self, "outline_ids", frozenset(self.outline_ids))
        object.__setattr__(self, "muted_ids", frozenset(self.muted_ids))


@dataclass(slots=True)
class _MutableHighlight:
    polyhedron_colors: dict[str, str]
    atom_colors: dict[int, str]
    outline_ids: set[str]
    muted_ids: set[str]

    @classmethod
    def empty(cls) -> _MutableHighlight:
        return cls({}, {}, set(), set())

    def freeze(self) -> ComparisonHighlight:
        return ComparisonHighlight(
            self.polyhedron_colors,
            self.atom_colors,
            self.outline_ids,
            self.muted_ids,
        )


def _node_target(node_id: object) -> tuple[str, str | int] | None:
    if not isinstance(node_id, str):
        return None
    if _POLYHEDRON_ID.fullmatch(node_id):
        return "polyhedron", node_id
    if _INTERSTITIAL_ID.fullmatch(node_id):
        digits = node_id[1:]
        if len(digits) > 10:
            return None
        try:
            site_index = int(digits)
        except (ValueError, OverflowError):
            return None
        if site_index > _MAX_SITE_INDEX:
            return None
        return "atom", site_index
    return None


def _set_node_color(
    highlight: _MutableHighlight,
    node_id: str,
    color: str,
    *,
    require_existing: bool = False,
) -> bool:
    target = _node_target(node_id)
    if target is None:
        return False
    kind, key = target
    if kind == "polyhedron":
        if require_existing and key not in highlight.polyhedron_colors:
            return False
        highlight.polyhedron_colors[str(key)] = color
    else:
        if require_existing and key not in highlight.atom_colors:
            return False
        highlight.atom_colors[int(key)] = color
    return True


def _set_unmatched(
    highlight: _MutableHighlight,
    node_id: str,
    kind: str,
) -> None:
    target = _node_target(node_id)
    expected_kind = {
        "polyhedron": "polyhedron",
        "interstitial": "atom",
    }.get(kind)
    if target is None or target[0] != expected_kind:
        return
    _set_node_color(highlight, node_id, MUTED_COLOR)
    highlight.muted_ids.add(node_id)
    highlight.outline_ids.add(node_id)


def highlight_pair(
    report: MotifComparisonReport,
) -> tuple[ComparisonHighlight, ComparisonHighlight]:
    """Convert one directional report into left/right semantic highlights."""

    first = _MutableHighlight.empty()
    second = _MutableHighlight.empty()

    for match_index, match in enumerate(report.matches):
        color = MATCH_PALETTE[match_index % len(MATCH_PALETTE)]
        for first_node_id, second_node_id in match.node_pairs:
            _set_node_color(first, first_node_id, color)
            _set_node_color(second, second_node_id, color)

    for substitution in report.substitutions:
        _set_node_color(
            first,
            substitution.first_node_id,
            SUBSTITUTION_YELLOW,
            require_existing=True,
        )
        _set_node_color(
            second,
            substitution.second_node_id,
            SUBSTITUTION_YELLOW,
            require_existing=True,
        )

    # Unmatched is applied last so it wins even for a malformed overlapping
    # report and remains visually distinct from both match and substitution.
    for node in report.unmatched_first:
        _set_unmatched(first, node.node_id, node.kind)
    for node in report.unmatched_second:
        _set_unmatched(second, node.node_id, node.kind)

    return first.freeze(), second.freeze()
