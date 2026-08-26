from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from crystal_viewer.analysis.hierarchy import HierarchyLevel, HierarchyReport
from crystal_viewer.analysis.inorganic_topology import (
    InorganicTopologyReport,
    build_inorganic_topology,
)
from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph
from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult
from crystal_viewer.analysis.progressive_analysis import AnalysisSnapshot, AnalysisStage
from crystal_viewer.analysis.organic.pipeline import (
    OrganicAnalysisBundle,
    OrganicAnalysisReport,
)
from crystal_viewer.analysis.structure_profile import ProfileDecision, RequestedProfile
from crystal_viewer.analysis.structural_analysis import StructuralAnalysis
from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class DocumentWarning:
    code: str
    message: str
    severity: str = "warning"


@dataclass(slots=True)
class VisualizationState:
    level: HierarchyLevel = HierarchyLevel.SITES
    hidden_atom_indices: set[int] = field(default_factory=set)
    hidden_bond_orbits: set[str] = field(default_factory=set)
    hidden_bond_families: set[tuple[str, str]] = field(default_factory=set)
    hidden_polyhedron_ids: set[str] = field(default_factory=set)
    hidden_unit_ids: set[str] = field(default_factory=set)
    hidden_block_ids: set[str] = field(default_factory=set)
    hidden_connector_ids: set[str] = field(default_factory=set)
    hidden_topology_family_ids: set[str] = field(default_factory=set)
    atom_orbit_colors: dict[str, str] = field(default_factory=dict)
    polyhedron_orbit_colors: dict[str, str] = field(default_factory=dict)
    shown_unit_ids: set[str] = field(default_factory=set)
    shown_block_ids: set[str] = field(default_factory=set)
    unit_colors: dict[str, str] = field(default_factory=dict)
    block_colors: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class StructureDocument:
    id: str
    structure: CrystalStructure
    hierarchy: HierarchyReport
    warnings: tuple[DocumentWarning, ...]
    periodic_graph: PeriodicPolyhedronGraph | None = None
    structural_analysis: StructuralAnalysis | None = None
    inorganic_topology: InorganicTopologyReport | None = None
    periodic_bonds: PeriodicBondResult | None = None
    requested_profile: RequestedProfile = RequestedProfile.AUTO
    profile_decision: ProfileDecision | None = None
    organic_analysis: OrganicAnalysisReport | None = None
    analysis_stage: str = AnalysisStage.TOPOLOGY.value
    visual: VisualizationState = field(default_factory=VisualizationState)
    descriptor_cache: dict[tuple[object, ...], object] = field(default_factory=dict)
    comparison_cache: dict[tuple[object, ...], object] = field(default_factory=dict)
    morphology_cache: dict[tuple[object, ...], object] = field(default_factory=dict)
    morphology_state: object | None = None
    knowledge_state: object | None = None
    scene_cache: dict[tuple[object, ...], object] = field(default_factory=dict)

    def content_identity(self) -> str:
        """Return a deterministic identity for the current analysis snapshot."""
        payload = (
            self.structure.cell,
            tuple(self.structure.asymmetric_sites),
            tuple(self.structure.sites),
            tuple(self.structure.symmetry_operations),
            self.structure.formula,
            self.structure.space_group,
            tuple(self.hierarchy.polyhedra),
            tuple(self.hierarchy.polyhedron_connections),
            tuple(self.hierarchy.structural_units),
            tuple(self.hierarchy.structural_domains),
            tuple(self.hierarchy.blocks),
            tuple(self.hierarchy.connectors),
            self.structural_analysis,
            self.inorganic_topology,
            self.profile_decision,
            self.organic_analysis,
        )
        return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()

    def scene_data(
        self,
        repeat: tuple[int, int, int] = (1, 1, 1),
        bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None = None,
        bond_tolerance: float = 1.18,
        include_bonds: bool = True,
        complete_boundary: bool = True,
    ):
        """Return cached immutable display geometry for these render settings."""
        from crystal_viewer.core.scene import build_scene

        normalized_repeat = tuple(int(value) for value in repeat)
        normalized_bounds = (
            tuple((round(float(pair[0]), 6), round(float(pair[1]), 6)) for pair in bounds)
            if bounds is not None
            else tuple((0.0, float(value)) for value in normalized_repeat)
        )
        key = (
            normalized_repeat,
            normalized_bounds,
            round(float(bond_tolerance), 6),
            bool(include_bonds),
            bool(complete_boundary),
        )
        cached = self.scene_cache.get(key)
        if cached is not None:
            return cached
        scene = build_scene(
            self.structure,
            repeat=key[0],
            bounds=key[1],
            bond_tolerance=key[2],
            include_bonds=(
                key[3]
                and not (
                    self.analysis_stage == "parsed" and self.periodic_bonds is None
                )
            ),
            complete_boundary=key[4],
            periodic_bonds=self.periodic_bonds,
        )
        self.scene_cache[key] = scene
        while len(self.scene_cache) > 8:
            self.scene_cache.pop(next(iter(self.scene_cache)))
        return scene

    @classmethod
    def from_preview(cls, structure: CrystalStructure) -> StructureDocument:
        """Create the stable atom-only document used during background analysis."""
        document = cls.from_structure(structure, HierarchyReport())
        document.periodic_graph = None
        document.inorganic_topology = None
        document.analysis_stage = "parsed"
        return document

    def install_analysis_snapshot(self, snapshot: AnalysisSnapshot) -> None:
        """Install one ready analysis stage without replacing presentation state."""
        self.hierarchy = snapshot.hierarchy
        self.periodic_bonds = snapshot.periodic_bonds
        if snapshot.profile_decision is not None:
            self.profile_decision = snapshot.profile_decision
        self.organic_analysis = None
        self.analysis_stage = snapshot.stage.value
        if snapshot.structural_analysis is not None:
            self.structural_analysis = snapshot.structural_analysis
        if snapshot.inorganic_topology is not None:
            self.inorganic_topology = snapshot.inorganic_topology
        self.periodic_graph = PeriodicPolyhedronGraph.from_hierarchy(snapshot.hierarchy)
        self.scene_cache.clear()
        self.descriptor_cache.clear()
        self.comparison_cache.clear()

    def begin_reanalysis(self, requested: RequestedProfile) -> None:
        """Return to the responsive atom preview before another profile branch."""
        self.requested_profile = requested
        self.hierarchy = HierarchyReport()
        self.periodic_graph = None
        self.structural_analysis = None
        self.inorganic_topology = None
        self.periodic_bonds = None
        self.profile_decision = None
        self.organic_analysis = None
        self.analysis_stage = "parsed"
        self.scene_cache.clear()
        self.descriptor_cache.clear()
        self.comparison_cache.clear()

    def install_organic_bundle(self, bundle: OrganicAnalysisBundle) -> None:
        """Install immutable organic analysis without changing source/display state."""
        self.profile_decision = bundle.report.profile
        self.organic_analysis = bundle.report
        self.periodic_bonds = bundle.report.periodic_bonds
        self.analysis_stage = bundle.stage.value
        self.inorganic_topology = None
        self.scene_cache.clear()
        self.descriptor_cache.clear()
        self.comparison_cache.clear()

    @classmethod
    def from_structure(
        cls,
        structure: CrystalStructure,
        hierarchy: HierarchyReport,
        structural_analysis: StructuralAnalysis | None = None,
    ) -> StructureDocument:
        warnings = tuple(
            DocumentWarning(
                "occupancy-out-of-range",
                f"{site.label}: reported occupancy {site.reported_occupancy:g} is outside 0–1.",
            )
            for site in structure.asymmetric_sites
            if site.occupancy_warning
        )
        identity = str(structure.source_path or structure.name)
        document_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        return cls(
            id=document_id,
            structure=structure,
            hierarchy=hierarchy,
            warnings=warnings,
            periodic_graph=PeriodicPolyhedronGraph.from_hierarchy(hierarchy),
            structural_analysis=structural_analysis,
            periodic_bonds=(
                getattr(structural_analysis, "periodic_bonds", None)
                if structural_analysis is not None
                else None
            ),
            inorganic_topology=build_inorganic_topology(
                structure,
                hierarchy,
                getattr(structural_analysis, "polyhedron_roles", ()),
            ),
        )


def load_document(path: str | Path) -> StructureDocument:
    """Load a CIF and calculate its hierarchy once for collection/comparison use."""
    from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
    from crystal_viewer.analysis.structural_cache import cached_analyze_structure
    from crystal_viewer.core.cif import load_cif

    structure = load_cif(Path(path))
    structural_analysis = cached_analyze_structure(structure)
    hierarchy = HierarchyAnalyzer().analyze(structure, structural_analysis)
    return StructureDocument.from_structure(structure, hierarchy, structural_analysis)
