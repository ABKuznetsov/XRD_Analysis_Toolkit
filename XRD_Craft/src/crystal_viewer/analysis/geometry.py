from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import ConvexHull, QhullError

from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class GroupGeometry:
    center: tuple[float, float, float]
    bounding_box: tuple[float, float, float]
    volume: float
    surface_area: float
    principal_axes: np.ndarray


def analyze_atom_group(structure: CrystalStructure, atom_indices: tuple[int, ...]) -> GroupGeometry:
    if not atom_indices:
        raise ValueError("Atom group is empty.")
    coordinates = structure.cartesian_positions[list(atom_indices)]
    center = coordinates.mean(axis=0)
    spans = np.ptp(coordinates, axis=0)
    covariance = np.cov((coordinates - center).T) if len(coordinates) > 1 else np.eye(3)
    _values, vectors = np.linalg.eigh(np.atleast_2d(covariance))
    volume = 0.0
    area = 0.0
    if len(coordinates) >= 4:
        try:
            hull = ConvexHull(coordinates)
            volume = float(hull.volume)
            area = float(hull.area)
        except QhullError:
            pass
    return GroupGeometry(
        center=tuple(map(float, center)),
        bounding_box=tuple(map(float, spans)),
        volume=volume,
        surface_area=area,
        principal_axes=vectors,
    )

