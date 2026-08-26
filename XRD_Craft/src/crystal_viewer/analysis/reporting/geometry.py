from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.reporting.model import (
    Provenance,
    ReportCell,
    ReportColumn,
    ReportRow,
    ReportTable,
)
from crystal_viewer.core.model import CrystalStructure
from crystal_viewer.core.measurement import MissingState, parse_cif_number


@dataclass(frozen=True, slots=True)
class GeometrySettings:
    distance_tolerance: float = 0.001
    angle_tolerance: float = 0.01


def symmetry_code(image: tuple[int, int, int]) -> str:
    return "1_" + "".join(str(5 + int(component)) for component in image)


def _text(value: str, provenance: Provenance = Provenance.CALCULATED) -> ReportCell:
    return ReportCell(value, value, provenance)


def _number(value: float, digits: int, method_id: str) -> ReportCell:
    return ReportCell(value, f"{value:.{digits}f}", Provenance.CALCULATED, method_id=method_id)


def _loop_value(loop, row: tuple[str, ...], tag: str, default: str = "") -> str:
    try:
        return row[loop.tags.index(tag)]
    except ValueError:
        return default


def _reported_bond_rows(structure: CrystalStructure) -> tuple[list[ReportRow], set[tuple[str, ...]]]:
    rows: list[ReportRow] = []
    keys: set[tuple[str, ...]] = set()
    required = "_geom_bond_atom_site_label_1"
    for loop in structure.source_data.loops:
        if required not in loop.tags or "_geom_bond_distance" not in loop.tags:
            continue
        for index, source_row in enumerate(loop.rows, start=1):
            first = _loop_value(loop, source_row, required)
            second = _loop_value(loop, source_row, "_geom_bond_atom_site_label_2")
            sym_first = _loop_value(loop, source_row, "_geom_bond_site_symmetry_1", ".") or "."
            sym_second = _loop_value(loop, source_row, "_geom_bond_site_symmetry_2", ".") or "."
            token = _loop_value(loop, source_row, "_geom_bond_distance")
            measured = parse_cif_number(
                token,
                unit="Å",
                source_name="_geom_bond_distance",
            )
            if measured.state is not MissingState.PRESENT:
                continue
            publication = _loop_value(loop, source_row, "_geom_bond_publ_flag", "yes").lower()
            key = (first, second, sym_first, sym_second)
            keys.add(key)
            rows.append(
                ReportRow(
                    id=f"bond:reported:{index}:{first}:{second}",
                    cells={
                        "center": _text(first, Provenance.REPORTED),
                        "ligand": _text(second, Provenance.REPORTED),
                        "distance": ReportCell(
                            measured,
                            measured.formatted(),
                            Provenance.REPORTED,
                            source_name=measured.source_name,
                        ),
                        "multiplicity": ReportCell(1, "1", Provenance.REPORTED),
                        "symmetry": _text(
                            f"{sym_first} / {sym_second}", Provenance.REPORTED
                        ),
                        "polyhedron": _text("—", Provenance.UNAVAILABLE),
                    },
                    include_in_publication=publication in {"yes", "y", "1", "true"},
                    object_refs=(f"atom:{first}", f"atom:{second}"),
                )
            )
    return rows, keys


def build_bond_table(
    structure: CrystalStructure,
    hierarchy: HierarchyReport,
    settings: GeometrySettings,
) -> ReportTable:
    rows, reported_keys = _reported_bond_rows(structure)
    seen: set[tuple[int, int, tuple[int, int, int]]] = set()
    for polyhedron in hierarchy.polyhedra:
        centre = structure.sites[polyhedron.center_index]
        for ligand, distance in zip(polyhedron.ligands, polyhedron.bond_lengths, strict=True):
            key = (polyhedron.center_index, ligand.site_index, ligand.image)
            if key in seen:
                continue
            seen.add(key)
            ligand_site = structure.sites[ligand.site_index]
            code = symmetry_code(ligand.image)
            if (centre.label, ligand_site.label, ".", code) in reported_keys:
                continue
            row_id = f"bond:{centre.label}:{ligand_site.label}:{code}"
            rows.append(
                ReportRow(
                    id=row_id,
                    cells={
                        "center": _text(centre.label),
                        "ligand": _text(ligand_site.label),
                        "distance": _number(float(distance), 4, "periodic-cartesian-distance"),
                        "multiplicity": ReportCell(1, "1", Provenance.CALCULATED),
                        "symmetry": _text(code),
                        "polyhedron": _text(polyhedron.id),
                    },
                    object_refs=(
                        f"atom:{centre.label}",
                        f"atom:{ligand_site.label}@{ligand.image}",
                        f"polyhedron:{polyhedron.id}",
                    ),
                )
            )
    return ReportTable(
        id="bond_lengths",
        title="Bond lengths",
        columns=(
            ReportColumn("center", "Centre"),
            ReportColumn("ligand", "Ligand"),
            ReportColumn("distance", "Distance", "Å"),
            ReportColumn("multiplicity", "Multiplicity"),
            ReportColumn("symmetry", "Symmetry"),
            ReportColumn("polyhedron", "Polyhedron"),
        ),
        rows=tuple(rows),
        method="Distances calculated in Cartesian coordinates with periodic images.",
    )


