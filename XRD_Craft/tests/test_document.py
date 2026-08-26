from __future__ import annotations

import pytest

from crystal_viewer.analysis.comparison import cached_compare, motif_cache_key
from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.analysis.motif_comparison import MatchLimits, MotifComparisonReport
from crystal_viewer.analysis.motif_graph import LatticeImageSearchError
from crystal_viewer.analysis.progressive_analysis import iter_analyze_structure
from crystal_viewer.analysis.organic.pipeline import iter_analyze_organic
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _structure(occupancy: float = 1.0) -> CrystalStructure:
    site = AtomSite("O00M", "O", (0.0, 0.0, 0.0), occupancy=occupancy)
    return CrystalStructure(
        name="document-test",
        cell=UnitCell(5.0, 5.0, 5.0),
        asymmetric_sites=[site],
        sites=[site],
    )


def test_document_collects_occupancy_warning() -> None:
    structure = _structure(1.024)
    document = StructureDocument.from_structure(
        structure,
        HierarchyAnalyzer().analyze(structure),
    )

    assert document.warnings[0].code == "occupancy-out-of-range"
    assert "O00M" in document.warnings[0].message
    assert "1.024" in document.warnings[0].message


def test_visual_state_is_independent_from_structure() -> None:
    structure = _structure()
    document = StructureDocument.from_structure(
        structure,
        HierarchyAnalyzer().analyze(structure),
    )

    document.visual.hidden_polyhedron_ids.add("P1")

    assert document.visual.hidden_polyhedron_ids == {"P1"}
    assert len(document.structure.sites) == 1
    assert document.structure.sites[0].label == "O00M"


def test_document_caches_periodic_polyhedron_graph() -> None:
    structure = _structure()
    hierarchy = HierarchyAnalyzer().analyze(structure)

    document = StructureDocument.from_structure(structure, hierarchy)

    assert document.periodic_graph is not None
    assert document.periodic_graph.graph.number_of_nodes() == len(hierarchy.polyhedra)


def test_document_caches_scene_by_render_geometry_settings(monkeypatch) -> None:
    structure = _structure()
    document = StructureDocument.from_structure(
        structure,
        HierarchyAnalyzer().analyze(structure),
    )
    calls = []

    def fake_build_scene(_structure, **settings):
        scene = object()
        calls.append((settings, scene))
        return scene

    monkeypatch.setattr("crystal_viewer.core.scene.build_scene", fake_build_scene)

    first = document.scene_data(repeat=(1, 1, 1), bond_tolerance=1.18)
    again = document.scene_data(repeat=(1, 1, 1), bond_tolerance=1.18)
    larger = document.scene_data(repeat=(2, 1, 1), bond_tolerance=1.18)

    assert again is first
    assert larger is not first
    assert len(calls) == 2


def test_preview_scene_has_atoms_without_inferred_bonds_and_keeps_visual_state() -> None:
    structure = _structure()
    document = StructureDocument.from_preview(structure)
    document.visual.atom_orbit_colors["O00M"] = "#123456"

    preview = document.scene_data()

    assert preview.atoms
    assert preview.bonds == []
    snapshot = next(iter(iter_analyze_structure(structure)))
    original_visual = document.visual
    document.install_analysis_snapshot(snapshot)
    assert document.visual is original_visual
    assert document.visual.atom_orbit_colors == {"O00M": "#123456"}
    assert document.analysis_stage == "bonds"


def test_installing_organic_stage_preserves_structure_and_visual_state() -> None:
    sites = [
        AtomSite("C1", "C", (0.10, 0.50, 0.50)),
        AtomSite("C2", "C", (0.24, 0.50, 0.50)),
        AtomSite("O1", "O", (0.38, 0.50, 0.50)),
    ]
    structure = CrystalStructure("organic", UnitCell(10, 10, 10), sites, sites)
    document = StructureDocument.from_preview(structure)
    document.visual.atom_orbit_colors["C1"] = "#112233"
    visual = document.visual
    bundle = tuple(iter_analyze_organic(structure))[1]

    document.install_organic_bundle(bundle)

    assert document.structure is structure
    assert document.visual is visual
    assert document.organic_analysis is bundle.report
    assert document.profile_decision is bundle.report.profile
    assert document.analysis_stage == "components"


def _motif_report(first: StructureDocument, second: StructureDocument) -> MotifComparisonReport:
    return MotifComparisonReport(
        first_document_id=first.id,
        second_document_id=second.id,
        matches=(),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=False,
        states_explored=0,
    )


