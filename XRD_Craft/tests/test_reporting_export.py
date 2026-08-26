import csv
import json

import pytest

from crystal_viewer.analysis.reporting import Availability, ReportTable
from crystal_viewer.analysis.reporting.export import export_report_json, export_table_csv
from tests.reporting_helpers import sample_report, sample_table


def test_csv_exports_only_included_rows_and_units(tmp_path) -> None:
    path = export_table_csv(sample_table(), tmp_path / "bonds.csv")

    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["id"] for row in rows] == ["bond:1"]
    assert rows[0]["distance [Å]"] == "1.734"


def test_json_preserves_raw_esd_provenance_and_settings(tmp_path) -> None:
    path = export_report_json(sample_report(), tmp_path / "report.json")
    data = json.loads(path.read_text(encoding="utf-8"))

    cell = data["tables"]["crystal_data"]["rows"][0]["cells"]["value"]
    assert cell["raw"] == "7.7360(2)"
    assert cell["su"] == 0.0002
    assert cell["provenance"] == "reported"
    assert data["settings"]["bond_tolerance"] == 1.18


def test_unavailable_table_cannot_be_exported(tmp_path) -> None:
    table = ReportTable(
        id="bond_valence",
        title="Bond valence",
        columns=(),
        rows=(),
        availability=Availability.UNAVAILABLE,
        unavailable_reason="parameter set not selected",
    )

    with pytest.raises(
        ValueError,
        match="Table 'bond_valence' is unavailable: parameter set not selected",
    ):
        export_table_csv(table, tmp_path / "bvs.csv")
