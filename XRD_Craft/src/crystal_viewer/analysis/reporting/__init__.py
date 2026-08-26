"""Typed, UI-independent structural analysis reports."""

from crystal_viewer.analysis.reporting.catalog import (
    REPORT_PRESETS,
    TABLE_DEFINITIONS,
    ReportPreset,
    TableDefinition,
    report_preset,
    table_definition,
)
from crystal_viewer.analysis.reporting.model import (
    Availability,
    Provenance,
    ReportCell,
    ReportColumn,
    ReportRow,
    ReportSettings,
    ReportTable,
    ReportWarning,
    StructureReport,
)
from crystal_viewer.analysis.reporting.builder import StructureReportBuilder
from crystal_viewer.analysis.reporting.export import export_report_json, export_table_csv

__all__ = [
    "Availability",
    "Provenance",
    "REPORT_PRESETS",
    "ReportCell",
    "ReportColumn",
    "ReportPreset",
    "ReportRow",
    "ReportSettings",
    "ReportTable",
    "ReportWarning",
    "StructureReport",
    "StructureReportBuilder",
    "TABLE_DEFINITIONS",
    "TableDefinition",
    "report_preset",
    "table_definition",
    "export_report_json",
    "export_table_csv",
]