def test_same_ordered_pair_reuses_cached_motif_report() -> None:
    first = StructureDocument.from_structure(
        _structure(), HierarchyAnalyzer().analyze(_structure())
    )
    second_structure = _structure()
    second_structure.name = "second"
    second = StructureDocument.from_structure(
        second_structure, HierarchyAnalyzer().analyze(second_structure)
    )
    expected = _motif_report(first, second)
    calls: list[int] = []

    initial = cached_compare(
        first, second, compute=lambda: calls.append(1) or expected
    )
    reused = cached_compare(
        first, second, compute=lambda: calls.append(2) or expected
    )

    assert reused is initial
    assert calls == [1]


def test_motif_cache_key_is_order_sensitive_and_includes_limits() -> None:
    default = MatchLimits()
    constrained = MatchLimits(max_states=1, max_seconds=0.5, max_nodes=8)

    assert motif_cache_key("first", "second", default) != motif_cache_key(
        "second", "first", default
    )
    assert motif_cache_key("first", "second", default) != motif_cache_key(
        "first", "second", constrained
    )


def test_motif_cache_evicts_oldest_report_after_eight_entries() -> None:
    first_structure = _structure()
    first_structure.name = "first"
    first = StructureDocument.from_structure(
        first_structure, HierarchyAnalyzer().analyze(first_structure)
    )
    seconds = []
    for index in range(9):
        structure = _structure()
        structure.name = f"second-{index}"
        seconds.append(
            StructureDocument.from_structure(
                structure, HierarchyAnalyzer().analyze(structure)
            )
        )

    for second in seconds:
        expected = _motif_report(first, second)
        cached_compare(first, second, compute=lambda expected=expected: expected)

    assert len(first.comparison_cache) == 8
    oldest_key = motif_cache_key(
        first.id,
        seconds[0].id,
        MatchLimits(),
        first.content_identity(),
        seconds[0].content_identity(),
    )
    newest_key = motif_cache_key(
        first.id,
        seconds[-1].id,
        MatchLimits(),
        first.content_identity(),
        seconds[-1].content_identity(),
    )
    assert oldest_key not in first.comparison_cache
    assert newest_key in first.comparison_cache


def test_failed_motif_comparison_is_not_cached() -> None:
    first = StructureDocument.from_structure(
        _structure(), HierarchyAnalyzer().analyze(_structure())
    )
    second_structure = _structure()
    second_structure.name = "second"
    second = StructureDocument.from_structure(
        second_structure, HierarchyAnalyzer().analyze(second_structure)
    )
    attempts = 0

    def fail() -> MotifComparisonReport:
        nonlocal attempts
        attempts += 1
        raise LatticeImageSearchError("incomplete graph")

    with pytest.raises(LatticeImageSearchError, match="incomplete graph"):
        cached_compare(first, second, compute=fail)
    with pytest.raises(LatticeImageSearchError, match="incomplete graph"):
        cached_compare(first, second, compute=fail)

    assert attempts == 2
    assert first.comparison_cache == {}


def test_changed_second_content_with_same_document_id_is_recomputed() -> None:
    first_structure = _structure()
    first_structure.name = "first"
    first = StructureDocument.from_structure(
        first_structure, HierarchyAnalyzer().analyze(first_structure)
    )
    original_structure = _structure()
    original_structure.name = "same-source"
    changed_structure = _structure()
    changed_structure.name = "same-source"
    changed_structure.cell = UnitCell(6.0, 5.0, 5.0)
    original = StructureDocument.from_structure(
        original_structure, HierarchyAnalyzer().analyze(original_structure)
    )
    changed = StructureDocument.from_structure(
        changed_structure, HierarchyAnalyzer().analyze(changed_structure)
    )
    calls: list[str] = []

    cached_compare(
        first,
        original,
        compute=lambda: calls.append("original") or _motif_report(first, original),
    )
    cached_compare(
        first,
        changed,
        compute=lambda: calls.append("changed") or _motif_report(first, changed),
    )

    assert original.id == changed.id
    assert calls == ["original", "changed"]


def test_mutating_first_document_content_invalidates_its_cached_report() -> None:
    first_structure = _structure()
    first_structure.name = "first"
    first = StructureDocument.from_structure(
        first_structure, HierarchyAnalyzer().analyze(first_structure)
    )
    second_structure = _structure()
    second_structure.name = "second"
    second = StructureDocument.from_structure(
        second_structure, HierarchyAnalyzer().analyze(second_structure)
    )
    calls: list[int] = []

    cached_compare(
        first,
        second,
        compute=lambda: calls.append(1) or _motif_report(first, second),
    )
    first.structure.cell = UnitCell(6.0, 5.0, 5.0)
    cached_compare(
        first,
        second,
        compute=lambda: calls.append(2) or _motif_report(first, second),
    )

    assert calls == [1, 2]
