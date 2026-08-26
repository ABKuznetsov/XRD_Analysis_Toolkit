from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from crystal_viewer.analysis.morphology import Hkl, reciprocal_normal
from crystal_viewer.analysis.morphology_geometry import MorphologyModel
from crystal_viewer.analysis.twin_law import twin_cartesian_transform
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec
from crystal_viewer.core.model import UnitCell


class InvalidTwinGeometryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TwinFacet:
    family_hkl: Hkl
    parent_plane_hkl: Hkl
    display_hkl: Hkl
    vertices: tuple[tuple[float, float, float], ...]
    normal: tuple[float, float, float]
    area: float
    domain_id: str


@dataclass(frozen=True, slots=True)
class TwinDomain:
    domain_id: str
    orientation: tuple[tuple[float, float, float], ...]
    translation: tuple[float, float, float]
    facets: tuple[TwinFacet, ...]
    vertices: tuple[tuple[float, float, float], ...]
    orientation_state: str = "I"
    slab_interval: tuple[float, float] | None = None
    slab_index: int | None = None


@dataclass(frozen=True, slots=True)
class CompositionPlane:
    normal: tuple[float, float, float]
    offset: float
    polygon: tuple[tuple[float, float, float], ...]
    hkl: Hkl


@dataclass(frozen=True, slots=True)
class TwinAggregate:
    domains: tuple[TwinDomain, ...]
    external_facets: tuple[TwinFacet, ...]
    composition_planes: tuple[CompositionPlane, ...]
    warnings: tuple[str, ...] = ()


def _as_tuple(vector: np.ndarray) -> tuple[float, float, float]:
    return tuple(float(value) for value in vector)


def _matrix_tuple(matrix: np.ndarray) -> tuple[tuple[float, float, float], ...]:
    return tuple(_as_tuple(row) for row in matrix)


def _polygon_area(points: np.ndarray, normal: np.ndarray) -> float:
    area_vector = np.zeros(3, dtype=float)
    for first, second in zip(points, np.roll(points, -1, axis=0), strict=True):
        area_vector += np.cross(first, second)
    return abs(float(np.dot(area_vector, normal))) / 2.0


def _ordered_polygon(points: np.ndarray, normal: np.ndarray) -> np.ndarray:
    centroid = np.mean(points, axis=0)
    offsets = points - centroid
    first = offsets[int(np.argmax(np.linalg.norm(offsets, axis=1)))]
    first /= np.linalg.norm(first)
    second = np.cross(normal, first)
    angles = np.arctan2(offsets @ second, offsets @ first)
    return points[np.argsort(angles)]


def _unique_points(points, tolerance: float) -> np.ndarray:
    unique: list[np.ndarray] = []
    for raw in points:
        point = np.asarray(raw, dtype=float)
        if not any(np.linalg.norm(point - existing) <= tolerance for existing in unique):
            unique.append(point)
    if not unique:
        return np.empty((0, 3), dtype=float)
    return np.asarray(unique, dtype=float)


def _transform_domain(
    morphology: MorphologyModel,
    domain_id: str,
    orientation: np.ndarray,
    translation: np.ndarray,
    *,
    orientation_state: str | None = None,
    slab_interval: tuple[float, float] | None = None,
    slab_index: int | None = None,
) -> TwinDomain:
    vertices = np.asarray(morphology.vertices, dtype=float) @ orientation.T + translation
    facets: list[TwinFacet] = []
    for facet in morphology.facets:
        transformed_vertices = np.asarray(facet.vertices, dtype=float) @ orientation.T + translation
        transformed_normal = orientation @ np.asarray(facet.normal, dtype=float)
        facets.append(
            TwinFacet(
                facet.family_hkl,
                facet.plane_hkl,
                facet.plane_hkl,
                tuple(_as_tuple(point) for point in transformed_vertices),
                _as_tuple(transformed_normal),
                facet.area,
                domain_id,
            )
        )
    return TwinDomain(
        domain_id,
        _matrix_tuple(orientation),
        _as_tuple(translation),
        tuple(facets),
        tuple(_as_tuple(point) for point in vertices),
        domain_id if orientation_state is None else orientation_state,
        slab_interval,
        slab_index,
    )


