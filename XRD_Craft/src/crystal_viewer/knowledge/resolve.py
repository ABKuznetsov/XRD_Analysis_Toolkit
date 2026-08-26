from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from crystal_viewer.knowledge.model import InterpretationChanges, KnowledgePreset, PeriodicBondChange


@dataclass(frozen=True, slots=True)
class InterpretationOverlay:
    domain_id: str
    changes: InterpretationChanges
    provenance: str
    preset_id: str | None = None


@dataclass(slots=True)
class DocumentKnowledgeState:
    accepted: InterpretationOverlay | None = None
    manual: InterpretationOverlay | None = None
    dismissed_preset_ids: set[str] | None = None

    def __post_init__(self) -> None:
        if self.dismissed_preset_ids is None:
            self.dismissed_preset_ids = set()


@dataclass(frozen=True, slots=True)
class ResolvedInterpretation:
    domain_id: str
    name: str
    vocabulary: str
    member_polyhedron_ids: tuple[str, ...]
    role_overrides: tuple[tuple[int, str], ...]
    pending_bond_changes: tuple[PeriodicBondChange, ...]
    provenance: str
    preset_id: str | None = None


def _state(document) -> DocumentKnowledgeState:
    current = getattr(document, "knowledge_state", None)
    if isinstance(current, DocumentKnowledgeState):
        return current
    current = DocumentKnowledgeState()
    document.knowledge_state = current
    return current


def _domain(document, domain_id: str):
    try:
        return next(
            item
            for item in document.hierarchy.structural_domains
            if item.id == domain_id
        )
    except StopIteration as error:
        raise KeyError(domain_id) from error


def _automatic(document, domain_id: str) -> ResolvedInterpretation:
    domain = _domain(document, domain_id)
    assignment = next(
        (
            item
            for item in getattr(document.structural_analysis, "nomenclature", ())
            if item.domain_id == domain_id
        ),
        None,
    )
    return ResolvedInterpretation(
        domain_id=domain_id,
        name=(assignment.descriptor if assignment is not None else domain.classification),
        vocabulary=(assignment.vocabulary if assignment is not None else "generic"),
        member_polyhedron_ids=tuple(domain.polyhedron_ids),
        role_overrides=(),
        pending_bond_changes=(),
        provenance="automatic",
    )


def _apply(
    automatic: ResolvedInterpretation,
    overlay: InterpretationOverlay,
) -> ResolvedInterpretation:
    changes = overlay.changes
    members = changes.member_polyhedron_ids or automatic.member_polyhedron_ids
    return ResolvedInterpretation(
        domain_id=automatic.domain_id,
        name=changes.name or automatic.name,
        vocabulary=changes.vocabulary or automatic.vocabulary,
        member_polyhedron_ids=tuple(members),
        role_overrides=changes.role_overrides,
        pending_bond_changes=changes.bond_additions + changes.bond_removals,
        provenance=overlay.provenance,
        preset_id=overlay.preset_id,
    )


def resolve_interpretation(document, domain_id: str) -> ResolvedInterpretation:
    automatic = _automatic(document, domain_id)
    state = _state(document)
    if state.manual is not None and state.manual.domain_id == domain_id:
        return _apply(automatic, state.manual)
    if state.accepted is not None and state.accepted.domain_id == domain_id:
        return _apply(automatic, state.accepted)
    return automatic


def accept_preset(document, preset: KnowledgePreset, *, domain_id: str) -> None:
    domain = _domain(document, domain_id)
    if preset.scope == "local" and preset.source_identity != document.content_identity():
        raise ValueError("local preset belongs to a different structure snapshot")
    changes = preset.changes
    if preset.scope == "reusable":
        changes = InterpretationChanges(
            name=changes.name,
            vocabulary=changes.vocabulary,
            member_polyhedron_ids=tuple(domain.polyhedron_ids),
        )
    elif not changes.member_polyhedron_ids:
        changes = InterpretationChanges(
            name=changes.name,
            vocabulary=changes.vocabulary,
            member_polyhedron_ids=tuple(domain.polyhedron_ids),
            role_overrides=changes.role_overrides,
            bond_additions=changes.bond_additions,
            bond_removals=changes.bond_removals,
        )
    state = _state(document)
    state.accepted = InterpretationOverlay(
        domain_id,
        changes,
        "user preset",
        preset.id,
    )


def set_manual_changes(
    document,
    domain_id: str,
    changes: InterpretationChanges,
) -> None:
    _domain(document, domain_id)
    state = _state(document)
    state.manual = InterpretationOverlay(domain_id, changes, "manual")


def remove_overlay(document) -> None:
    document.knowledge_state = DocumentKnowledgeState()


def _without_bonds(overlay: InterpretationOverlay | None) -> InterpretationOverlay | None:
    if overlay is None:
        return None
    changes = overlay.changes
    return replace(
        overlay,
        changes=replace(changes, bond_additions=(), bond_removals=()),
    )


def _default_recompute(document, additions, removals):
    from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
    from crystal_viewer.analysis.inorganic_topology import build_inorganic_topology
    from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph
    from crystal_viewer.analysis.structural_cache import cached_analyze_structure

    current_settings = document.structural_analysis.settings
    bond_settings = replace(
        current_settings.bond_settings,
        confirmed_additions=tuple(current_settings.bond_settings.confirmed_additions) + additions,
        confirmed_removals=tuple(current_settings.bond_settings.confirmed_removals) + removals,
    )
    settings = replace(current_settings, bond_settings=bond_settings)
    analysis = cached_analyze_structure(document.structure, settings)
    hierarchy = HierarchyAnalyzer().analyze(
        document.structure,
        structural_analysis=analysis,
    )
    return (
        analysis,
        hierarchy,
        PeriodicPolyhedronGraph.from_hierarchy(hierarchy),
        build_inorganic_topology(
            document.structure,
            hierarchy,
            analysis.polyhedron_roles,
        ),
    )


def confirm_bond_changes(
    document,
    *,
    recompute: Callable | None = None,
) -> None:
    state = _state(document)
    overlay = state.manual or state.accepted
    if overlay is None:
        return
    changes = overlay.changes
    additions = tuple(
        (item.first, item.second, item.image) for item in changes.bond_additions
    )
    removals = tuple(
        (item.first, item.second, item.image) for item in changes.bond_removals
    )
    if not additions and not removals:
        return
    site_count = len(document.structure.sites)
    if any(
        first >= site_count or second >= site_count
        for first, second, _image in additions + removals
    ):
        raise ValueError("bond change references a site outside the structure")
    calculate = recompute or _default_recompute
    analysis, hierarchy, periodic_graph, inorganic_topology = calculate(
        document, additions, removals
    )

    document.structural_analysis = analysis
    document.hierarchy = hierarchy
    document.periodic_graph = periodic_graph
    document.inorganic_topology = inorganic_topology
    for attribute in (
        "descriptor_cache",
        "comparison_cache",
        "morphology_cache",
        "scene_cache",
    ):
        cache = getattr(document, attribute, None)
        if cache is not None:
            cache.clear()
    state.accepted = _without_bonds(state.accepted)
    state.manual = _without_bonds(state.manual)


__all__ = [
    "DocumentKnowledgeState",
    "InterpretationOverlay",
    "ResolvedInterpretation",
    "accept_preset",
    "confirm_bond_changes",
    "remove_overlay",
    "resolve_interpretation",
    "set_manual_changes",
]
