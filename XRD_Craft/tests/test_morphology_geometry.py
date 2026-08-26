from __future__ import annotations

import math

import numpy as np
import pytest

from crystal_viewer.analysis.morphology import MillerFamily, MorphologyPlane
from crystal_viewer.analysis.morphology_geometry import (
    InvalidMorphologyError,
    build_morphology_model,
)
from crystal_viewer.core.model import UnitCell


def _plane(hkl, equivalents, rho=1.0, *, enabled=True) -> MorphologyPlane:
    family = MillerFamily(
        hkl=tuple(hkl),
        equivalents=tuple(tuple(value) for value in equivalents),
        d_hkl=1.0,
        allowed_order=1,
        d_effective=1.0,
        symmetry_source="test",
    )
    return MorphologyPlane(family, rho, rho, enabled=enabled)


def test_cube_geometry_has_expected_facets_area_and_volume() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    cube = _plane(
        (1, 0, 0),
        ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)),
    )

    model = build_morphology_model(cell, (cube,))

    assert len(model.vertices) == 8
    assert len(model.facets) == 6
    assert model.volume == pytest.approx(8.0)
    assert model.area_by_family[(1, 0, 0)] == pytest.approx(24.0)
    assert model.fraction_by_family[(1, 0, 0)] == pytest.approx(1.0)
    assert all(np.dot(facet.normal, np.mean(facet.vertices, axis=0)) > 0 for facet in model.facets)


def test_octahedron_geometry_is_deterministic() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    equivalents = tuple(
        (h, k, l)
        for h in (-1, 1)
        for k in (-1, 1)
        for l in (-1, 1)
    )
    octahedron = _plane((1, 1, 1), equivalents)

    first = build_morphology_model(cell, (octahedron,))
    second = build_morphology_model(cell, (octahedron,))

    assert len(first.vertices) == 6
    assert len(first.facets) == 8
    assert first.volume == pytest.approx(4.0 * math.sqrt(3.0))
    assert first.vertices == second.vertices
    assert tuple(facet.vertices for facet in first.facets) == tuple(facet.vertices for facet in second.facets)


def test_non_manifest_family_remains_with_zero_area() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    cube = _plane(
        (1, 0, 0),
        ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)),
    )
    outside = _plane((1, 1, 1), ((1, 1, 1),), rho=10.0)

    model = build_morphology_model(cell, (cube, outside))

    assert model.area_by_family[(1, 1, 1)] == 0.0
    assert model.fraction_by_family[(1, 1, 1)] == 0.0


@pytest.mark.parametrize("scale", (1e-12, 1e12))
def test_common_distance_scale_preserves_topology_and_fractions(scale: float) -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    equivalents = (
        (1, 0, 0), (-1, 0, 0), (0, 1, 0),
        (0, -1, 0), (0, 0, 1), (0, 0, -1),
    )
    reference = build_morphology_model(cell, (_plane((1, 0, 0), equivalents),))
    scaled = build_morphology_model(
        cell, (_plane((1, 0, 0), equivalents, rho=scale),)
    )

    assert len(scaled.vertices) == len(reference.vertices)
    assert len(scaled.facets) == len(reference.facets)
    assert scaled.fraction_by_family == pytest.approx(reference.fraction_by_family)
    assert scaled.volume == pytest.approx(reference.volume * scale**3)


@pytest.mark.parametrize(
    ("planes", "code"),
    (
        ((), "empty"),
        ((_plane((1, 0, 0), ((1, 0, 0),), rho=0.0),), "invalid-distance"),
        ((_plane((1, 0, 0), ((1, 0, 0), (-1, 0, 0))),), "unbounded"),
    ),
)
def test_invalid_or_unbounded_geometry_has_stable_error_code(planes, code: str) -> None:
    with pytest.raises(InvalidMorphologyError) as caught:
        build_morphology_model(UnitCell(1.0, 1.0, 1.0), planes)

    assert caught.value.code == code