def _clip_polygon(
    points: np.ndarray,
    normal: np.ndarray,
    offset: float,
    *,
    keep_below: bool,
    tolerance: float,
) -> np.ndarray:
    if len(points) < 3:
        return np.empty((0, 3), dtype=float)

    def signed(point: np.ndarray) -> float:
        value = float(np.dot(normal, point) - offset)
        return value if keep_below else -value

    result: list[np.ndarray] = []
    previous = points[-1]
    previous_distance = signed(previous)
    previous_inside = previous_distance <= tolerance
    for current in points:
        current_distance = signed(current)
        current_inside = current_distance <= tolerance
        if current_inside != previous_inside:
            denominator = previous_distance - current_distance
            if abs(denominator) > tolerance:
                fraction = previous_distance / denominator
                result.append(previous + fraction * (current - previous))
        if current_inside:
            result.append(current)
        previous = current
        previous_distance = current_distance
        previous_inside = current_inside
    return _unique_points(result, tolerance)


def _clip_domain(
    domain: TwinDomain,
    normal: np.ndarray,
    offset: float,
    *,
    keep_below: bool,
    tolerance: float,
) -> tuple[TwinDomain, np.ndarray]:
    clipped_facets: list[TwinFacet] = []
    boundary_points: list[np.ndarray] = []
    all_points: list[np.ndarray] = []
    for facet in domain.facets:
        facet_normal = np.asarray(facet.normal, dtype=float)
        clipped = _clip_polygon(
            np.asarray(facet.vertices, dtype=float),
            normal,
            offset,
            keep_below=keep_below,
            tolerance=tolerance,
        )
        if len(clipped) < 3:
            continue
        area = _polygon_area(clipped, facet_normal)
        if area <= tolerance:
            continue
        all_points.extend(clipped)
        boundary_points.extend(
            point
            for point in clipped
            if abs(float(np.dot(normal, point) - offset)) <= tolerance * 10.0
        )
        clipped_facets.append(
            TwinFacet(
                facet.family_hkl,
                facet.parent_plane_hkl,
                facet.display_hkl,
                tuple(_as_tuple(point) for point in clipped),
                facet.normal,
                area,
                domain.domain_id,
            )
        )
    boundary = _unique_points(boundary_points, tolerance * 10.0)
    vertices = _unique_points(all_points, tolerance * 10.0)
    if len(vertices) < 4 or len(boundary) < 3:
        raise InvalidTwinGeometryError(
            "composition-miss",
            "The composition plane does not produce a finite section through both individuals.",
        )
    ordered_boundary = _ordered_polygon(boundary, normal)
    return (
        TwinDomain(
            domain.domain_id,
            domain.orientation,
            domain.translation,
            tuple(clipped_facets),
            tuple(_as_tuple(point) for point in vertices),
            domain.orientation_state,
            domain.slab_interval,
            domain.slab_index,
        ),
        ordered_boundary,
    )


