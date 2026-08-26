from __future__ import annotations

from pathlib import Path

import pytest

from crystal_viewer.analysis.morphology import build_bfdh_planes, resolve_symmetry_operations
from crystal_viewer.analysis.morphology_geometry import build_morphology_model
from crystal_viewer.core.cif import load_cif

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("relative_path", "expected_provenance"),
    (
        ("examples/gehlenite_Ca2Al2SiO7_average.cif", "cif-loop"),
        ("examples/hinged_silicate.cif", "cif-loop"),
    ),
)
def test_real_cif_produces_bounded_bfdh_morphology(
    relative_path: str,
    expected_provenance: str,
) -> None:
    structure = load_cif(ROOT / relative_path)

    symmetry = resolve_symmetry_operations(structure)
    planes = build_bfdh_planes(structure, max_index=3)
    model = build_morphology_model(structure.cell, planes)

    assert symmetry.provenance == expected_provenance
    assert len(planes) > 0
    assert len(model.facets) >= 4
    assert model.volume > 0.0
    assert sum(model.fraction_by_family.values()) == pytest.approx(1.0)
    assert all(plane.rho > 0.0 for plane in planes)
