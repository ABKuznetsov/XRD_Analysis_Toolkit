from __future__ import annotations

import math

from crystal_viewer.analysis.reporting.model import (
    Availability,
    Provenance,
    ReportCell,
    ReportColumn,
    ReportRow,
    ReportTable,
)
from crystal_viewer.core.measurement import MeasuredValue, MissingState
from crystal_viewer.core.model import CrystalStructure


def _reported_cell(value: MeasuredValue) -> ReportCell:
    return ReportCell(
        value=value,
        display=value.formatted(),
        provenance=Provenance.REPORTED,
        source_name=value.source_name,
    )


def _calculated_cell(value: float | int | str, display: str | None = None, method_id: str = "") -> ReportCell:
    return ReportCell(
        value=value,
        display=str(value) if display is None else display,
        provenance=Provenance.CALCULATED,
        method_id=method_id,
    )


def _source_scalar_cell(structure: CrystalStructure, tag: str) -> ReportCell | None:
    raw = structure.source_data.raw(tag)
    if raw is None:
        return None
    return ReportCell(raw, raw, Provenance.REPORTED, source_name=tag)


def build_crystal_data_table(structure: CrystalStructure) -> ReportTable:
    rows: list[ReportRow] = []

    scalar_rows = (
        ("formula", "Chemical formula", "_chemical_formula_sum"),
        ("space_group", "Space group", "_space_group_name_H-M_alt"),
        ("crystal_system", "Crystal system", "_space_group_crystal_system"),
        ("hall", "Hall symbol", "_space_group_name_Hall"),
        ("z", "Z", "_cell_formula_units_Z"),
        ("temperature", "Temperature", "_diffrn_ambient_temperature"),
        ("pressure", "Pressure", "_diffrn_ambient_pressure"),
    )
    for row_id, title, tag in scalar_rows:
        cell = _source_scalar_cell(structure, tag)
        if cell is None and row_id == "space_group":
            cell = _source_scalar_cell(structure, "_symmetry_space_group_name_H-M")
        if cell is not None:
            rows.append(
                ReportRow(
                    id=f"crystal:{row_id}",
                    cells={"parameter": _calculated_cell(title), "value": cell},
                )
            )

    cell_parameters = (
        ("a", "a", "_cell_length_a", "Å", structure.cell.a),
        ("b", "b", "_cell_length_b", "Å", structure.cell.b),
        ("c", "c", "_cell_length_c", "Å", structure.cell.c),
        ("alpha", "α", "_cell_angle_alpha", "°", structure.cell.alpha),
        ("beta", "β", "_cell_angle_beta", "°", structure.cell.beta),
        ("gamma", "γ", "_cell_angle_gamma", "°", structure.cell.gamma),
    )
    for row_id, title, tag, unit, fallback in cell_parameters:
        measured = structure.source_data.numeric(tag, unit=unit)
        value_cell = (
            _reported_cell(measured)
            if measured.state is MissingState.PRESENT
            else _calculated_cell(fallback, f"{fallback:g}")
        )
        rows.append(
            ReportRow(
                id=f"cell:{row_id}",
                cells={"parameter": _calculated_cell(title), "value": value_cell},
            )
        )

    rows.append(
        ReportRow(
            id="cell:volume",
            cells={
                "parameter": _calculated_cell("V"),
                "value": _calculated_cell(
                    structure.cell.volume,
                    f"{structure.cell.volume:.5f}",
                    method_id="unit-cell-determinant",
                ),
            },
        )
    )
    return ReportTable(
        id="crystal_data",
        title="Crystal data",
        columns=(ReportColumn("parameter", "Parameter"), ReportColumn("value", "Value")),
        rows=tuple(rows),
    )


def build_refinement_table(structure: CrystalStructure) -> ReportTable:
    prefixes = ("_refine_", "_diffrn_", "_reflns_")
    rows = tuple(
        ReportRow(
            id=f"refine:{tag}",
            cells={
                "parameter": ReportCell(tag, tag, Provenance.REPORTED, source_name=tag),
                "value": ReportCell(raw, raw, Provenance.REPORTED, source_name=tag),
            },
        )
        for tag, raw in structure.source_data.scalars.items()
        if tag.startswith(prefixes)
    )
    return ReportTable(
        id="refinement",
        title="Data collection and refinement",
        columns=(ReportColumn("parameter", "CIF item"), ReportColumn("value", "Value")),
        rows=rows,
        availability=Availability.AVAILABLE if rows else Availability.UNAVAILABLE,
        unavailable_reason="" if rows else "No refinement data are present in the source CIF.",
    )


