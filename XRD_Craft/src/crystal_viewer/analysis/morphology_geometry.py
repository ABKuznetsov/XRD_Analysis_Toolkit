from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import numpy as np
from scipy.spatial import ConvexHull, HalfspaceIntersection, QhullError

from crystal_viewer.analysis.morphology import Hkl, MorphologyPlane, reciprocal_normal
from crystal_viewer.core.model import UnitCell


class InvalidMorphologyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MorphologyFacet:
    family_hkl: Hkl
    plane_hkl: Hkl
    vertices: tuple[tuple[float, float, float], ...]
    normal: tuple[float, float, float]
    area: float


@dataclass(frozen=True, slots=True)
class MorphologyModel:
    planes: tuple[MorphologyPlane, ...]
    vertices: tuple[tuple[float, float, float], ...]
    facets: tuple[MorphologyFacet, ...]
    volume: float
    area_by_family: Mapping[Hkl, float]
    fraction_by_family: Mapping[Hkl, float]
    warnings: tuple[str, ...] = ()


def _ordered_polygon(
    points: np.ndarray,
    normal: np.ndarray,
) -> np.ndarray:
    centroid = np.mean(points, axis=0)
    offsets = points - centroid
    first = max(offsets, key=lambda value: float(np.linalg.norm(value)))
    first = first / np.linalg.norm(first)
    second = np.cross(normal, first)
    angles = np.arctan2(offsets @ second, offsets @ first)
    return points[np.argsort(angles)]


def _polygon_area(points: np.ndarray, normal: np.ndarray) -> float:
    shifted = points - np.mean(points, axis=0)
    area_vector = np.zeros(3, dtype=float)
    for first, second in zip(shifted, np.roll(shifted, -1, axis=0), strict=True):
        area_vector += np.cross(first, second)
    return abs(float(np.dot(area_vector, normal))) / 2.0


def _validate_bounded(normals: np.ndarray, tolerance: float) -> None:
    unique = np.unique(np.round(normals, 12), axis=0)
    if len(unique) < 4:
        raise InvalidMorphologyError("unbounded", "Active planes do not bound a three-dimensional volume.")
    try:
        hull = ConvexHull(unique)
    except QhullError as error:
        raise InvalidMorphologyError("unbounded", "Active plane normals do not span three dimensions.") from error
    if hull.volume <= tolerance or not np.all(hull.equations[:, -1] < -tolerance):
        raise InvalidMorphologyError("unbounded", "Active planes leave the morphology unbounded.")


def build_morphology_model(
    cell: UnitCell,
    planes: tuple[MorphologyPlane, ...] | list[MorphologyPlane],
    *,
    tolerance: float = 1e-8,
) -> MorphologyModel:
    plane_tuple = tuple(planes)
    if not plane_tuple:
        raise InvalidMorphologyError("empty", "No morphology planes are available.")

    active_distances: list[float] = []
    for plane in plane_tuple:
        if not math.isfinite(plane.rho) or plane.rho <= 0.0:
            raise InvalidMorphologyError(
                "invalid-distance",
                "All centre-to-plane distances must be finite and positive.",
            )
        if plane.enabled:
            active_distances.append(float(plane.rho))
    if not active_distances:
        raise InvalidMorphologyError("empty", "No active morphology planes are available.")
    distance_scale = max(active_distances)

    expanded: list[tuple[Hkl, Hkl, np.ndarray, float]] = []
    seen: set[tuple[float, ...]] = set()
    for plane in plane_tuple:
        if not plane.enabled:
            continue
        scaled_rho = float(plane.rho) / distance_scale
        for hkl in plane.family.equivalents:
            normal = reciprocal_normal(cell, hkl)
            key = (*np.round(normal, 12), round(scaled_rho, 12))
            if key in seen:
                continue
            seen.add(key)
            expanded.append((plane.family.hkl, hkl, normal, scaled_rho))

    normals = np.asarray([item[2] for item in expanded], dtype=float)
    _validate_bounded(normals, tolerance)
    halfspaces = np.asarray(
        [(*normal, -rho) for _family, _hkl, normal, rho in expanded],
        dtype=float,
    )
    try:
        intersection = HalfspaceIntersection(halfspaces, np.zeros(3, dtype=float))
        raw_vertices = np.asarray(intersection.intersections, dtype=float)
    except QhullError as error:
        raise InvalidMorphologyError("degenerate", "The plane intersection is numerically degenerate.") from error
    if len(raw_vertices) < 4 or not np.all(np.isfinite(raw_vertices)):
        raise InvalidMorphologyError("empty-intersection", "The active planes do not form a finite polyhedron.")

    normalized_vertices = np.unique(np.round(raw_vertices, 10), axis=0)
    try:
        hull = ConvexHull(normalized_vertices)
    except QhullError as error:
        raise InvalidMorphologyError("degenerate", "The morphology vertices are numerically degenerate.") from error

    facets: list[MorphologyFacet] = []
    area_by_family = {plane.family.hkl: 0.0 for plane in plane_tuple}
    for family_hkl, plane_hkl, normal, rho in expanded:
        distances = np.abs(normalized_vertices @ normal - rho)
        points = normalized_vertices[distances <= max(tolerance * 10.0, 1e-7)]
        if len(points) < 3:
            continue
        ordered = _ordered_polygon(points, normal)
        normalized_area = _polygon_area(ordered, normal)
        if normalized_area <= tolerance:
            continue
        area = normalized_area * distance_scale**2
        area_by_family[family_hkl] += area
        facets.append(
            MorphologyFacet(
                family_hkl,
                plane_hkl,
                tuple(
                    tuple(float(value * distance_scale) for value in point)
                    for point in ordered
                ),
                tuple(float(value) for value in normal),
                area,
            )
        )

    total_area = math.fsum(area_by_family.values())
    if total_area <= tolerance * distance_scale**2:
        raise InvalidMorphologyError("degenerate", "The morphology has no measurable facets.")
    fraction_by_family = {
        hkl: area / total_area if area > 0.0 else 0.0
        for hkl, area in area_by_family.items()
    }
    facets.sort(key=lambda facet: (facet.family_hkl, facet.plane_hkl))
    vertices = tuple(
        tuple(float(value * distance_scale) for value in point)
        for point in normalized_vertices
    )
    warnings = tuple(dict.fromkeys(plane.family.warning for plane in plane_tuple if plane.family.warning))
    return MorphologyModel(
        plane_tuple,
        vertices,
        tuple(facets),
        float(hull.volume * distance_scale**3),
        MappingProxyType(area_by_family),
        MappingProxyType(fraction_by_family),
        warnings,
    )


__all__ = [
    "InvalidMorphologyError",
    "MorphologyFacet",
    "MorphologyModel",
    "build_morphology_model",
]
