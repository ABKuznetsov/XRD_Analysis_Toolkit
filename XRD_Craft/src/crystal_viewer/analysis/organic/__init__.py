"""Cross-platform organic and metal-organic structure analysis."""

from crystal_viewer.analysis.organic.bond_layers import build_bond_layers
from crystal_viewer.analysis.organic.cache import OrganicAnalysisCache, organic_cache_key
from crystal_viewer.analysis.organic.model import (
    BondLayerReport,
    ChemicalEdge,
    ChemicalEdgeKind,
)
from crystal_viewer.analysis.organic.pipeline import (
    OrganicAnalysisBundle,
    OrganicAnalysisReport,
    OrganicAnalysisStage,
    iter_analyze_organic,
)
from crystal_viewer.analysis.organic.packing import (
    PackingAssembly,
    PackingReport,
    PackingSettings,
    VoidRegion,
    build_packing,
)
from crystal_viewer.analysis.organic.reticular import (
    ReticularReport,
    build_reticular_network,
)

__all__ = [
    "BondLayerReport",
    "ChemicalEdge",
    "ChemicalEdgeKind",
    "OrganicAnalysisBundle",
    "OrganicAnalysisCache",
    "OrganicAnalysisReport",
    "OrganicAnalysisStage",
    "PackingAssembly",
    "PackingReport",
    "PackingSettings",
    "ReticularReport",
    "VoidRegion",
    "build_bond_layers",
    "build_packing",
    "build_reticular_network",
    "iter_analyze_organic",
    "organic_cache_key",
]
