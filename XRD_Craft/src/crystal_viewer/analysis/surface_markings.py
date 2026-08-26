from __future__ import annotations

import math
import operator
from dataclasses import dataclass
from enum import Enum

import numpy as np

from crystal_viewer.analysis.morphology import Hkl, reduce_hkl
from crystal_viewer.analysis.twin_geometry import TwinAggregate, TwinFacet


class SurfaceMarkingKind(str, Enum):
    INDUCTION = "induction"
    TWIN = "twin"


@dataclass(frozen=True, slots=True)
class SurfaceMarking:
    target_family: Hkl
    kind: SurfaceMarkingKind
    density: int = 6
    line_width: float = 1.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_family", reduce_hkl(self.target_family))
        object.__setattr__(self, "kind", SurfaceMarkingKind(self.kind))
        if isinstance(self.density, bool):
            raise ValueError("Surface-marking density must be an integer from 1 to 50.")
        try:
            density = operator.index(self.density)
        except TypeError as error:
            raise ValueError("Surface-marking density must be an integer from 1 to 50.") from error
        if not 1 <= density <= 50:
            raise ValueError("Surface-marking density must be an integer from 1 to 50.")
        object.__setattr__(self, "density", density)
        line_width = float(self.line_width)
        if not math.isfinite(line_width) or not 0.25 <= line_width <= 8.0:
            raise ValueError("Surface-marking line width must be from 0.25 to 8.0.")
        object.__setattr__(self, "line_width", line_width)


@dataclass(frozen=True, slots=True)
class MarkingSegment:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    family_hkl: Hkl
    domain_id: str
    kind: SurfaceMarkingKind = SurfaceMarkingKind.TWIN


@dataclass(frozen=True, slots=True)
class MarkingPolyline:
    points: tuple[tuple[float, float, float], ...]
    family_hkl: Hkl
    domain_id: str
    kind: SurfaceMarkingKind = SurfaceMarkingKind.INDUCTION


def _unique_points(points, tolerance: float) -> tuple[np.ndarray, ...]:
    unique: list[np.ndarray] = []
    for raw in points:
        point = np.asarray(raw, dtype=float)
        if not any(np.linalg.norm(point - existing) <= tolerance for existing in unique):
            unique.append(point)
    return tuple(unique)


def _facet_plane_segment(
    facet: TwinFacet,
    normal: np.ndarray,
    offset: float,
    tolerance: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    polygon = np.asarray(facet.vertices, dtype=float)
    distances = polygon @ normal - offset
    if np.all(np.abs(distances) <= tolerance):
        return None
    crossings: list[np.ndarray] = [
        point for point, distance in zip(polygon, distances, strict=True)
        if abs(float(distance)) <= tolerance
    ]
    for index in range(len(polygon)):
        first = polygon[index]
        second = polygon[(index + 1) % len(polygon)]
        first_distance = float(distances[index])
        second_distance = float(distances[(index + 1) % len(polygon)])
        if first_distance * second_distance < -(tolerance**2):
            fraction = first_distance / (first_distance - second_distance)
            crossings.append(first + fraction * (second - first))
    unique = _unique_points(crossings, tolerance * 10.0)
    if len(unique) < 2:
        return None
    best: tuple[np.ndarray, np.ndarray] | None = None
    best_length = tolerance
    for index, first in enumerate(unique):
        for second in unique[index + 1:]:
            length = float(np.linalg.norm(second - first))
            if length > best_length:
                best = first, second
                best_length = length
    return best


def _segment_key(first: np.ndarray, second: np.ndarray) -> tuple[tuple[float, ...], tuple[float, ...]]:
    endpoints = sorted((tuple(np.round(first, 10)), tuple(np.round(second, 10))))
    return endpoints[0], endpoints[1]


def build_twin_striation(
    aggregate: TwinAggregate,
    *,
    tolerance: float = 1e-8,
) -> tuple[MarkingSegment, ...]:
    segments: list[MarkingSegment] = []
    seen: set[tuple[tuple[float, ...], tuple[float, ...]]] = set()
    facets = sorted(
        aggregate.external_facets,
        key=lambda facet: (facet.domain_id, facet.family_hkl, facet.parent_plane_hkl),
    )
    for plane in sorted(aggregate.composition_planes, key=lambda item: item.offset):
        normal = np.asarray(plane.normal, dtype=float)
        for facet in facets:
            pair = _facet_plane_segment(facet, normal, plane.offset, tolerance)
            if pair is None:
                continue
            first, second = pair
            key = _segment_key(first, second)
            if key in seen:
                continue
            seen.add(key)
            segments.append(
                MarkingSegment(
                    tuple(float(value) for value in first),
                    tuple(float(value) for value in second),
                    facet.family_hkl,
                    facet.domain_id,
                )
            )
    return tuple(segments)


def build_induction_contours(
    facets,
    marking: SurfaceMarking,
    *,
    display_epsilon: float | None = None,
) -> tuple[MarkingPolyline, ...]:
    if marking.kind is not SurfaceMarkingKind.INDUCTION:
        raise ValueError("Induction contours require an induction marking.")
    contours: list[MarkingPolyline] = []
    for facet in facets:
        if facet.family_hkl != marking.target_family:
            continue
        polygon = np.asarray(facet.vertices, dtype=float)
        if len(polygon) < 3:
            continue
        normal = np.asarray(facet.normal, dtype=float)
        length = float(np.linalg.norm(normal))
        if not math.isfinite(length) or length <= 1e-15:
            continue
        normal /= length
        centroid = np.mean(polygon, axis=0)
        scale = float(np.max(np.linalg.norm(polygon - centroid, axis=1)))
        epsilon = (
            max(scale, 1.0) * 1e-5
            if display_epsilon is None
            else float(display_epsilon)
        )
        if not math.isfinite(epsilon) or epsilon <= 0.0:
            raise ValueError("Contour display epsilon must be finite and positive.")
        for index in range(1, marking.density + 1):
            inset_scale = index / (marking.density + 1.0)
            inset = centroid + inset_scale * (polygon - centroid)
            displayed = inset + epsilon * normal
            closed = np.vstack((displayed, displayed[0]))
            contours.append(
                MarkingPolyline(
                    tuple(tuple(float(value) for value in point) for point in closed),
                    marking.target_family,
                    str(getattr(facet, "domain_id", "I")),
                )
            )
    return tuple(contours)


__all__ = [
    "MarkingPolyline",
    "MarkingSegment",
    "SurfaceMarking",
    "SurfaceMarkingKind",
    "build_induction_contours",
    "build_twin_striation",
]