def _shared_section(first: np.ndarray, second: np.ndarray, normal: np.ndarray, tolerance: float) -> np.ndarray:
    # Both sections are convex and coplanar. Clip the first section successively
    # by the inward half-planes of the second in a shared 2D coordinate system.
    all_points = np.vstack((first, second))
    origin = np.mean(all_points, axis=0)
    axis_u = first[0] - origin
    axis_u -= normal * float(np.dot(axis_u, normal))
    if np.linalg.norm(axis_u) <= tolerance:
        axis_u = first[1] - first[0]
    axis_u /= np.linalg.norm(axis_u)
    axis_v = np.cross(normal, axis_u)

    def to_2d(points: np.ndarray) -> np.ndarray:
        shifted = points - origin
        return np.column_stack((shifted @ axis_u, shifted @ axis_v))

    subject = to_2d(first)
    clipper = to_2d(second)
    signed_area = 0.5 * float(
        np.sum(clipper[:, 0] * np.roll(clipper[:, 1], -1) - clipper[:, 1] * np.roll(clipper[:, 0], -1))
    )
    orientation = 1.0 if signed_area >= 0.0 else -1.0
    output = subject
    for edge_start, edge_end in zip(clipper, np.roll(clipper, -1, axis=0), strict=True):
        edge = edge_end - edge_start

        def inside(point: np.ndarray) -> bool:
            cross = edge[0] * (point[1] - edge_start[1]) - edge[1] * (point[0] - edge_start[0])
            return orientation * cross >= -tolerance

        result: list[np.ndarray] = []
        if len(output) == 0:
            break
        previous = output[-1]
        previous_inside = inside(previous)
        for current in output:
            current_inside = inside(current)
            if current_inside != previous_inside:
                segment = current - previous
                denominator = edge[0] * segment[1] - edge[1] * segment[0]
                if abs(denominator) > tolerance:
                    delta = edge_start - previous
                    fraction = (edge[0] * delta[1] - edge[1] * delta[0]) / denominator
                    result.append(previous + fraction * segment)
            if current_inside:
                result.append(current)
            previous = current
            previous_inside = current_inside
        output = np.asarray(result, dtype=float)
    if len(output) < 3:
        raise InvalidTwinGeometryError(
            "composition-miss",
            "The individuals have no shared bounded composition-plane polygon.",
        )
    shared = origin + output[:, :1] * axis_u + output[:, 1:] * axis_v
    return _ordered_polygon(_unique_points(shared, tolerance * 10.0), normal)


