from __future__ import annotations

import csv
import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Mapping

from crystal_viewer.analysis.comparison import ComparisonReport


def _json_value(value):
    if is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def export_comparison_json(
    report: ComparisonReport,
    path: str | Path,
    included_only: bool = True,
) -> Path:
    target = Path(path)
    rows = []
    for row in report.rows:
        if included_only and not row.include_in_report:
            continue
        rows.append(
            {
                "descriptor_id": row.descriptor_id,
                "title": row.title,
                "section": row.section,
                "method_id": row.method_id,
                "focus": _json_value(row.focus),
                "expanded_records": _json_value(row.expanded_records),
                "cells": [
                    {
                        "document_id": cell.document_id,
                        "display": cell.display,
                        "state": cell.state.value,
                        "raw": _json_value(cell.raw),
                        "warning": cell.warning,
                    }
                    for cell in row.cells
                ],
            }
        )
    payload = {
        "documents": list(report.document_ids),
        "document_titles": list(report.document_titles),
        "warnings": list(report.warnings),
        "rows": rows,
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def export_comparison_csv(
    report: ComparisonReport,
    path: str | Path,
    included_only: bool = True,
) -> Path:
    target = Path(path)
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "Characteristic",
                *report.document_titles,
                "Method",
                *(f"{title} state" for title in report.document_titles),
                *(f"{title} warning" for title in report.document_titles),
                "Report warnings",
            )
        )
        for row in report.rows:
            if included_only and not row.include_in_report:
                continue
            writer.writerow(
                (
                    f"{row.section} / {row.title}",
                    *(cell.display for cell in row.cells),
                    row.method_id,
                    *(cell.state.value for cell in row.cells),
                    *(cell.warning for cell in row.cells),
                    "; ".join(report.warnings),
                )
            )
    return target
