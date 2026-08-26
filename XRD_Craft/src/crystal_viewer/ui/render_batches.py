from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Sequence

import numpy as np
import pyvista as pv


class DetailLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SPHERE_RESOLUTION = {
    DetailLevel.HIGH: (24, 24),
    DetailLevel.MEDIUM: (16, 16),
    DetailLevel.LOW: (10, 10),
}

CYLINDER_RESOLUTION = {
    DetailLevel.HIGH: 12,
    DetailLevel.MEDIUM: 9,
    DetailLevel.LOW: 6,
}


@dataclass(frozen=True, slots=True)
class SphereInstance:
    center: tuple[float, float, float]
    radius: float
    source_index: int


@dataclass(frozen=True, slots=True)
class OccupancySphereInstance:
    center: tuple[float, float, float]
    radius: float
    source_index: int
    sectors: tuple[tuple[tuple[int, int, int], float], ...]


@dataclass(frozen=True, slots=True)
class CylinderInstance:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    radius: float
    source_index: int


@dataclass(frozen=True, slots=True)
class GradientCylinderInstance:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    radius: float
    source_index: int
    start_rgb: tuple[int, int, int]
    end_rgb: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SurfaceInstance:
    surface: pv.PolyData
    translation: tuple[float, float, float]
    source_index: int


def group_spheres_by_material(
    items: Sequence[tuple[str, SphereInstance]],
) -> dict[str, list[SphereInstance]]:
    groups: dict[str, list[SphereInstance]] = {}
    for material, instance in items:
        groups.setdefault(material, []).append(instance)
    return groups


def detail_level_for_atom_count(atom_count: int) -> DetailLevel:
    if atom_count <= 500:
        return DetailLevel.HIGH
    if atom_count <= 2_000:
        return DetailLevel.MEDIUM
    return DetailLevel.LOW


@lru_cache(maxsize=3)
def _unit_sphere(detail: DetailLevel) -> pv.PolyData:
    theta, phi = SPHERE_RESOLUTION[detail]
    return pv.Sphere(radius=1.0, theta_resolution=theta, phi_resolution=phi)


@lru_cache(maxsize=3)
def _unit_cylinder(detail: DetailLevel) -> pv.PolyData:
    return pv.Cylinder(
        center=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
        radius=1.0,
        height=1.0,
        resolution=CYLINDER_RESOLUTION[detail],
        capping=True,
    )


def _offset_faces(faces: np.ndarray, point_offset: int) -> np.ndarray:
    shifted = np.asarray(faces, dtype=np.int64).copy()
    cursor = 0
    while cursor < len(shifted):
        size = int(shifted[cursor])
        shifted[cursor + 1 : cursor + 1 + size] += point_offset
        cursor += size + 1
    return shifted


def _assemble_polydata(
    parts: list[tuple[np.ndarray, np.ndarray, int, int]],
) -> pv.PolyData | None:
    if not parts:
        return None
    point_parts: list[np.ndarray] = []
    face_parts: list[np.ndarray] = []
    source_parts: list[np.ndarray] = []
    point_offset = 0
    for points, faces, cell_count, source_index in parts:
        point_parts.append(points)
        face_parts.append(_offset_faces(faces, point_offset))
        source_parts.append(np.full(cell_count, source_index, dtype=np.int64))
        point_offset += len(points)
    mesh = pv.PolyData(
        np.concatenate(point_parts, axis=0),
        faces=np.concatenate(face_parts),
    )
    mesh.cell_data["source_index"] = np.concatenate(source_parts)
    return mesh


def build_sphere_batch(
    instances: Sequence[SphereInstance],
    detail: DetailLevel,
) -> pv.PolyData | None:
    template = _unit_sphere(detail)
    parts: list[tuple[np.ndarray, np.ndarray, int, int]] = []
    for instance in instances:
        if instance.radius <= 0.0:
            continue
        points = (
            np.asarray(template.points) * float(instance.radius)
            + np.asarray(instance.center, dtype=float)
        )
        parts.append(
            (
                points,
                np.asarray(template.faces),
                template.n_cells,
                int(instance.source_index),
            )
        )
    return _assemble_polydata(parts)


