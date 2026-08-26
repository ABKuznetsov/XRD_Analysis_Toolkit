from __future__ import annotations

import pytest

from crystal_viewer.analysis.morphology import MillerFamily, MorphologyPlane, build_bfdh_planes
from crystal_viewer.analysis.morphology_geometry import build_morphology_model
from crystal_viewer.analysis.morphology_selection import (
    select_primary_forms,
    with_active_families,
)
from crystal_viewer.core.model import UnitCell


def _plane(hkl, equivalents, rho=1.0) -> MorphologyPlane:
    family = MillerFamily(
        hkl=tuple(hkl),
        equivalents=tuple(tuple(value) for value in equivalents),
        d_hkl=1.0,
        allowed_order=1,
        d_effective=1.0,
        symmetry_source="test",
    )
    return MorphologyPlane(family, rho, rho)


CUBE = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)
OCTAHEDRON = tuple(
    (h, k, l)
    for h in (-1, 1)
    for k in (-1, 1)
    for l in (-1, 1)
)


def test_minimum_ranked_set_covering_eighty_percent_is_selected() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    cube = _plane((1, 0, 0), CUBE)
    corner_cuts = _plane((1, 1, 1), OCTAHEDRON, rho=1.3)

    selection = select_primary_forms(cell, (cube, corner_cuts))

    assert selection.active_families == ((1, 0, 0),)
    assert selection.coverage == pytest.approx(
        selection.reference_fraction_by_family[(1, 0, 0)]
    )
    assert selection.coverage >= 0.80
    assert selection.used_full_fallback is False
    active = with_active_families((cube, corner_cuts), selection.active_families)
    assert tuple(plane.enabled for plane in active) == (True, False)
    assert build_morphology_model(cell, active).volume > 0.0


def test_selector_adds_ranked_families_until_shape_is_bounded() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    planes = (
        _plane((1, 0, 0), ((1, 0, 0), (-1, 0, 0))),
        _plane((0, 1, 0), ((0, 1, 0), (0, -1, 0))),
        _plane((0, 0, 1), ((0, 0, 1), (0, 0, -1))),
    )

    selection = select_primary_forms(cell, planes, target=0.60)

    assert set(selection.active_families) == {plane.family.hkl for plane in planes}
    assert selection.coverage == pytest.approx(1.0)
    assert selection.used_full_fallback is True
    assert selection.warnings
    assert build_morphology_model(
        cell,
        with_active_families(planes, selection.active_families),
    ).volume > 0.0


@pytest.mark.parametrize("target", (0.0, -0.1, 1.01, float("nan")))
def test_invalid_primary_coverage_is_rejected(target: float) -> None:
    with pytest.raises(ValueError, match="target"):
        select_primary_forms(UnitCell(1.0, 1.0, 1.0), (), target=target)


def test_real_cif_primary_selection_is_bounded_and_leaves_additional_families(
    body_centered_document,
) -> None:
    structure = body_centered_document.structure
    planes = build_bfdh_planes(structure, max_index=3)

    selection = select_primary_forms(structure.cell, planes)
    active_model = build_morphology_model(
        structure.cell,
        with_active_families(planes, selection.active_families),
    )

    assert selection.coverage >= 0.80
    assert active_model.volume > 0.0
    assert len(selection.active_families) < len(planes)
