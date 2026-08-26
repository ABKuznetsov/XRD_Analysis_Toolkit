from __future__ import annotations

import numpy as np
import pytest

from crystal_viewer.analysis.morphology import MillerFamily, MorphologyPlane
from crystal_viewer.analysis.morphology_geometry import build_morphology_model
from crystal_viewer.analysis.morphology_geometry import MorphologyFacet
from crystal_viewer.analysis.surface_markings import (
    SurfaceMarking,
    SurfaceMarkingKind,
    build_induction_contours,
    build_twin_striation,
)
from crystal_viewer.analysis.twin_geometry import build_twin_aggregate
from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec
from crystal_viewer.core.model import UnitCell


def _cube():
    cell = UnitCell(1.0, 1.0, 1.0)
    family = MillerFamily(
        (1, 0, 0),
        ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)),
        1.0,
        1,
        1.0,
        "test",
    )
    return cell, build_morphology_model(cell, (MorphologyPlane(family, 1.0, 1.0),))


def _segment_key(segment) -> tuple[tuple[float, ...], tuple[float, ...]]:
    endpoints = sorted(
        (tuple(np.round(segment.start, 9)), tuple(np.round(segment.end, 9)))
    )
    return endpoints[0], endpoints[1]


def test_twin_striation_is_the_clipped_intersection_of_lamellae_and_facets() -> None:
    cell, morphology = _cube()
    aggregate = build_twin_aggregate(
        cell,
        morphology,
        TwinAggregateSpec(
            TwinAggregateKind.POLYSYNTHETIC,
            TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
            composition_plane_hkl=(1, 0, 0),
            lamella_count=6,
            lamella_ratio=0.5,
        ),
    )

    segments = build_twin_striation(aggregate)

    assert len(segments) == 20
    assert all(segment.kind is SurfaceMarkingKind.TWIN for segment in segments)
    assert all(segment.family_hkl == (1, 0, 0) for segment in segments)
    assert all(np.linalg.norm(np.asarray(segment.end) - segment.start) > 1e-8 for segment in segments)
    assert len({_segment_key(segment) for segment in segments}) == len(segments)
    boundary_offsets = {round(plane.offset, 9) for plane in aggregate.composition_planes}
    for segment in segments:
        assert round(segment.start[0], 9) in boundary_offsets
        assert round(segment.end[0], 9) in boundary_offsets
        assert max(abs(value) for value in (*segment.start, *segment.end)) <= 1.0 + 1e-8


def test_twin_striation_does_not_touch_facets_outside_the_lamella_plane() -> None:
    cell, morphology = _cube()
    aggregate = build_twin_aggregate(
        cell,
        morphology,
        TwinAggregateSpec(
            TwinAggregateKind.POLYSYNTHETIC,
            TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
            composition_plane_hkl=(1, 0, 0),
            lamella_count=2,
        ),
    )

    segments = build_twin_striation(aggregate)

    assert len(segments) == 4
    assert all(abs(segment.start[0]) <= 1e-9 and abs(segment.end[0]) <= 1e-9 for segment in segments)


@pytest.mark.parametrize(
    "values",
    (
        {"target_family": (0, 0, 0)},
        {"density": 0},
        {"density": 51},
        {"density": 2.5},
        {"line_width": 0.24},
        {"line_width": 8.01},
        {"line_width": float("nan")},
    ),
)
def test_surface_marking_validates_family_density_and_line_width(values) -> None:
    settings = {
        "target_family": (1, 0, 0),
        "kind": SurfaceMarkingKind.INDUCTION,
        "density": 6,
        "line_width": 1.5,
    }
    settings.update(values)
    with pytest.raises((TypeError, ValueError)):
        SurfaceMarking(**settings)


def test_induction_contours_are_nested_inside_only_the_selected_family() -> None:
    target = MorphologyFacet(
        (0, 0, 1),
        (0, 0, 1),
        ((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)),
        (0.0, 0.0, 1.0),
        4.0,
    )
    other = MorphologyFacet(
        (1, 0, 0),
        (1, 0, 0),
        ((0.0, -1.0, -1.0), (0.0, 1.0, -1.0), (0.0, 1.0, 1.0), (0.0, -1.0, 1.0)),
        (1.0, 0.0, 0.0),
        4.0,
    )
    marking = SurfaceMarking((0, 0, 1), SurfaceMarkingKind.INDUCTION, density=3)

    contours = build_induction_contours((target, other), marking)

    assert len(contours) == 3
    assert all(contour.kind is SurfaceMarkingKind.INDUCTION for contour in contours)
    assert all(contour.family_hkl == (0, 0, 1) for contour in contours)
    for contour in contours:
        assert contour.points[0] == contour.points[-1]
        assert all(abs(x) <= 1.0 and abs(y) <= 1.0 for x, y, _z in contour.points)
        assert all(0.0 < z < 1e-3 for _x, _y, z in contour.points)
