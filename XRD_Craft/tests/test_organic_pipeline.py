from __future__ import annotations

from crystal_viewer.analysis.organic.pipeline import (
    OrganicAnalysisStage,
    iter_analyze_organic,
)
from crystal_viewer.analysis.structure_profile import ResolvedProfile
from crystal_viewer.analysis.structure_profile import ProfileDecision
from crystal_viewer.analysis.organic.model import BondLayerReport, ChemicalEdge, ChemicalEdgeKind
from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult
from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _finite_organic_structure() -> CrystalStructure:
    sites = [
        AtomSite("C1", "C", (0.10, 0.50, 0.50)),
        AtomSite("C2", "C", (0.24, 0.50, 0.50)),
        AtomSite("O1", "O", (0.38, 0.50, 0.50)),
    ]
    return CrystalStructure("finite organic", UnitCell(10, 10, 10), sites, sites)


def test_organic_pipeline_emits_useful_dependency_order() -> None:
    bundles = tuple(
        iter_analyze_organic(
            _finite_organic_structure(),
            StructuralAnalysisSettings(),
        )
    )

    assert [bundle.stage for bundle in bundles] == [
        OrganicAnalysisStage.BONDS_PROFILE,
        OrganicAnalysisStage.COMPONENTS,
        OrganicAnalysisStage.CONTACTS,
        OrganicAnalysisStage.PACKING,
    ]
    assert bundles[0].report.profile.resolved is ResolvedProfile.MOLECULAR
    assert bundles[0].report.components is None
    assert bundles[1].report.components is not None
    assert bundles[1].report.contacts is None
    assert bundles[2].report.contacts is not None
    assert bundles[2].report.packing is None
    assert bundles[3].report.packing is not None
    assert bundles[3].report.complete


def test_pipeline_reuses_one_immutable_bond_and_component_result() -> None:
    bundles = tuple(iter_analyze_organic(_finite_organic_structure()))

    assert bundles[0].report.bonds is bundles[1].report.bonds
    assert bundles[1].report.bonds is bundles[2].report.bonds
    assert bundles[1].report.components is bundles[2].report.components
    assert bundles[2].report.components is bundles[3].report.components


def test_reticular_profile_adds_one_final_network_stage() -> None:
    sites = [
        AtomSite("Zn1", "Zn", (0.1, 0.5, 0.5)),
        AtomSite("C1", "C", (0.3, 0.5, 0.5)),
        AtomSite("C2", "C", (0.7, 0.5, 0.5)),
        AtomSite("Zn2", "Zn", (0.9, 0.5, 0.5)),
    ]
    structure = CrystalStructure("reticular", UnitCell(10, 10, 10), sites, sites)
    covalent = ChemicalEdge("cc", 1, 2, (0, 0, 0), 1.4, ChemicalEdgeKind.COVALENT, 1.0, "test")
    coordination = (
        ChemicalEdge("zc1", 0, 1, (0, 0, 0), 2.0, ChemicalEdgeKind.COORDINATION, 1.0, "test"),
        ChemicalEdge("zc2", 3, 2, (1, 0, 0), 2.0, ChemicalEdgeKind.COORDINATION, 1.0, "test"),
    )
    layers = BondLayerReport((covalent,), coordination, (), True)
    profile = ProfileDecision(ResolvedProfile.RETICULAR, 1.0, ("test reticular profile",))

    bundles = tuple(
        iter_analyze_organic(
            structure,
            periodic_bonds=PeriodicBondResult((), True),
            layers=layers,
            profile=profile,
        )
    )

    assert bundles[-1].stage is OrganicAnalysisStage.RETICULAR
    assert bundles[-1].report.reticular is not None
    assert bundles[-2].report.reticular is None
