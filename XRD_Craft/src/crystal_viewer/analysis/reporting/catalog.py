from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TableDefinition:
    id: str
    title: str
    group: str
    stage: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class ReportPreset:
    id: str
    title: str
    table_ids: tuple[str, ...]


TABLE_DEFINITIONS = (
    TableDefinition("crystal_data", "Crystal data", "Crystal and refinement", "A"),
    TableDefinition("refinement", "Data collection and refinement", "Crystal and refinement", "A"),
    TableDefinition("atomic_sites", "Atomic sites", "Atoms and displacement", "A"),
    TableDefinition("adp", "Atomic displacement parameters", "Atoms and displacement", "A"),
    TableDefinition("bond_lengths", "Bond lengths", "Geometry", "A"),
    TableDefinition("bond_angles", "Bond angles", "Geometry", "A"),
    TableDefinition("torsion_angles", "Torsion angles", "Geometry", "D"),
    TableDefinition("contacts", "Non-bonded contacts", "Geometry", "D"),
    TableDefinition("hydrogen_bonds", "Hydrogen bonds", "Geometry", "D"),
    TableDefinition("coordination", "Coordination environments", "Inorganic geometry", "B"),
    TableDefinition("polyhedra", "Polyhedral metrics", "Inorganic geometry", "B"),
    TableDefinition("connectivity", "Polyhedral connectivity", "Inorganic geometry", "B"),
    TableDefinition("bond_valence", "Bond-valence analysis", "Inorganic geometry", "B"),
    TableDefinition("structural_units", "Structural units", "Hierarchy and mechanics", "C"),
    TableDefinition("rigid_blocks", "Rigid blocks", "Hierarchy and mechanics", "C"),
    TableDefinition("connectors", "Connectors and pivot candidates", "Hierarchy and mechanics", "C"),
    TableDefinition("degrees_of_freedom", "Degrees of freedom", "Hierarchy and mechanics", "C"),
)

_TABLES_BY_ID = {definition.id: definition for definition in TABLE_DEFINITIONS}

STANDARD = (
    "crystal_data",
    "refinement",
    "atomic_sites",
    "adp",
    "bond_lengths",
    "bond_angles",
)
INORGANIC = STANDARD + ("coordination", "polyhedra", "connectivity", "bond_valence")
MECHANICS = ("structural_units", "rigid_blocks", "connectors", "degrees_of_freedom")
FULL = tuple(definition.id for definition in TABLE_DEFINITIONS)

REPORT_PRESETS = (
    ReportPreset("standard", "Standard Structure Paper", STANDARD),
    ReportPreset("inorganic", "Inorganic / Mineral Structure", INORGANIC),
    ReportPreset("mechanics", "CRAFT Mechanics", MECHANICS),
    ReportPreset("full", "Full Report", FULL),
    ReportPreset("custom", "Custom", ()),
)

_PRESETS_BY_ID = {preset.id: preset for preset in REPORT_PRESETS}


def table_definition(table_id: str) -> TableDefinition:
    try:
        return _TABLES_BY_ID[table_id]
    except KeyError as error:
        raise KeyError(f"Unknown report table: {table_id}") from error


def report_preset(preset_id: str) -> ReportPreset:
    try:
        return _PRESETS_BY_ID[preset_id]
    except KeyError as error:
        raise KeyError(f"Unknown report preset: {preset_id}") from error
