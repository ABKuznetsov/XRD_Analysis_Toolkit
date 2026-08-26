"""Structure hierarchy and motion analysis."""

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer, HierarchyReport
from crystal_viewer.analysis.passport import StructuralPassport, build_structural_passport
from crystal_viewer.analysis.periodic_graph import (
    PeriodicComponent,
    PeriodicEdge,
    PeriodicPolyhedronGraph,
)
from crystal_viewer.analysis.reporting import StructureReport, report_preset, table_definition
from crystal_viewer.analysis.series import SeriesMechanicsReport, analyze_structure_series

__all__ = [
    "HierarchyAnalyzer",
    "HierarchyReport",
    "PeriodicComponent",
    "PeriodicEdge",
    "PeriodicPolyhedronGraph",
    "SeriesMechanicsReport",
    "StructuralPassport",
    "StructureReport",
    "analyze_structure_series",
    "build_structural_passport",
    "report_preset",
    "table_definition",
]
