from __future__ import annotations

import csv
import json
from pathlib import Path

from crystal_viewer.analysis.morphology import build_bfdh_planes
from crystal_viewer.analysis.morphology_export import export_morphology_csv, export_morphology_json
from crystal_viewer.analysis.morphology_geometry import build_morphology_model
from crystal_viewer.analysis.morphology_state import MorphologyEditState, apply_edit_state
from crystal_viewer.analysis.surface_markings import SurfaceMarking, SurfaceMarkingKind
from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec
from crystal_viewer.ui.morphology_colors import allocate_family_colors
from crystal_viewer.core.cif import load_cif

ROOT = Path(__file__).resolve().parents[1]


def test_csv_contains_calculated_and_editable_plane_values(tmp_path) -> None:
    structure = load_cif(ROOT / "tests" / "data" / "morphology" / "body_centered.cif")
    base = build_bfdh_planes(structure, max_index=1)
    state = MorphologyEditState(max_index=1).with_distance(base[0].family.hkl, base[0].rho0 * 1.2)
    planes = apply_edit_state(structure, base, state)
    model = build_morphology_model(structure.cell, planes)
    path = tmp_path / "morphology.csv"

    export_morphology_csv(path, model)

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {
        "hkl",
        "d_hkl_angstrom",
        "allowed_order",
        "d_effective_angstrom",
        "bfdh_rho0",
        "current_rho",
        "enabled",
        "area_relative",
        "area_fraction",
        "state",
        "method",
        "warning",
    } <= set(rows[0])
    assert any(row["state"] == "manual" for row in rows)
    assert all(row["method"] == "BFDH geometric morphology prediction" for row in rows)


def test_flat_export_keeps_reference_origin_color_and_explicit_empty_twin_fields(tmp_path) -> None:
    structure = load_cif(ROOT / "tests" / "data" / "morphology" / "body_centered.cif")
    base = build_bfdh_planes(structure, max_index=2)
    reference = build_morphology_model(structure.cell, base)
    state = MorphologyEditState(max_index=2)
    current = build_morphology_model(structure.cell, apply_edit_state(structure, base, state))
    colors = allocate_family_colors(plane.family.hkl for plane in current.planes)
    path = tmp_path / "truth.csv"

    export_morphology_csv(
        path,
        current,
        reference_model=reference,
        state=state,
        color_by_family=colors,
    )

    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    assert rows
    assert all(row["color"] == colors[tuple(map(int, row["hkl"].split()))] for row in rows)
    assert all(row["twin_kind"] == row["twin_law"] == row["twin_provenance"] == "" for row in rows)
    assert all("reference_fraction" in row and "current_fraction" in row and "origin" in row for row in rows)


def test_json_export_contains_exact_state_orientation_and_provenance(tmp_path) -> None:
    structure = load_cif(ROOT / "tests" / "data" / "morphology" / "primitive_cubic.cif")
    model = build_morphology_model(structure.cell, build_bfdh_planes(structure, max_index=1))
    twin = TwinAggregateSpec(
        TwinAggregateKind.POLYSYNTHETIC,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 1, 0)),
        composition_plane_hkl=(1, 1, 0),
        lamella_count=4,
    )
    marking = SurfaceMarking((1, 0, 0), SurfaceMarkingKind.INDUCTION, 5, 2.0)
    state = MorphologyEditState(twin=twin, markings=(marking,))
    path = tmp_path / "morphology.json"

    export_morphology_json(path, model, state=state)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format_version"] == 2
    assert payload["state"]["twin"]["kind"] == "polysynthetic"
    assert payload["state"]["twin"]["law"]["mode"] == "reflection"
    assert payload["state"]["markings"] == [
        {
            "target_family": [1, 0, 0],
            "kind": "induction",
            "density": 5,
            "line_width": 2.0,
        }
    ]
    assert payload["calculation"]["method"] == "BFDH geometric morphology prediction"
