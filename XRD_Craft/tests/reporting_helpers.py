from crystal_viewer.analysis.reporting import (
    Provenance,
    ReportCell,
    ReportColumn,
    ReportRow,
    ReportSettings,
    ReportTable,
    StructureReport,
)
from crystal_viewer.core.measurement import MeasuredValue


def sample_table() -> ReportTable:
    columns = (
        ReportColumn("label", "Label"),
        ReportColumn("distance", "Distance", "Å"),
    )
    return ReportTable(
        id="bond_lengths",
        title="Bond lengths",
        columns=columns,
        rows=(
            ReportRow(
                "bond:1",
                {
                    "label": ReportCell("Al1", "Al1", Provenance.REPORTED),
                    "distance": ReportCell(1.734, "1.734", Provenance.CALCULATED),
                },
                include_in_publication=True,
            ),
            ReportRow(
                "bond:2",
                {
                    "label": ReportCell("Al1", "Al1", Provenance.REPORTED),
                    "distance": ReportCell(1.812, "1.812", Provenance.CALCULATED),
                },
                include_in_publication=False,
            ),
        ),
    )


def sample_report() -> StructureReport:
    measured = MeasuredValue(
        raw="7.7360(2)",
        value=7.736,
        su=0.0002,
        unit="Å",
        source_name="_cell_length_a",
    )
    crystal = ReportTable(
        id="crystal_data",
        title="Crystal data",
        columns=(ReportColumn("value", "Value", "Å"),),
        rows=(
            ReportRow(
                "cell:a",
                {
                    "value": ReportCell(
                        measured,
                        measured.raw,
                        Provenance.REPORTED,
                        source_name=measured.source_name,
                    )
                },
            ),
        ),
    )
    return StructureReport(
        structure_name="Example",
        source_path="example.cif",
        settings=ReportSettings(bond_tolerance=1.18),
        tables={"crystal_data": crystal, "bond_lengths": sample_table()},
        generator_version="0.1.0",
    )
