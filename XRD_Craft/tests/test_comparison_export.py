from __future__ import annotations

import csv
import json

from crystal_viewer.analysis.comparison import (
    ComparisonCell,
    ComparisonReport,
    ComparisonRow,
    ComparisonState,
    compare_documents,
)
from crystal_viewer.analysis.comparison_export import (
    export_comparison_csv,
    export_comparison_json,
)
from crystal_viewer.analysis.descriptors.model import FocusCommand
from crystal_viewer.analysis.hierarchy import HierarchyLevel
from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.motif_comparison import MotifComparisonReport, MotifMatch
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import CrystalStructure, UnitCell


def _report() -> ComparisonReport:
    return ComparisonReport(
        ("a", "b"),
        ("A", "B"),
        (
            ComparisonRow(
                "cell.a",
                "Cell a",
                "Crystal data",
                (
                    ComparisonCell("a", "5.0", ComparisonState.SIMILAR, 5.0),
                    ComparisonCell("b", "5.1", ComparisonState.MODERATE, 5.1, "estimated"),
                ),
                method_id="cell-v1",
                focus=FocusCommand("isolate", HierarchyLevel.POLYHEDRA, "polyhedron-type", {"center": "Mo"}),
                expanded_records=({"source": "CIF"}, {"source": "CIF"}),
            ),
        ),
        warnings=("source warning",),
    )


def test_comparison_json_contains_methods_warnings_and_raw_values(tmp_path) -> None:
    target = export_comparison_json(_report(), tmp_path / "compare.json")
    data = json.loads(target.read_text(encoding="utf-8"))

    assert data["documents"] == ["a", "b"]
    assert data["rows"][0]["method_id"] == "cell-v1"
    assert data["rows"][0]["cells"][1]["raw"] == 5.1
    assert data["rows"][0]["cells"][1]["warning"] == "estimated"
    assert data["rows"][0]["focus"]["payload"] == {"center": "Mo"}


def test_csv_keeps_structure_columns_before_flat_provenance_columns(tmp_path) -> None:
    target = export_comparison_csv(_report(), tmp_path / "compare.csv")
    header = next(csv.reader(target.open(encoding="utf-8-sig", newline="")))

    assert header[:3] == ["Characteristic", "A", "B"]
    assert header[3:] == [
        "Method",
        "A state",
        "B state",
        "A warning",
        "B warning",
        "Report warnings",
    ]


def test_exports_round_trip_limits_ambiguity_method_and_states(tmp_path) -> None:
    documents = tuple(
        StructureDocument.from_structure(
            CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), [], []),
            HierarchyReport(),
        )
        for name in ("A", "B")
    )
    match = MotifMatch(
        id="M1",
        classification="island",
        periodic_rank=0,
        node_pairs=(("P1", "P1"),),
        edge_pairs=(),
        edge_kinds=(),
        topology_score=0.5,
        geometry_score=1.0,
        chemistry_score=1.0,
        total_score=0.725,
    )
    motif_report = MotifComparisonReport(
        first_document_id=documents[0].id,
        second_document_id=documents[1].id,
        matches=(match,),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=True,
        states_explored=3,
        limit_reasons=("max_nodes", "max_seconds"),
        ambiguous=True,
        equivalent_best_count=2,
        ambiguity_reason="equivalent_best_mappings",
    )
    report = compare_documents(documents, motif_report=motif_report)

    json_path = export_comparison_json(report, tmp_path / "limited.json")
    csv_path = export_comparison_csv(report, tmp_path / "limited.csv")

    json_data = json.loads(json_path.read_text(encoding="utf-8"))
    json_row = next(
        row for row in json_data["rows"] if row["descriptor_id"] == "motif.match.M1"
    )
    assert json_row["method_id"]
    assert json_row["cells"][0]["state"] == "moderate"
    assert json_row["cells"][0]["raw"]["ambiguous"] is True
    assert json_row["cells"][0]["raw"]["equivalent_best_count"] == 2
    assert "max_nodes" in " ".join(json_data["warnings"])
    assert "max_seconds" in " ".join(json_data["warnings"])
    assert "Ambiguous" in " ".join(json_data["warnings"])

    csv_rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig", newline="")))
    csv_row = next(row for row in csv_rows if row["Characteristic"].endswith("Common island"))
    assert csv_row["Method"]
    assert csv_row["A state"] == "moderate"
    assert csv_row["B state"] == "moderate"
    provenance = " ".join(
        (csv_row["A warning"], csv_row["B warning"], csv_row["Report warnings"])
    )
    assert "max_nodes" in provenance
    assert "max_seconds" in provenance
    assert "Ambiguous" in provenance


def test_incomplete_motif_exports_only_not_evaluated_provenance(tmp_path) -> None:
    documents = tuple(
        StructureDocument.from_structure(
            CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), [], []),
            HierarchyReport(),
        )
        for name in ("A", "B")
    )
    motif_report = MotifComparisonReport(
        first_document_id=documents[0].id,
        second_document_id=documents[1].id,
        matches=(),
        substitutions=(),
        unmatched_first=(),
        unmatched_second=(),
        approximate=True,
        states_explored=0,
        limit_reasons=("max_nodes",),
        graph_complete=False,
    )
    report = compare_documents(documents, motif_report=motif_report)

    json_data = json.loads(
        export_comparison_json(report, tmp_path / "incomplete.json").read_text(
            encoding="utf-8"
        )
    )
    motif_ids = {
        "motif.common",
        "connections.substitutions",
        "connections.unmatched",
    }
    json_rows = [row for row in json_data["rows"] if row["descriptor_id"] in motif_ids]
    assert len(json_rows) == 3
    for row in json_rows:
        assert [cell["display"] for cell in row["cells"]] == [
            "Not evaluated",
            "Not evaluated",
        ]
        assert [cell["state"] for cell in row["cells"]] == [
            "unavailable",
            "unavailable",
        ]
        assert all(cell["raw"] is None for cell in row["cells"])
    assert "not evaluated" in " ".join(json_data["warnings"]).lower()
    assert "max_nodes" in " ".join(json_data["warnings"])

    csv_rows = list(
        csv.DictReader(
            export_comparison_csv(report, tmp_path / "incomplete.csv").open(
                encoding="utf-8-sig",
                newline="",
            )
        )
    )
    exported = {
        row["Characteristic"].split(" / ", 1)[1]: row
        for row in csv_rows
        if row["Characteristic"].split(" / ", 1)[-1]
        in {"Common motif", "Atom substitutions", "Unmatched nodes"}
    }
    assert set(exported) == {"Common motif", "Atom substitutions", "Unmatched nodes"}
    for row in exported.values():
        assert row["A"] == row["B"] == "Not evaluated"
        assert row["A state"] == row["B state"] == "unavailable"
        assert "max_nodes" in row["Report warnings"]