def _angle(first: np.ndarray, apex: np.ndarray, second: np.ndarray) -> float:
    vector_a = first - apex
    vector_b = second - apex
    denominator = np.linalg.norm(vector_a) * np.linalg.norm(vector_b)
    if denominator <= 1e-14:
        return 0.0
    cosine = float(np.dot(vector_a, vector_b) / denominator)
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def build_angle_table(
    structure: CrystalStructure,
    hierarchy: HierarchyReport,
    settings: GeometrySettings,
) -> ReportTable:
    rows: list[ReportRow] = []
    for loop in structure.source_data.loops:
        if "_geom_angle_atom_site_label_1" not in loop.tags or "_geom_angle" not in loop.tags:
            continue
        for index, source_row in enumerate(loop.rows, start=1):
            labels = tuple(
                _loop_value(loop, source_row, f"_geom_angle_atom_site_label_{position}")
                for position in (1, 2, 3)
            )
            symmetries = tuple(
                _loop_value(loop, source_row, f"_geom_angle_site_symmetry_{position}", ".")
                or "."
                for position in (1, 2, 3)
            )
            measured = parse_cif_number(
                _loop_value(loop, source_row, "_geom_angle"),
                unit="°",
                source_name="_geom_angle",
            )
            if measured.state is not MissingState.PRESENT:
                continue
            publication = _loop_value(loop, source_row, "_geom_angle_publ_flag", "yes").lower()
            rows.append(
                ReportRow(
                    id=f"angle:reported:{index}:{':'.join(labels)}",
                    cells={
                        "first": _text(labels[0], Provenance.REPORTED),
                        "apex": _text(labels[1], Provenance.REPORTED),
                        "second": _text(labels[2], Provenance.REPORTED),
                        "angle": ReportCell(
                            measured,
                            measured.formatted(),
                            Provenance.REPORTED,
                            source_name=measured.source_name,
                        ),
                        "kind": _text("reported", Provenance.REPORTED),
                        "symmetry": _text(" / ".join(symmetries), Provenance.REPORTED),
                    },
                    include_in_publication=publication in {"yes", "y", "1", "true"},
                    object_refs=tuple(f"atom:{label}" for label in labels),
                )
            )
    polyhedra = {polyhedron.id: polyhedron for polyhedron in hierarchy.polyhedra}
    matrix = structure.cell.matrix

    for polyhedron in hierarchy.polyhedra:
        centre_site = structure.sites[polyhedron.center_index]
        apex = structure.cell.frac_to_cart(centre_site.fractional)
        for first_index, second_index in combinations(range(len(polyhedron.ligands)), 2):
            first_ref = polyhedron.ligands[first_index]
            second_ref = polyhedron.ligands[second_index]
            first = np.asarray(polyhedron.vertex_coordinates[first_index], dtype=float)
            second = np.asarray(polyhedron.vertex_coordinates[second_index], dtype=float)
            first_site = structure.sites[first_ref.site_index]
            second_site = structure.sites[second_ref.site_index]
            value = _angle(first, apex, second)
            rows.append(
                ReportRow(
                    id=f"angle:{polyhedron.id}:{first_index}:{second_index}",
                    cells={
                        "first": _text(first_site.label),
                        "apex": _text(centre_site.label),
                        "second": _text(second_site.label),
                        "angle": _number(value, 3, "vector-angle"),
                        "kind": _text("intrapolyhedral"),
                        "symmetry": _text(
                            f"{symmetry_code(first_ref.image)} / {symmetry_code(second_ref.image)}"
                        ),
                    },
                    object_refs=(f"polyhedron:{polyhedron.id}",),
                )
            )

    for connection_index, connection in enumerate(hierarchy.polyhedron_connections, start=1):
        if len(connection.shared_ligands) != 1:
            continue
        first_poly = polyhedra[connection.first]
        second_poly = polyhedra[connection.second]
        shared = connection.shared_ligands[0]
        ligand_site = structure.sites[shared.site_index]
        ligand_frac = np.asarray(ligand_site.fractional, dtype=float)
        apex = (ligand_frac + np.asarray(shared.image, dtype=float)) @ matrix
        centres = []
        for polyhedron in (first_poly, second_poly):
            centre_frac = np.asarray(structure.sites[polyhedron.center_index].fractional, dtype=float)
            delta = centre_frac - ligand_frac - np.asarray(shared.image, dtype=float)
            centre_image = -np.rint(delta)
            centres.append((centre_frac + centre_image) @ matrix)
        value = _angle(centres[0], apex, centres[1])
        first_site = structure.sites[first_poly.center_index]
        second_site = structure.sites[second_poly.center_index]
        rows.append(
            ReportRow(
                id=f"angle:bridge:{connection_index}",
                cells={
                    "first": _text(first_site.label),
                    "apex": _text(ligand_site.label),
                    "second": _text(second_site.label),
                    "angle": _number(value, 3, "periodic-bridge-angle"),
                    "kind": _text("bridge"),
                    "symmetry": _text(symmetry_code(shared.image)),
                },
                object_refs=(
                    f"polyhedron:{first_poly.id}",
                    f"atom:{ligand_site.label}@{shared.image}",
                    f"polyhedron:{second_poly.id}",
                ),
            )
        )

    return ReportTable(
        id="bond_angles",
        title="Bond angles",
        columns=(
            ReportColumn("first", "Atom 1"),
            ReportColumn("apex", "Apex"),
            ReportColumn("second", "Atom 2"),
            ReportColumn("angle", "Angle", "°"),
            ReportColumn("kind", "Kind"),
            ReportColumn("symmetry", "Symmetry"),
        ),
        rows=tuple(rows),
        method="Angles calculated from periodic Cartesian vectors; calculated ESD unavailable.",
    )
