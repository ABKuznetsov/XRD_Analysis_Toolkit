from __future__ import annotations

from collections.abc import Callable, Iterable

from crystal_viewer import __version__
from crystal_viewer.analysis.reporting.catalog import TABLE_DEFINITIONS, table_definition
from crystal_viewer.analysis.reporting.crystal import (
    build_adp_table,
    build_atomic_sites_table,
    build_crystal_data_table,
    build_refinement_table,
)
from crystal_viewer.analysis.reporting.model import (
    Availability,
    ReportSettings,
    ReportTable,
    StructureReport,
)
from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.analysis.reporting.geometry import GeometrySettings, build_angle_table, build_bond_table
from crystal_viewer.core.model import CrystalStructure


TableBuilder = Callable[[CrystalStructure], ReportTable]

BUILDERS: dict[str, TableBuilder] = {
    "crystal_data": build_crystal_data_table,
    "refinement": build_refinement_table,
    "atomic_sites": build_atomic_sites_table,
    "adp": build_adp_table,
}


class StructureReportBuilder:
    def __init__(
        self,
        structure: CrystalStructure,
        settings: ReportSettings | None = None,
    ) -> None:
        self.structure = structure
        self.settings = settings or ReportSettings()
        self._cache: dict[str, ReportTable] = {}

    def table(self, table_id: str) -> ReportTable:
        if table_id in self._cache:
            return self._cache[table_id]
        definition = table_definition(table_id)
        builder = BUILDERS.get(table_id)
        if table_id in {"bond_lengths", "bond_angles"}:
            hierarchy = HierarchyAnalyzer(bond_tolerance=self.settings.bond_tolerance).analyze(
                self.structure
            )
            geometry_settings = GeometrySettings(
                distance_tolerance=self.settings.distance_group_tolerance,
                angle_tolerance=self.settings.angle_group_tolerance,
            )
            table = (
                build_bond_table(self.structure, hierarchy, geometry_settings)
                if table_id == "bond_lengths"
                else build_angle_table(self.structure, hierarchy, geometry_settings)
            )
        elif builder is None:
            table = ReportTable(
                id=definition.id,
                title=definition.title,
                columns=(),
                rows=(),
                availability=Availability.UNAVAILABLE,
                unavailable_reason=f"Available in Stage {definition.stage}: {definition.title}",
            )
        else:
            table = builder(self.structure)
        self._cache[table_id] = table
        return table

    def build(self, table_ids: Iterable[str] | None = None) -> StructureReport:
        selected = tuple(table_ids) if table_ids is not None else tuple(
            definition.id for definition in TABLE_DEFINITIONS
        )
        tables = {table_id: self.table(table_id) for table_id in selected}
        return StructureReport(
            structure_name=self.structure.name,
            source_path=str(self.structure.source_path or ""),
            settings=self.settings,
            tables=tables,
            generator_version=__version__,
        )