def _site_value(site, key: str, fallback: float, precision: int = 6) -> ReportCell:
    measured = site.reported.get(key)
    if measured is not None and measured.state is MissingState.PRESENT:
        return _reported_cell(measured)
    return _calculated_cell(fallback, f"{fallback:.{precision}f}")


def _site_occupancy(site) -> ReportCell:
    measured = site.reported.get("occupancy")
    if measured is not None and measured.state is MissingState.PRESENT:
        return _reported_cell(measured)
    method_id = "site-component-occupancy-sum" if len(site.components) > 1 else ""
    return _calculated_cell(
        site.occupancy,
        f"{site.occupancy:.6f}",
        method_id=method_id,
    )


def build_atomic_sites_table(structure: CrystalStructure) -> ReportTable:
    rows: list[ReportRow] = []
    for site in structure.asymmetric_sites:
        cart = structure.cell.frac_to_cart(site.fractional)
        rows.append(
            ReportRow(
                id=f"atom:{site.label}",
                cells={
                    "label": ReportCell(site.label, site.label, Provenance.REPORTED),
                    "species": ReportCell(site.element, site.element, Provenance.REPORTED),
                    "x": _site_value(site, "fract_x", site.fractional[0]),
                    "y": _site_value(site, "fract_y", site.fractional[1]),
                    "z": _site_value(site, "fract_z", site.fractional[2]),
                    "occupancy": _site_occupancy(site),
                    "cart_x": _calculated_cell(float(cart[0]), f"{cart[0]:.5f}"),
                    "cart_y": _calculated_cell(float(cart[1]), f"{cart[1]:.5f}"),
                    "cart_z": _calculated_cell(float(cart[2]), f"{cart[2]:.5f}"),
                },
                object_refs=(f"atom:{site.label}",),
            )
        )
    return ReportTable(
        id="atomic_sites",
        title="Atomic sites",
        columns=(
            ReportColumn("label", "Site"),
            ReportColumn("species", "Species"),
            ReportColumn("x", "x"),
            ReportColumn("y", "y"),
            ReportColumn("z", "z"),
            ReportColumn("occupancy", "Occupancy"),
            ReportColumn("cart_x", "X", "Å", False),
            ReportColumn("cart_y", "Y", "Å", False),
            ReportColumn("cart_z", "Z", "Å", False),
        ),
        rows=tuple(rows),
    )


def build_adp_table(structure: CrystalStructure) -> ReportTable:
    rows: list[ReportRow] = []
    for site in structure.asymmetric_sites:
        reported_b = site.reported.get("B_iso_or_equiv")
        reported_u = site.reported.get("U_iso_or_equiv")
        if reported_b is not None and reported_b.state is MissingState.PRESENT:
            u_value = float(reported_b.value) / (8.0 * math.pi**2)
            parameter = "Biso"
            reported_cell = _reported_cell(reported_b)
            u_cell = _calculated_cell(u_value, f"{u_value:.6f}", method_id="B-to-U")
        elif reported_u is not None and reported_u.state is MissingState.PRESENT:
            parameter = "Uiso"
            reported_cell = _reported_cell(reported_u)
            u_cell = _reported_cell(reported_u)
        elif site.u_iso is not None:
            parameter = "Uiso"
            reported_cell = _calculated_cell(site.u_iso, f"{site.u_iso:.6f}")
            u_cell = reported_cell
        else:
            continue
        rows.append(
            ReportRow(
                id=f"adp:{site.label}",
                cells={
                    "label": ReportCell(site.label, site.label, Provenance.REPORTED),
                    "parameter": ReportCell(parameter, parameter, Provenance.REPORTED),
                    "reported": reported_cell,
                    "u_equiv": u_cell,
                },
                object_refs=(f"atom:{site.label}",),
            )
        )
    return ReportTable(
        id="adp",
        title="Atomic displacement parameters",
        columns=(
            ReportColumn("label", "Site"),
            ReportColumn("parameter", "Source convention"),
            ReportColumn("reported", "Reported", "Å²"),
            ReportColumn("u_equiv", "U equivalent", "Å²"),
        ),
        rows=tuple(rows),
        availability=Availability.AVAILABLE if rows else Availability.UNAVAILABLE,
        unavailable_reason="" if rows else "No displacement parameters are available.",
    )