def build_twin_aggregate(
    cell: UnitCell,
    morphology: MorphologyModel,
    spec: TwinAggregateSpec,
    *,
    tolerance: float = 1e-8,
) -> TwinAggregate:
    identity = np.eye(3, dtype=float)
    transform = twin_cartesian_transform(cell, spec.law, tolerance=tolerance)
    parent = _transform_domain(morphology, "I", identity, np.zeros(3, dtype=float))
    twin = _transform_domain(
        morphology,
        "II",
        transform,
        np.asarray(spec.second_translation, dtype=float),
    )

    if spec.kind is TwinAggregateKind.PENETRATION:
        warning = (
            "Penetration twin is a geometrical intergrowth visualization; "
            "it is not a reconstructed external equilibrium surface."
        )
        return TwinAggregate(
            (parent, twin),
            parent.facets + twin.facets,
            (),
            (warning,),
        )
    plane_hkl = spec.resolved_composition_plane_hkl
    normal = reciprocal_normal(cell, plane_hkl)
    offset = spec.composition_offset
    if spec.kind is TwinAggregateKind.POLYSYNTHETIC:
        projections = np.concatenate(
            (
                np.asarray(parent.vertices, dtype=float) @ normal,
                np.asarray(twin.vertices, dtype=float) @ normal,
            )
        )
        low = float(np.min(projections))
        high = float(np.max(projections))
        if not math.isfinite(low) or not math.isfinite(high) or high - low <= tolerance:
            raise InvalidTwinGeometryError(
                "lamella-range",
                "The twin individuals have no finite span along the lamella normal.",
            )
        weights = tuple(
            spec.lamella_ratio if index % 2 == 0 else 1.0 - spec.lamella_ratio
            for index in range(spec.lamella_count)
        )
        scale = (high - low) / math.fsum(weights)
        boundaries = [low]
        for weight in weights:
            boundaries.append(boundaries[-1] + weight * scale)
        boundaries[-1] = high

        domains: list[TwinDomain] = []
        for index, (lower, upper) in enumerate(
            zip(boundaries, boundaries[1:]),
            start=1,
        ):
            state = "I" if index % 2 == 1 else "II"
            orientation = identity if state == "I" else transform
            translation = np.zeros(3, dtype=float) if state == "I" else np.asarray(
                spec.second_translation, dtype=float
            )
            source = _transform_domain(
                morphology,
                f"L{index}",
                orientation,
                translation,
                orientation_state=state,
                slab_interval=(float(lower), float(upper)),
                slab_index=index,
            )
            try:
                clipped, _lower_section = _clip_domain(
                    source,
                    normal,
                    lower,
                    keep_below=False,
                    tolerance=tolerance,
                )
                clipped, _upper_section = _clip_domain(
                    clipped,
                    normal,
                    upper,
                    keep_below=True,
                    tolerance=tolerance,
                )
            except InvalidTwinGeometryError:
                continue
            domains.append(clipped)
        if not domains:
            raise InvalidTwinGeometryError(
                "empty-lamellae",
                "The requested lamella stack does not intersect either twin individual.",
            )

        composition_planes: list[CompositionPlane] = []
        for left, right in zip(domains, domains[1:]):
            if (
                left.slab_index is None
                or right.slab_index != left.slab_index + 1
                or left.slab_interval is None
                or right.slab_interval is None
            ):
                continue
            boundary = left.slab_interval[1]
            if not math.isclose(boundary, right.slab_interval[0], abs_tol=tolerance):
                continue
            left_points = _unique_points(
                (
                    point
                    for point in left.vertices
                    if abs(float(np.dot(normal, point) - boundary)) <= tolerance * 10.0
                ),
                tolerance * 10.0,
            )
            right_points = _unique_points(
                (
                    point
                    for point in right.vertices
                    if abs(float(np.dot(normal, point) - boundary)) <= tolerance * 10.0
                ),
                tolerance * 10.0,
            )
            if len(left_points) < 3 or len(right_points) < 3:
                continue
            shared = _shared_section(
                _ordered_polygon(left_points, normal),
                _ordered_polygon(right_points, normal),
                normal,
                tolerance,
            )
            composition_planes.append(
                CompositionPlane(
                    _as_tuple(normal),
                    float(boundary),
                    tuple(_as_tuple(point) for point in shared),
                    plane_hkl,
                )
            )
        return TwinAggregate(
            tuple(domains),
            tuple(facet for domain in domains for facet in domain.facets),
            tuple(composition_planes),
        )

    if spec.kind is not TwinAggregateKind.CONTACT:
        raise InvalidTwinGeometryError("unsupported-kind", "Unsupported twin aggregate kind.")

    for domain in (parent, twin):
        projections = np.asarray(domain.vertices, dtype=float) @ normal
        if np.min(projections) >= offset - tolerance or np.max(projections) <= offset + tolerance:
            raise InvalidTwinGeometryError(
                "composition-miss",
                "The composition plane must intersect both twin individuals.",
            )

    clipped_parent, parent_section = _clip_domain(
        parent,
        normal,
        offset,
        keep_below=True,
        tolerance=tolerance,
    )
    clipped_twin, twin_section = _clip_domain(
        twin,
        normal,
        offset,
        keep_below=False,
        tolerance=tolerance,
    )
    shared = _shared_section(parent_section, twin_section, normal, tolerance)
    plane = CompositionPlane(
        _as_tuple(normal),
        float(offset),
        tuple(_as_tuple(point) for point in shared),
        plane_hkl,
    )
    return TwinAggregate(
        (clipped_parent, clipped_twin),
        clipped_parent.facets + clipped_twin.facets,
        (plane,),
    )


__all__ = [
    "CompositionPlane",
    "InvalidTwinGeometryError",
    "TwinAggregate",
    "TwinDomain",
    "TwinFacet",
    "build_twin_aggregate",
]
