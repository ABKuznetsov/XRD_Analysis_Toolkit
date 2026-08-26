from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import numpy as np

from crystal_viewer.analysis.morphology import Hkl, reciprocal_normal, reduce_hkl
from crystal_viewer.core.model import UnitCell


class TwinLawMode(str, Enum):
    REFLECTION = "reflection"
    TWOFOLD = "twofold"
    MATRIX = "matrix"


class TwinProvenance(str, Enum):
    MANUAL = "manual"
    CIF = "cif"


@dataclass(frozen=True, slots=True)
class TwinLaw:
    mode: TwinLawMode
    plane_hkl: Hkl | None = None
    axis_uvw: Hkl | None = None
    reciprocal_matrix: tuple[tuple[float, float, float], ...] | None = None
    provenance: TwinProvenance = TwinProvenance.MANUAL

    def __post_init__(self) -> None:
        mode = TwinLawMode(self.mode)
        provenance = TwinProvenance(self.provenance)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "provenance", provenance)
        if mode is TwinLawMode.REFLECTION:
            if self.plane_hkl is None or self.axis_uvw is not None or self.reciprocal_matrix is not None:
                raise ValueError("Reflection twin law requires only a nonzero K1 plane.")
            object.__setattr__(self, "plane_hkl", reduce_hkl(self.plane_hkl))
        elif mode is TwinLawMode.TWOFOLD:
            if self.axis_uvw is None or self.plane_hkl is not None or self.reciprocal_matrix is not None:
                raise ValueError("Twofold twin law requires only a nonzero [uvw] axis.")
            object.__setattr__(self, "axis_uvw", reduce_hkl(self.axis_uvw))
        else:
            if self.reciprocal_matrix is None or self.plane_hkl is not None or self.axis_uvw is not None:
                raise ValueError("Matrix twin law requires only a 3x3 reciprocal matrix.")
            matrix = np.asarray(self.reciprocal_matrix, dtype=float)
            if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
                raise ValueError("Twin matrix must contain nine finite values.")
            object.__setattr__(
                self,
                "reciprocal_matrix",
                tuple(tuple(float(value) for value in row) for row in matrix),
            )


def _validated_orthogonal(transform: np.ndarray, *, tolerance: float) -> np.ndarray:
    if transform.shape != (3, 3) or not np.all(np.isfinite(transform)):
        raise ValueError("Twin orientation must be a finite 3x3 matrix.")
    determinant = float(np.linalg.det(transform))
    if not math.isfinite(determinant) or abs(determinant) <= tolerance:
        raise ValueError("Twin orientation matrix is singular.")
    if not np.allclose(transform.T @ transform, np.eye(3), atol=tolerance, rtol=0.0):
        raise ValueError("Twin matrix is incompatible with the unit-cell metric.")
    if not math.isclose(abs(determinant), 1.0, abs_tol=tolerance, rel_tol=0.0):
        raise ValueError("Twin orientation determinant must have magnitude one.")
    result = np.asarray(transform, dtype=float)
    result.setflags(write=False)
    return result


def twin_cartesian_transform(
    cell: UnitCell,
    law: TwinLaw,
    *,
    tolerance: float = 1e-8,
) -> np.ndarray:
    if law.mode is TwinLawMode.REFLECTION:
        normal = reciprocal_normal(cell, law.plane_hkl)
        transform = np.eye(3) - 2.0 * np.outer(normal, normal)
    elif law.mode is TwinLawMode.TWOFOLD:
        axis = np.asarray(law.axis_uvw, dtype=float) @ cell.matrix
        length = float(np.linalg.norm(axis))
        if not math.isfinite(length) or length <= tolerance:
            raise ValueError("Twin axis is degenerate in the active unit cell.")
        axis /= length
        transform = 2.0 * np.outer(axis, axis) - np.eye(3)
    else:
        reciprocal_matrix = np.asarray(law.reciprocal_matrix, dtype=float)
        if abs(float(np.linalg.det(reciprocal_matrix))) <= tolerance:
            raise ValueError("Twin matrix is singular.")
        direct_basis = cell.matrix
        transform = np.linalg.inv(direct_basis) @ reciprocal_matrix @ direct_basis
    return _validated_orthogonal(transform, tolerance=tolerance)


def validate_distinct_twin(
    transform: np.ndarray,
    point_group_rotations: Iterable[np.ndarray],
    cell: UnitCell,
    *,
    tolerance: float = 1e-8,
) -> None:
    candidate = _validated_orthogonal(np.asarray(transform, dtype=float), tolerance=tolerance)
    cartesian_basis = cell.matrix.T
    inverse_basis = np.linalg.inv(cartesian_basis)
    for rotation in point_group_rotations:
        fractional = np.asarray(rotation, dtype=float)
        if fractional.shape != (3, 3):
            raise ValueError("Point-group rotation must be a 3x3 matrix.")
        cartesian = cartesian_basis @ fractional @ inverse_basis
        if np.allclose(candidate, cartesian, atol=tolerance, rtol=0.0):
            raise ValueError(
                "Twin operation belongs to the crystal symmetry; it does not create a distinct orientation."
            )


__all__ = [
    "TwinLaw",
    "TwinLawMode",
    "TwinProvenance",
    "twin_cartesian_transform",
    "validate_distinct_twin",
]
