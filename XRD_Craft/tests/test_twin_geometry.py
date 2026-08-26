from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.spatial import ConvexHull

from crystal_viewer.analysis.morphology import MillerFamily, MorphologyPlane
from crystal_viewer.analysis.morphology_geometry import build_morphology_model
from crystal_viewer.analysis.twin_geometry import (
    InvalidTwinGeometryError,
    build_twin_aggregate,
)
from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode, twin_cartesian_transform
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


def test_penetration_transforms_the_second_domain_without_losing_family_identity() -> None:
    cell, morphology = _cube()
    translation = np.asarray((0.25, -0.5, 1.0))
    law = TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 1, 0))
    spec = TwinAggregateSpec(
        TwinAggregateKind.PENETRATION,
        law,
        composition_plane_hkl=(1, 1, 0),
        second_translation=tuple(translation),
    )

    aggregate = build_twin_aggregate(cell, morphology, spec)

    assert tuple(domain.domain_id for domain in aggregate.domains) == ("I", "II")
    parent, twin = aggregate.domains
    transform = twin_cartesian_transform(cell, law)
    np.testing.assert_allclose(parent.orientation, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(twin.orientation, transform, atol=1e-12)
    np.testing.assert_allclose(
        np.asarray(twin.vertices),
        np.asarray(morphology.vertices) @ transform.T + translation,
        atol=1e-10,
    )
    assert {facet.family_hkl for facet in twin.facets} == {(1, 0, 0)}
    assert tuple(facet.display_hkl for facet in twin.facets) == tuple(
        facet.plane_hkl for facet in morphology.facets
    )
    for source, transformed in zip(morphology.facets, twin.facets, strict=True):
        np.testing.assert_allclose(transformed.normal, transform @ source.normal, atol=1e-10)
    assert "intergrowth" in " ".join(aggregate.warnings).lower()


def test_contact_twin_clips_domains_to_opposite_sides_of_a_shared_plane() -> None:
    cell, morphology = _cube()
    spec = TwinAggregateSpec(
        TwinAggregateKind.CONTACT,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
    )

    aggregate = build_twin_aggregate(cell, morphology, spec)

    assert len(aggregate.domains) == 2
    assert len(aggregate.composition_planes) == 1
    plane = aggregate.composition_planes[0]
    normal = np.asarray(plane.normal)
    assert plane.hkl == (1, 0, 0)
    assert len(plane.polygon) == 4
    assert all(abs(np.dot(normal, point) - plane.offset) <= 1e-8 for point in plane.polygon)
    parent_projection = np.asarray(aggregate.domains[0].vertices) @ normal
    twin_projection = np.asarray(aggregate.domains[1].vertices) @ normal
    assert np.max(parent_projection) <= plane.offset + 1e-8
    assert np.min(twin_projection) >= plane.offset - 1e-8
    volumes = tuple(ConvexHull(np.asarray(domain.vertices)).volume for domain in aggregate.domains)
    assert all(math.isfinite(volume) and volume > 0.0 for volume in volumes)
    assert sum(volumes) == pytest.approx(morphology.volume)


def test_contact_plane_that_misses_the_individuals_has_a_stable_error() -> None:
    cell, morphology = _cube()
    spec = TwinAggregateSpec(
        TwinAggregateKind.CONTACT,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
        composition_offset=10.0,
    )

    with pytest.raises(InvalidTwinGeometryError) as caught:
        build_twin_aggregate(cell, morphology, spec)

    assert caught.value.code == "composition-miss"


def test_polysynthetic_twin_builds_deterministic_alternating_lamellae() -> None:
    cell, morphology = _cube()
    spec = TwinAggregateSpec(
        TwinAggregateKind.POLYSYNTHETIC,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
        composition_plane_hkl=(1, 0, 0),
        lamella_count=6,
        lamella_ratio=0.25,
    )

    first = build_twin_aggregate(cell, morphology, spec)
    second = build_twin_aggregate(cell, morphology, spec)

    assert first == second
    assert len(first.domains) == 6
    assert tuple(domain.orientation_state for domain in first.domains) == (
        "I", "II", "I", "II", "I", "II"
    )
    intervals = tuple(domain.slab_interval for domain in first.domains)
    assert all(interval is not None for interval in intervals)
    assert all(left[1] == pytest.approx(right[0]) for left, right in zip(intervals, intervals[1:]))
    widths = tuple(high - low for low, high in intervals)
    assert widths[0] / (widths[0] + widths[1]) == pytest.approx(0.25)
    normal = np.asarray(first.composition_planes[0].normal)
    for domain, (low, high) in zip(first.domains, intervals, strict=True):
        projections = np.asarray(domain.vertices) @ normal
        assert np.min(projections) >= low - 1e-8
        assert np.max(projections) <= high + 1e-8
    assert len(first.composition_planes) == 5


def test_polysynthetic_twin_drops_empty_remnants_without_inventing_interfaces() -> None:
    cell, morphology = _cube()
    aggregate = build_twin_aggregate(
        cell,
        morphology,
        TwinAggregateSpec(
            TwinAggregateKind.POLYSYNTHETIC,
            TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
            composition_plane_hkl=(1, 0, 0),
            second_translation=(10.0, 0.0, 0.0),
            lamella_count=6,
            lamella_ratio=0.5,
        ),
    )

    assert tuple(domain.domain_id for domain in aggregate.domains) == ("L1", "L6")
    assert aggregate.composition_planes == ()
