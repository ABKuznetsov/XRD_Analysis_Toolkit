from __future__ import annotations

from pathlib import Path

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.analysis.progressive_analysis import (
    AnalysisStage,
    iter_analyze_document,
    iter_analyze_structure,
)
from crystal_viewer.analysis.organic.pipeline import OrganicAnalysisStage
from crystal_viewer.analysis.structure_profile import ResolvedProfile
from crystal_viewer.analysis.structural_analysis import (
    StructuralAnalysisSettings,
    analyze_structure,
)
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


DATA = Path(__file__).parent / "data" / "structures" / "lithium_triborate.cif"


def test_progressive_analysis_emits_dependency_order_and_honest_partial_hierarchies() -> None:
    structure = load_cif(DATA)

    snapshots = tuple(iter_analyze_structure(structure))

    assert [item.stage for item in snapshots] == [
        AnalysisStage.BONDS,
        AnalysisStage.POLYHEDRA,
        AnalysisStage.UNITS,
        AnalysisStage.TOPOLOGY,
    ]
    assert snapshots[0].hierarchy.polyhedra == []
    assert snapshots[1].hierarchy.polyhedra
    assert snapshots[1].hierarchy.structural_units == []
    assert snapshots[2].hierarchy.structural_units
    assert snapshots[2].structural_analysis is None
    assert snapshots[3].structural_analysis is not None
    assert snapshots[3].inorganic_topology is not None


def test_progressive_final_result_equals_public_synchronous_analysis() -> None:
    structure = load_cif(DATA)
    # Keep this equivalence test independent of host load: the production
    # five-second ChemEnv budget intentionally records timing provenance.
    settings = StructuralAnalysisSettings(maximum_seconds=120.0)

    final = tuple(iter_analyze_structure(structure, settings))[-1]
    synchronous = analyze_structure(structure, settings)

    assert final.structural_analysis == synchronous
    assert final.hierarchy == HierarchyAnalyzer().analyze(structure, synchronous)


def test_document_pipeline_keeps_inorganic_profile_evidence_on_snapshots() -> None:
    structure = load_cif(DATA)

    snapshots = tuple(iter_analyze_document(structure))

    assert snapshots[-1].profile_decision is not None
    assert snapshots[-1].profile_decision.resolved is ResolvedProfile.INORGANIC


def test_document_pipeline_branches_to_incremental_organic_reports() -> None:
    sites = [
        AtomSite("C1", "C", (0.10, 0.50, 0.50)),
        AtomSite("C2", "C", (0.24, 0.50, 0.50)),
        AtomSite("O1", "O", (0.38, 0.50, 0.50)),
    ]
    structure = CrystalStructure("organic", UnitCell(10, 10, 10), sites, sites)

    updates = tuple(iter_analyze_document(structure))

    assert [update.stage for update in updates] == [
        OrganicAnalysisStage.BONDS_PROFILE,
        OrganicAnalysisStage.COMPONENTS,
        OrganicAnalysisStage.CONTACTS,
        OrganicAnalysisStage.PACKING,
    ]
    assert updates[-1].report.complete
