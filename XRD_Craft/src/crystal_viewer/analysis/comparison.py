"""Typed, explainable comparison of crystallochemical descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, cast

from crystal_viewer.analysis.descriptors.builders import build_descriptors
from crystal_viewer.analysis.descriptors.model import (
    DescriptorKind,
    DescriptorValue,
    DistributionSummary,
    FocusCommand,
)
from crystal_viewer.analysis.hierarchy import HierarchyLevel
from crystal_viewer.analysis.motif_comparison import (
    MOTIF_ALGORITHM_VERSION,
    MatchLimits,
    MotifComparisonReport,
    MotifMatch,
    compare_motifs,
)
from crystal_viewer.core.document import StructureDocument


MAX_COMPARISON_CACHE_ENTRIES = 8


class ComparisonState(StrEnum):
    SIMILAR = "similar"
    MODERATE = "moderate"
    DIFFERENT = "different"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class NumericTolerance:
    similar_absolute: float
    moderate_absolute: float


DEFAULT_POLICY: Mapping[str, NumericTolerance] = {
    "cell.a": NumericTolerance(0.02, 0.10),
    "cell.b": NumericTolerance(0.02, 0.10),
    "cell.c": NumericTolerance(0.02, 0.10),
    "cell.alpha": NumericTolerance(0.10, 0.50),
    "cell.beta": NumericTolerance(0.10, 0.50),
    "cell.gamma": NumericTolerance(0.10, 0.50),
    "cell.volume": NumericTolerance(1.0, 5.0),
    "cell.c_over_a": NumericTolerance(0.005, 0.020),
    "mo_o.distortion_index": NumericTolerance(0.002, 0.01),
    "mo_o.d6_minus_d5": NumericTolerance(0.02, 0.08),
    "mo_o.off_centering": NumericTolerance(0.02, 0.08),
    "mo_o.strong_5_plus_1_fraction": NumericTolerance(0.05, 0.20),
}


@dataclass(frozen=True, slots=True)
class ComparisonCell:
    document_id: str
    display: str
    state: ComparisonState
    raw: object = None
    warning: str = ""


@dataclass(frozen=True, slots=True)
class SectionSummary:
    name: str
    difference_count: int
    summary: str


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    descriptor_id: str
    title: str
    section: str
    cells: tuple[ComparisonCell, ...]
    method_id: str = ""
    focus: FocusCommand | None = None
    expanded_records: tuple[Mapping[str, object], ...] = ()
    include_in_report: bool = True

    @property
    def has_difference(self) -> bool:
        return any(
            cell.state in {ComparisonState.MODERATE, ComparisonState.DIFFERENT}
            for cell in self.cells
        )


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    document_ids: tuple[str, ...]
    document_titles: tuple[str, ...]
    rows: tuple[ComparisonRow, ...]
    warnings: tuple[str, ...] = ()

    def row(self, descriptor_id: str) -> ComparisonRow:
        return next(row for row in self.rows if row.descriptor_id == descriptor_id)


def motif_cache_key(
    first_id: str,
    second_id: str,
    limits: MatchLimits,
    first_content_id: str = "",
    second_content_id: str = "",
) -> tuple[object, ...]:
    """Return the directional, algorithm-specific key for one motif search."""
    return (
        MOTIF_ALGORITHM_VERSION,
        first_id,
        first_content_id,
        second_id,
        second_content_id,
        limits,
    )


def cached_compare(
    first: StructureDocument,
    second: StructureDocument,
    limits: MatchLimits = MatchLimits(),
    *,
    compute: Callable[[], MotifComparisonReport] | None = None,
) -> MotifComparisonReport:
    """Return one complete motif report, caching only successful computations."""
    key = motif_cache_key(
        first.id,
        second.id,
        limits,
        first.content_identity(),
        second.content_identity(),
    )
    cached = first.comparison_cache.get(key)
    if isinstance(cached, MotifComparisonReport):
        return cached

    report = compute() if compute is not None else compare_motifs(first, second, limits)
    first.comparison_cache[key] = report
    while len(first.comparison_cache) > MAX_COMPARISON_CACHE_ENTRIES:
        first.comparison_cache.pop(next(iter(first.comparison_cache)))
    return report


def _numeric_value(descriptor: DescriptorValue) -> float | None:
    if descriptor.kind is DescriptorKind.UNAVAILABLE or descriptor.value is None:
        return None
    if isinstance(descriptor.value, DistributionSummary):
        return descriptor.value.mean if descriptor.value.count else None
    if isinstance(descriptor.value, (int, float)):
        return float(descriptor.value)
    return None


def _display(descriptor: DescriptorValue) -> str:
    if descriptor.kind is DescriptorKind.UNAVAILABLE or descriptor.value is None:
        return "—"
    if isinstance(descriptor.value, DistributionSummary):
        if not descriptor.value.count or descriptor.value.mean is None:
            return "—"
        return f"{descriptor.value.mean:.4g} ({descriptor.value.minimum:.4g}–{descriptor.value.maximum:.4g})"
    if isinstance(descriptor.value, float):
        return f"{descriptor.value:.6g}"
    if isinstance(descriptor.value, Mapping):
        return ", ".join(f"{key}: {value}" for key, value in descriptor.value.items()) or "—"
    return str(descriptor.value)


def _state(
    descriptor: DescriptorValue,
    baseline: DescriptorValue,
    tolerance: NumericTolerance | None,
) -> ComparisonState:
    current_numeric = _numeric_value(descriptor)
    baseline_numeric = _numeric_value(baseline)
    if descriptor.kind is DescriptorKind.UNAVAILABLE:
        return ComparisonState.UNAVAILABLE
    if isinstance(descriptor.value, DistributionSummary) and not descriptor.value.count:
        return ComparisonState.UNAVAILABLE
    if current_numeric is not None:
        if baseline_numeric is None:
            return ComparisonState.UNAVAILABLE
        limits = tolerance or NumericTolerance(0.0, 0.0)
        delta = abs(current_numeric - baseline_numeric)
        if delta <= limits.similar_absolute:
            return ComparisonState.SIMILAR
        if delta <= limits.moderate_absolute:
            return ComparisonState.MODERATE
        return ComparisonState.DIFFERENT
    if descriptor.value is None or baseline.value is None:
        return ComparisonState.UNAVAILABLE
    return (
        ComparisonState.SIMILAR
        if descriptor.value == baseline.value
        else ComparisonState.DIFFERENT
    )


def _focus(identifier: str) -> FocusCommand | None:
    if identifier.startswith("mo_o."):
        return FocusCommand(
            "isolate",
            HierarchyLevel.POLYHEDRA,
            "polyhedron-type",
            {"center": "Mo", "coordination": 6},
        )
    if identifier.startswith("topology."):
        return FocusCommand(
            "match-projection",
            HierarchyLevel.STRUCTURAL_UNITS,
            "common-periodic-component",
            {},
        )
    return None


def _expanded(descriptors: tuple[DescriptorValue, ...]) -> tuple[Mapping[str, object], ...]:
    records = []
    for descriptor in descriptors:
        value = descriptor.value
        if not isinstance(value, DistributionSummary):
            return ()
        records.append(
            {
                "minimum": value.minimum,
                "mean": value.mean,
                "maximum": value.maximum,
                "std": value.std,
                "count": value.count,
                "values": value.values,
            }
        )
    return tuple(records)


def _interstitial_site_index(node_id: str) -> int | None:
    if not node_id.startswith("I"):
        return None
    try:
        return int(node_id[1:])
    except ValueError:
        return None


def _motif_not_evaluated(motif_report: MotifComparisonReport) -> bool:
    return not motif_report.graph_complete or not motif_report.result_interpretable


def _motif_cell_warnings(motif_report: MotifComparisonReport) -> tuple[str, ...]:
    warnings = []
    if _motif_not_evaluated(motif_report):
        reasons = ", ".join(motif_report.limit_reasons) or "unspecified limit"
        cause = (
            "graph construction incomplete"
            if not motif_report.graph_complete
            else "search stopped before an interpretable result"
        )
        warnings.append(
            f"Motif comparison not evaluated: {cause}; "
            f"limits reached: {reasons}"
        )
    elif motif_report.approximate:
        reasons = ", ".join(motif_report.limit_reasons) or "unspecified limit"
        warnings.append(f"Approximate motif result: {reasons}")
    if motif_report.ambiguous:
        qualifier = "at least " if motif_report.approximate else ""
        count = max(2, motif_report.equivalent_best_count)
        warnings.append(
            "Ambiguous motif result: "
            f"{qualifier}{count} equivalent best mappings"
        )
    return tuple(warnings)


def _motif_cell_warning(motif_report: MotifComparisonReport) -> str:
    return "; ".join(_motif_cell_warnings(motif_report))


def _matched_focus(match: MotifMatch) -> FocusCommand:
    first_node_ids = tuple(first for first, _ in match.node_pairs)
    second_node_ids = tuple(second for _, second in match.node_pairs)
    return FocusCommand(
        "isolate",
        HierarchyLevel.STRUCTURAL_UNITS,
        "motif-pair",
        {
            "match_id": match.id,
            "first_node_ids": first_node_ids,
            "second_node_ids": second_node_ids,
            "first_polyhedron_ids": tuple(
                identifier for identifier in first_node_ids if identifier.startswith("P")
            ),
            "second_polyhedron_ids": tuple(
                identifier for identifier in second_node_ids if identifier.startswith("P")
            ),
            "first_atom_indices": tuple(
                site_index
                for identifier in first_node_ids
                if (site_index := _interstitial_site_index(identifier)) is not None
            ),
            "second_atom_indices": tuple(
                site_index
                for identifier in second_node_ids
                if (site_index := _interstitial_site_index(identifier)) is not None
            ),
            "first_edge_ids": tuple(first for first, _ in match.edge_pairs),
            "second_edge_ids": tuple(second for _, second in match.edge_pairs),
        },
    )


def _match_row(
    documents: tuple[StructureDocument, StructureDocument],
    motif_report: MotifComparisonReport,
    match: MotifMatch,
) -> ComparisonRow:
    node_count = len(match.node_pairs)
    edge_count = len(match.edge_pairs)
    display = f"{match.classification}: {node_count} nodes · {edge_count} connections"
    has_substitution = any(
        substitution.match_id == match.id
        for substitution in motif_report.substitutions
    )
    state = (
        ComparisonState.MODERATE
        if motif_report.approximate or motif_report.ambiguous or has_substitution
        else ComparisonState.SIMILAR
    )
    raw_common = {
        "match_id": match.id,
        "classification": match.classification,
        "periodic_rank": match.periodic_rank,
        "edge_kinds": match.edge_kinds,
        "topology_score": match.topology_score,
        "geometry_score": match.geometry_score,
        "chemistry_score": match.chemistry_score,
        "total_score": match.total_score,
        "exact": motif_report.exact,
        "graph_complete": motif_report.graph_complete,
        "result_interpretable": motif_report.result_interpretable,
        "approximate": motif_report.approximate,
        "limit_reasons": motif_report.limit_reasons,
        "ambiguous": motif_report.ambiguous,
        "equivalent_best_count": motif_report.equivalent_best_count,
        "ambiguity_reason": motif_report.ambiguity_reason,
    }
    first_ids = tuple(first for first, _ in match.node_pairs)
    second_ids = tuple(second for _, second in match.node_pairs)
    return ComparisonRow(
        descriptor_id=f"motif.match.{match.id}",
        title=f"Common {match.classification}",
        section="Structural Motifs",
        cells=tuple(
            ComparisonCell(
                document_id=document.id,
                display=display,
                state=state,
                raw={**raw_common, "node_ids": node_ids},
                warning=_motif_cell_warning(motif_report),
            )
            for document, node_ids in zip(
                documents, (first_ids, second_ids), strict=True
            )
        ),
        method_id=MOTIF_ALGORITHM_VERSION,
        focus=_matched_focus(match),
        expanded_records=tuple(
            {
                "first_node_id": first,
                "second_node_id": second,
            }
            for first, second in match.node_pairs
        ),
    )


def _empty_motif_row(
    documents: tuple[StructureDocument, StructureDocument],
    motif_report: MotifComparisonReport,
) -> ComparisonRow:
    if _motif_not_evaluated(motif_report):
        warning = _motif_cell_warning(motif_report)
        return ComparisonRow(
            descriptor_id="motif.common",
            title="Common motif",
            section="Structural Motifs",
            cells=tuple(
                ComparisonCell(
                    document.id,
                    "Not evaluated",
                    ComparisonState.UNAVAILABLE,
                    None,
                    warning,
                )
                for document in documents
            ),
            method_id=MOTIF_ALGORITHM_VERSION,
        )
    warning = (
        _motif_cell_warning(motif_report)
        if motif_report.approximate or motif_report.ambiguous
        else "No compatible common motif was found."
    )
    return ComparisonRow(
        descriptor_id="motif.common",
        title="Common motif",
        section="Structural Motifs",
        cells=tuple(
            ComparisonCell(document.id, "none", ComparisonState.DIFFERENT, (), warning)
            for document in documents
        ),
        method_id=MOTIF_ALGORITHM_VERSION,
    )


def _connection_rows(
    documents: tuple[StructureDocument, StructureDocument],
    motif_report: MotifComparisonReport,
) -> tuple[ComparisonRow, ComparisonRow]:
    if _motif_not_evaluated(motif_report):
        warning = _motif_cell_warning(motif_report)

        def unavailable_row(descriptor_id: str, title: str) -> ComparisonRow:
            return ComparisonRow(
                descriptor_id=descriptor_id,
                title=title,
                section="Connections and Interstitial Atoms",
                cells=tuple(
                    ComparisonCell(
                        document.id,
                        "Not evaluated",
                        ComparisonState.UNAVAILABLE,
                        None,
                        warning,
                    )
                    for document in documents
                ),
                method_id=MOTIF_ALGORITHM_VERSION,
            )

        return (
            unavailable_row("connections.substitutions", "Atom substitutions"),
            unavailable_row("connections.unmatched", "Unmatched nodes"),
        )

    substitutions = motif_report.substitutions
    warning = _motif_cell_warning(motif_report)
    substitution_focus = FocusCommand(
        "isolate",
        HierarchyLevel.STRUCTURAL_UNITS,
        "motif-substitutions",
        {
            "first_polyhedron_ids": tuple(
                item.first_node_id
                for item in substitutions
                if item.first_node_id.startswith("P")
            ),
            "second_polyhedron_ids": tuple(
                item.second_node_id
                for item in substitutions
                if item.second_node_id.startswith("P")
            ),
            "first_atom_indices": tuple(
                item.first_site_index
                for item in substitutions
                if item.first_node_id.startswith("I")
                and item.first_site_index is not None
            ),
            "second_atom_indices": tuple(
                item.second_site_index
                for item in substitutions
                if item.second_node_id.startswith("I")
                and item.second_site_index is not None
            ),
        },
    )
    substitutions_by_side = (
        tuple(item.first_element for item in substitutions),
        tuple(item.second_element for item in substitutions),
    )
    substitution_cells = tuple(
        ComparisonCell(
            document.id,
            ", ".join(elements) if elements else "none",
            ComparisonState.DIFFERENT if substitutions else ComparisonState.SIMILAR,
            elements,
            warning,
        )
        for document, elements in zip(documents, substitutions_by_side, strict=True)
    )
    substitution_row = ComparisonRow(
        descriptor_id="connections.substitutions",
        title="Atom substitutions",
        section="Connections and Interstitial Atoms",
        cells=substitution_cells,
        method_id=MOTIF_ALGORITHM_VERSION,
        focus=substitution_focus,
        expanded_records=tuple(
            {
                "match_id": item.match_id,
                "first_node_id": item.first_node_id,
                "second_node_id": item.second_node_id,
                "first_element": item.first_element,
                "second_element": item.second_element,
            }
            for item in substitutions
        ),
    )

    unmatched_by_side = (motif_report.unmatched_first, motif_report.unmatched_second)
    unmatched_focus = FocusCommand(
        "isolate",
        HierarchyLevel.STRUCTURAL_UNITS,
        "unmatched-pair",
        {
            "first_polyhedron_ids": tuple(
                item.node_id for item in motif_report.unmatched_first if item.kind == "polyhedron"
            ),
            "second_polyhedron_ids": tuple(
                item.node_id for item in motif_report.unmatched_second if item.kind == "polyhedron"
            ),
            "first_atom_indices": tuple(
                item.site_index
                for item in motif_report.unmatched_first
                if item.kind == "interstitial" and item.site_index is not None
            ),
            "second_atom_indices": tuple(
                item.site_index
                for item in motif_report.unmatched_second
                if item.kind == "interstitial" and item.site_index is not None
            ),
        },
    )
    unmatched_row = ComparisonRow(
        descriptor_id="connections.unmatched",
        title="Unmatched nodes",
        section="Connections and Interstitial Atoms",
        cells=tuple(
            ComparisonCell(
                document.id,
                str(len(items)),
                ComparisonState.DIFFERENT if items else ComparisonState.SIMILAR,
                tuple(item.node_id for item in items),
                warning,
            )
            for document, items in zip(documents, unmatched_by_side, strict=True)
        ),
        method_id=MOTIF_ALGORITHM_VERSION,
        focus=unmatched_focus,
        expanded_records=tuple(
            {
                "side": item.side,
                "node_id": item.node_id,
                "kind": item.kind,
                "element": item.element,
                "site_index": item.site_index,
            }
            for item in motif_report.unmatched_nodes
        ),
    )
    return substitution_row, unmatched_row


def _motif_rows(
    documents: tuple[StructureDocument, ...],
    motif_report: MotifComparisonReport,
) -> tuple[ComparisonRow, ...]:
    if len(documents) != 2:
        raise ValueError("A motif report requires exactly two structures.")
    pair = cast(tuple[StructureDocument, StructureDocument], documents)
    if (motif_report.first_document_id, motif_report.second_document_id) != tuple(
        document.id for document in pair
    ):
        raise ValueError("Motif report document order does not match the comparison.")
    motif_rows = tuple(
        _match_row(pair, motif_report, match) for match in motif_report.matches
    ) or (_empty_motif_row(pair, motif_report),)
    return motif_rows + _connection_rows(pair, motif_report)


def compare_documents(
    documents: tuple[StructureDocument, ...] | list[StructureDocument],
    policy: Mapping[str, NumericTolerance] = DEFAULT_POLICY,
    motif_report: MotifComparisonReport | None = None,
) -> ComparisonReport:
    documents = tuple(documents)
    if not 1 <= len(documents) <= 4:
        raise ValueError("Comparison requires one to four structures.")
    descriptor_sets = tuple(build_descriptors(document) for document in documents)
    identifiers = tuple(descriptor_sets[0])
    rows = []
    for identifier in identifiers:
        descriptors = tuple(values[identifier] for values in descriptor_sets)
        baseline = descriptors[0]
        cells = tuple(
            ComparisonCell(
                document_id=document.id,
                display=_display(descriptor),
                state=_state(descriptor, baseline, policy.get(identifier)),
                raw=descriptor.value,
                warning=descriptor.warning,
            )
            for document, descriptor in zip(documents, descriptors, strict=True)
        )
        rows.append(
            ComparisonRow(
                descriptor_id=identifier,
                title=baseline.title,
                section=baseline.section,
                cells=cells,
                method_id=baseline.method_id,
                focus=_focus(identifier),
                expanded_records=_expanded(descriptors),
            )
        )
    motif_rows = _motif_rows(documents, motif_report) if motif_report is not None else ()
    motif_warnings: tuple[str, ...] = ()
    if motif_report is not None:
        collected = []
        if _motif_not_evaluated(motif_report):
            collected.append(_motif_cell_warning(motif_report))
        elif motif_report.approximate:
            collected.append(
                "Motif comparison is approximate; limits reached: "
                + (", ".join(motif_report.limit_reasons) or "unspecified limit")
            )
        if motif_report.ambiguous:
            qualifier = "at least " if motif_report.approximate else ""
            collected.append(
                "Ambiguous motif comparison: "
                f"{qualifier}{max(2, motif_report.equivalent_best_count)} "
                "equivalent best mappings"
            )
        motif_warnings = tuple(collected)
    return ComparisonReport(
        document_ids=tuple(document.id for document in documents),
        document_titles=tuple(document.structure.name for document in documents),
        rows=tuple(rows) + motif_rows,
        warnings=(
            tuple(warning.message for document in documents for warning in document.warnings)
            + motif_warnings
        ),
    )
