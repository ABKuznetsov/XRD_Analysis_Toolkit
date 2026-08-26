from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterator

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.analysis.inorganic_topology import build_inorganic_topology
from crystal_viewer.analysis.progressive_analysis import (
    AnalysisSnapshot,
    AnalysisStage,
    iter_analyze_document,
    iter_analyze_structure,
)
from crystal_viewer.analysis.organic.cache import OrganicAnalysisCache, organic_cache_key
from crystal_viewer.analysis.organic.pipeline import (
    OrganicAnalysisBundle,
    OrganicAnalysisStage,
)
from crystal_viewer.analysis.organic.bond_layers import build_bond_layers
from crystal_viewer.analysis.structure_profile import (
    ProfileSettings,
    RequestedProfile,
    ResolvedProfile,
    resolve_structure_profile,
)
from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings
from crystal_viewer.analysis.structural_cache import (
    StructuralAnalysisCache,
    structural_cache_key,
)
from crystal_viewer.core.app_paths import crystal_blocks_data_dir
from crystal_viewer.core.model import CrystalStructure
from crystal_viewer.core.structure_io import load_structure_files


class LoadStage(StrEnum):
    PARSED = "parsed"
    BONDS = "bonds"
    POLYHEDRA = "polyhedra"
    UNITS = "units"
    TOPOLOGY = "topology"
    BONDS_PROFILE = "bonds/profile"
    COMPONENTS = "components"
    CONTACTS = "contacts"
    PACKING = "packing"
    RETICULAR = "reticular"


@dataclass(frozen=True, slots=True)
class StructureLoadUpdate:
    stage: LoadStage
    source_path: Path
    structure_index: int
    structure_count: int
    structure: CrystalStructure
    snapshot: AnalysisSnapshot | None = None
    organic_bundle: OrganicAnalysisBundle | None = None


def _cached_snapshot(structure, analysis) -> AnalysisSnapshot:
    hierarchy = HierarchyAnalyzer().analyze(structure, analysis)
    topology = build_inorganic_topology(
        structure,
        hierarchy,
        analysis.polyhedron_roles,
    )
    layers = build_bond_layers(structure, analysis.periodic_bonds)
    profile = resolve_structure_profile(
        structure,
        analysis.periodic_bonds,
        layers,
        requested=analysis.settings.profile.requested,
    )
    return AnalysisSnapshot(
        AnalysisStage.TOPOLOGY,
        analysis.periodic_bonds,
        analysis.coordination_environments,
        analysis.polyhedron_roles,
        hierarchy,
        analysis,
        topology,
        profile,
    )


def iter_reanalysis_updates(
    structure: CrystalStructure,
    source_path: str | Path,
    requested: RequestedProfile,
) -> Iterator[StructureLoadUpdate]:
    """Reanalyze an already parsed structure without blocking or reparsing it."""
    source = Path(source_path).expanduser().resolve()
    settings = StructuralAnalysisSettings(profile=ProfileSettings(requested))
    for result in iter_analyze_document(structure, settings):
        yield StructureLoadUpdate(
            LoadStage(result.stage.value),
            source,
            0,
            1,
            structure,
            result if isinstance(result, AnalysisSnapshot) else None,
            result if isinstance(result, OrganicAnalysisBundle) else None,
        )


def iter_load_updates(
    path: str | Path,
    *,
    settings: StructuralAnalysisSettings | None = None,
    cache: StructuralAnalysisCache | None = None,
    organic_cache: OrganicAnalysisCache | None = None,
) -> Iterator[StructureLoadUpdate]:
    source = Path(path).expanduser().resolve()
    settings = settings or StructuralAnalysisSettings()
    settings.validate()
    cache = cache or StructuralAnalysisCache(
        crystal_blocks_data_dir() / "cache" / "structural"
    )
    organic_cache = organic_cache or OrganicAnalysisCache(
        crystal_blocks_data_dir() / "cache" / "organic"
    )
    structures = load_structure_files(source)
    total = len(structures)
    for index, structure in enumerate(structures):
        yield StructureLoadUpdate(
            LoadStage.PARSED,
            source,
            index,
            total,
            structure,
        )
    for index, structure in enumerate(structures):
        key = structural_cache_key(structure, settings)
        organic_key = organic_cache_key(structure, settings)
        try:
            cached_organic = organic_cache.get(organic_key)
        except OSError:
            cached_organic = None
        if cached_organic is not None:
            stage = (
                OrganicAnalysisStage.RETICULAR
                if cached_organic.profile.resolved is ResolvedProfile.RETICULAR
                else OrganicAnalysisStage.PACKING
            )
            yield StructureLoadUpdate(
                LoadStage(stage.value),
                source,
                index,
                total,
                structure,
                organic_bundle=OrganicAnalysisBundle(stage, cached_organic),
            )
            continue
        try:
            cached = cache.get(key)
        except OSError:
            cached = None
        if cached is not None:
            snapshot = _cached_snapshot(structure, cached)
            yield StructureLoadUpdate(
                LoadStage.TOPOLOGY,
                source,
                index,
                total,
                structure,
                snapshot,
            )
            continue
        for result in iter_analyze_document(structure, settings):
            snapshot = result if isinstance(result, AnalysisSnapshot) else None
            organic_bundle = result if isinstance(result, OrganicAnalysisBundle) else None
            yield StructureLoadUpdate(
                LoadStage(result.stage.value),
                source,
                index,
                total,
                structure,
                snapshot,
                organic_bundle,
            )
            if snapshot is not None and snapshot.structural_analysis is not None:
                try:
                    cache.put(key, snapshot.structural_analysis)
                except OSError:
                    pass
            final_organic_stage = (
                organic_bundle is not None
                and organic_bundle.report.complete
                and (
                    organic_bundle.stage is OrganicAnalysisStage.RETICULAR
                    or (
                        organic_bundle.stage is OrganicAnalysisStage.PACKING
                        and organic_bundle.report.profile.resolved
                        is not ResolvedProfile.RETICULAR
                    )
                )
            )
            if final_organic_stage and organic_bundle is not None:
                try:
                    organic_cache.put(organic_key, organic_bundle.report)
                except OSError:
                    pass


__all__ = [
    "LoadStage",
    "StructureLoadUpdate",
    "iter_load_updates",
    "iter_reanalysis_updates",
]