def build_occupancy_sphere_batch(
    instances: Sequence[OccupancySphereInstance],
    detail: DetailLevel,
) -> pv.PolyData | None:
    """Build spheres divided into azimuthal sectors proportional to occupancy."""
    template = _unit_sphere(detail)
    template_points = np.asarray(template.points)
    cell_centres = np.asarray(template.cell_centers().points)
    azimuth = np.mod(np.arctan2(cell_centres[:, 1], cell_centres[:, 0]), 2.0 * np.pi)
    parts: list[tuple[np.ndarray, np.ndarray, int, int]] = []
    colour_parts: list[np.ndarray] = []
    for instance in instances:
        if instance.radius <= 0.0 or not instance.sectors:
            continue
        fractions = np.asarray([max(0.0, sector[1]) for sector in instance.sectors], dtype=float)
        total = float(fractions.sum())
        if total <= 0.0:
            continue
        fractions /= total
        boundaries = np.cumsum(fractions) * 2.0 * np.pi
        sector_indices = np.searchsorted(boundaries, azimuth, side="right")
        sector_indices = np.clip(sector_indices, 0, len(instance.sectors) - 1)
        palette = np.asarray([sector[0] for sector in instance.sectors], dtype=np.uint8)
        colour_parts.append(palette[sector_indices])
        parts.append(
            (
                template_points * float(instance.radius) + np.asarray(instance.center, dtype=float),
                np.asarray(template.faces),
                template.n_cells,
                int(instance.source_index),
            )
        )
    mesh = _assemble_polydata(parts)
    if mesh is not None:
        mesh.cell_data["occupancy_rgb"] = np.concatenate(colour_parts, axis=0)
    return mesh


def _rotation_from_z(direction: np.ndarray) -> np.ndarray:
    z_axis = np.asarray((0.0, 0.0, 1.0))
    cosine = float(np.clip(np.dot(z_axis, direction), -1.0, 1.0))
    if np.isclose(cosine, 1.0):
        return np.eye(3)
    if np.isclose(cosine, -1.0):
        return np.diag((1.0, -1.0, -1.0))
    cross = np.cross(z_axis, direction)
    sine = float(np.linalg.norm(cross))
    x, y, z = cross
    skew = np.asarray(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))
    return np.eye(3) + skew + skew @ skew * ((1.0 - cosine) / (sine * sine))


def build_cylinder_batch(
    instances: Sequence[CylinderInstance],
    detail: DetailLevel,
) -> pv.PolyData | None:
    template = _unit_cylinder(detail)
    parts: list[tuple[np.ndarray, np.ndarray, int, int]] = []
    for instance in instances:
        start = np.asarray(instance.start, dtype=float)
        end = np.asarray(instance.end, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        if length <= 1e-12 or instance.radius <= 0.0:
            continue
        direction = delta / length
        rotation = _rotation_from_z(direction)
        scaled = np.asarray(template.points) * np.asarray(
            (float(instance.radius), float(instance.radius), length)
        )
        points = scaled @ rotation.T + (start + end) / 2.0
        parts.append(
            (
                points,
                np.asarray(template.faces),
                template.n_cells,
                int(instance.source_index),
            )
        )
    return _assemble_polydata(parts)


def build_gradient_cylinder_batch(
    instances: Sequence[GradientCylinderInstance],
    detail: DetailLevel,
) -> pv.PolyData | None:
    """Build bonds whose endpoint colours are interpolated by the mapper."""
    template = _unit_cylinder(detail)
    parts: list[tuple[np.ndarray, np.ndarray, int, int]] = []
    colours: list[np.ndarray] = []
    template_points = np.asarray(template.points)
    z = template_points[:, 2]
    z_span = max(float(np.ptp(z)), 1e-12)
    axial = ((z - float(np.min(z))) / z_span)[:, None]
    for instance in instances:
        start = np.asarray(instance.start, dtype=float)
        end = np.asarray(instance.end, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        if length <= 1e-12 or instance.radius <= 0.0:
            continue
        rotation = _rotation_from_z(delta / length)
        scaled = template_points * np.asarray((instance.radius, instance.radius, length))
        points = scaled @ rotation.T + (start + end) / 2.0
        start_rgb = np.asarray(instance.start_rgb, dtype=float)
        end_rgb = np.asarray(instance.end_rgb, dtype=float)
        colours.append(np.rint(start_rgb + axial * (end_rgb - start_rgb)).astype(np.uint8))
        parts.append((points, np.asarray(template.faces), template.n_cells, instance.source_index))
    mesh = _assemble_polydata(parts)
    if mesh is not None:
        mesh.point_data["bond_rgb"] = np.concatenate(colours, axis=0)
    return mesh


def build_surface_batch(
    instances: Sequence[SurfaceInstance],
) -> pv.PolyData | None:
    parts: list[tuple[np.ndarray, np.ndarray, int, int]] = []
    normalized_surfaces: dict[int, pv.PolyData] = {}
    for instance in instances:
        if instance.surface.n_cells == 0:
            continue
        surface = normalized_surfaces.get(id(instance.surface))
        if surface is None:
            surface = (
                instance.surface.triangulate()
                if instance.surface.n_strips > 0
                else instance.surface
            )
            normalized_surfaces[id(instance.surface)] = surface
        points = (
            np.asarray(surface.points)
            + np.asarray(instance.translation, dtype=float)
        )
        parts.append(
            (
                points,
                np.asarray(surface.faces),
                surface.n_cells,
                int(instance.source_index),
            )
        )
    return _assemble_polydata(parts)
