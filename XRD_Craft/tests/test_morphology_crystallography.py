from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from crystal_viewer.analysis.morphology import (
    build_bfdh_planes,
    equivalent_hkls,
    first_allowed_order,
    interplanar_spacing,
    reciprocal_normal,
    reduce_hkl,
    reflection_is_systematically_absent,
    resolve_symmetry_operations,
)
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.model import AtomSite, CrystalStructure
from crystal_viewer.core.model import UnitCell
from crystal_viewer.core.symmetry import parse_affine_operation

ROOT = Path(__file__).resolve().parents[1]


def test_parse_affine_operation_preserves_rotation_and_translation() -> None:
    operation = parse_affine_operation("-y,x-y,z+1/3")

    assert np.array_equal(
        operation.rotation,
        np.asarray(((0, -1, 0), (1, -1, 0), (0, 0, 1))),
    )
    assert np.allclose(operation.translation, (0.0, 0.0, 1.0 / 3.0))


def test_parse_affine_operation_accepts_unicode_minus_and_modulo_translation() -> None:
    operation = parse_affine_operation("−x+3/2,y,z-1/2")

    assert np.array_equal(operation.rotation, np.diag((-1, 1, 1)))
    assert np.allclose(operation.translation, (0.5, 0.0, 0.5))


@pytest.mark.parametrize(
    "operation",
    ("x*y,y,z", "x/2,y,z", "x,y", "x,y,unknown", "x+x,y,z"),
)
def test_parse_affine_operation_rejects_non_crystallographic_expression(
    operation: str,
) -> None:
    with pytest.raises(ValueError):
        parse_affine_operation(operation)


def test_reduce_hkl_keeps_the_complementary_sign() -> None:
    assert reduce_hkl((2, -4, 6)) == (1, -2, 3)
    assert reduce_hkl((-2, 0, 0)) == (-1, 0, 0)
    with pytest.raises(ValueError):
        reduce_hkl((0, 0, 0))


def test_cubic_interplanar_spacing_and_normal() -> None:
    cell = UnitCell(5.0, 5.0, 5.0)

    assert np.isclose(interplanar_spacing(cell, (1, 1, 0)), 5.0 / math.sqrt(2.0))
    assert np.allclose(
        reciprocal_normal(cell, (1, 1, 0)),
        (1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0), 0.0),
    )


def test_low_symmetry_spacing_matches_reciprocal_matrix_definition() -> None:
    cell = UnitCell(4.1, 5.2, 6.3, 78.0, 103.0, 111.0)
    hkl = np.asarray((2, -1, 3), dtype=float)
    expected_vector = hkl @ np.linalg.inv(cell.matrix).T

    assert np.isclose(interplanar_spacing(cell, hkl), 1.0 / np.linalg.norm(expected_vector))
    assert np.allclose(reciprocal_normal(cell, hkl), expected_vector / np.linalg.norm(expected_vector))
    assert np.isclose(interplanar_spacing(cell, -hkl), interplanar_spacing(cell, hkl))


def test_equivalent_hkls_are_deterministic_and_keep_polar_opposites_separate() -> None:
    fourfold = (
        "x,y,z",
        "-y,x,z",
        "-x,-y,z",
        "y,-x,z",
    )

    assert equivalent_hkls((1, 0, 0), fourfold) == (
        (-1, 0, 0),
        (0, -1, 0),
        (0, 1, 0),
        (1, 0, 0),
    )
    assert equivalent_hkls((0, 0, 1), fourfold) == ((0, 0, 1),)
    assert equivalent_hkls((0, 0, -1), fourfold) == ((0, 0, -1),)


@pytest.mark.parametrize(
    ("hkl", "absent"),
    (((1, 0, 0), True), ((1, 1, 0), False), ((2, 1, 1), False)),
)
def test_body_centering_controls_systematic_absence(hkl, absent: bool) -> None:
    operations = load_cif(
        ROOT / "tests" / "data" / "morphology" / "body_centered.cif"
    ).symmetry_operations

    assert reflection_is_systematically_absent(hkl, operations) is absent


def test_screw_axis_and_glide_translation_control_systematic_absence() -> None:
    screw = ("x,y,z", "-x,y+1/2,-z")
    glide = ("x,y,z", "x+1/2,-y,z")

    assert reflection_is_systematically_absent((0, 1, 0), screw)
    assert not reflection_is_systematically_absent((0, 2, 0), screw)
    assert reflection_is_systematically_absent((1, 0, 2), glide)
    assert not reflection_is_systematically_absent((2, 0, 2), glide)
    assert first_allowed_order((0, 1, 0), screw) == 2


def test_symmetry_is_reconstructed_from_space_group_symbol() -> None:
    site = AtomSite("Si1", "Si", (0.123, 0.234, 0.345))
    structure = CrystalStructure(
        "symbol only",
        UnitCell(6.0, 7.0, 8.0),
        [site],
        [site],
        symmetry_operations=["x,y,z"],
        space_group="I222",
    )

    resolved = resolve_symmetry_operations(structure)

    assert resolved.provenance == "space-group-symbol"
    assert len(resolved.operations) == 8
    assert resolved.warning == ""


def test_invalid_space_group_uses_warned_identity_fallback() -> None:
    site = AtomSite("Si1", "Si", (0.0, 0.0, 0.0))
    structure = CrystalStructure(
        "unknown",
        UnitCell(5.0, 5.0, 5.0),
        [site],
        [site],
        space_group="not-a-space-group",
    )

    resolved = resolve_symmetry_operations(structure)

    assert resolved.provenance == "identity-fallback"
    assert resolved.operations == ("x,y,z",)
    assert "identity" in resolved.warning.lower()


def test_bfdh_planes_use_extinction_order_and_relative_normalization() -> None:
    structure = load_cif(
        ROOT / "tests" / "data" / "morphology" / "body_centered.cif"
    )

    planes = build_bfdh_planes(structure, max_index=1)
    x_family = next(plane for plane in planes if (1, 0, 0) in plane.family.equivalents)

    assert x_family.family.allowed_order == 2
    assert np.isclose(
        x_family.family.d_effective,
        x_family.family.d_hkl / x_family.family.allowed_order,
    )
    assert min(plane.rho0 for plane in planes) == pytest.approx(1.0)
    assert all(plane.rho == plane.rho0 and plane.enabled for plane in planes)
