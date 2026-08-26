from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from crystal_viewer.analysis.reporting.model import (
    Availability,
    ReportCell,
    ReportTable,
    StructureReport,
)
from crystal_viewer.core.measurement import MeasuredValue


def _require_available(table: ReportTable) -> None:
    if table.availability is Availability.UNAVAILABLE:
        raise ValueError(f"Table '{table.id}' is unavailable: {table.unavailable_reason}")


def export_table_csv(
    table: ReportTable,
    path: str | Path,
    *,
    included_only: bool = True,
) -> Path:
    _require_available(table)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        f"{column.id} [{column.unit}]" if column.unit else column.id
        for column in table.columns
    ]
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", *headers])
        writer.writeheader()
        for row in table.rows:
            if included_only and not row.include_in_publication:
                continue
            record = {"id": row.id}
            for column, header in zip(table.columns, headers, strict=True):
                cell = row.cells.get(column.id)
                record[header] = cell.display if cell is not None else ""
            writer.writerow(record)
    return target


def _cell_data(cell: ReportCell) -> dict[str, object]:
    result: dict[str, object] = {
        "display": cell.display,
        "provenance": cell.provenance.value,
        "source_name": cell.source_name,
        "method_id": cell.method_id,
        "warning": cell.warning,
    }
    if isinstance(cell.value, MeasuredValue):
        result.update(
            {
                "raw": cell.value.raw,
                "value": cell.value.value,
                "su": cell.value.su,
                "unit": cell.value.unit,
                "state": cell.value.state.value,
            }
        )
    else:
        result["value"] = cell.value
    return result


def _table_data(table: ReportTable, included_only: bool) -> dict[str, object]:
    return {
        "id": table.id,
        "title": table.title,
        "availability": table.availability.value,
        "unavailable_reason": table.unavailable_reason,
        "method": table.method,
        "columns": [asdict(column) for column in table.columns],
        "warnings": [asdict(warning) for warning in table.warnings],
        "rows": [
            {
                "id": row.id,
                "include_in_publication": row.include_in_publication,
                "object_refs": list(row.object_refs),
                "expanded_records": list(row.expanded_records),
                "notes": row.notes,
                "cells": {cell_id: _cell_data(cell) for cell_id, cell in row.cells.items()},
            }
            for row in table.rows
            if not included_only or row.include_in_publication
        ],
    }


def export_report_json(
    report: StructureReport,
    path: str | Path,
    *,
    included_only: bool = True,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "structure_name": report.structure_name,
        "source_path": report.source_path,
        "generator_version": report.generator_version,
        "settings": asdict(report.settings),
        "tables": {
            table_id: _table_data(table, included_only)
            for table_id, table in report.tables.items()
        },
    }
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target
