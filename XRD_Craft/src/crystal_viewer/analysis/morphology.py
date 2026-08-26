from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
import cmath

import numpy as np

from crystal_viewer.core.model import CrystalStructure, UnitCell
from crystal_viewer.core.symmetry import parse_affine_operation

Hkl = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class ResolvedSymmetry:
    operations: tuple[str, ...]
    provenance: str
    warning: str = ""


@dataclass(frozen=True, slots=True)
class MillerFamily:
    hkl: Hkl
    equivalents: tuple[Hkl, ...]
    d_hkl: float
    allowed_order: int
    d_effective: float
    symmetry_source: str
    warning: str = ""


@dataclass(frozen=True, slots=True)
class MorphologyPlane:
    family: MillerFamily
    rho0: float
    rho: float
    enabled: bool = True
    manual: bool = False


def reduce_hkl(hkl: Iterable[int | float]) -> Hkl:
    values = tuple(float(value) for value in hkl)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("Miller index must contain three finite integers.")
    integers = tuple(int(round(value)) for value in values)
    if any(not math.isclose(value, integer, abs_tol=1e-9) for value, integer in zip(values, integers, strict=True)):
        raise ValueError("Miller indices must be integral.")
    divisor = math.gcd(*(abs(value) for value in integers))
    if divisor == 0:
        raise ValueError("Miller index (0, 0, 0) is invalid.")
    return tuple(value // divisor for value in integers)


def _reciprocal_vector(cell: UnitCell, hkl: Iterable[int | float]) -> np.ndarray:
    reduced = np.asarray(reduce_hkl(hkl), dtype=float)
    vector = reduced @ np.linalg.inv(cell.matrix).T
    length = float(np.linalg.norm(vector))
    if not math.isfinite(length) or length <= 1e-15:
        raise ValueError("Miller plane has a degenerate reciprocal normal.")
    return vector


def reciprocal_normal(cell: UnitCell, hkl: Iterable[int | float]) -> np.ndarray:
    vector = _reciprocal_vector(cell, hkl)
    return vector / np.linalg.norm(vector)


def interplanar_spacing(cell: UnitCell, hkl: Iterable[int | float]) -> float:
    return 1.0 / float(np.linalg.norm(_reciprocal_vector(cell, hkl)))


def equivalent_hkls(hkl: Iterable[int | float], operations: Iterable[str]) -> tuple[Hkl, ...]:
    source = np.asarray(reduce_hkl(hkl), dtype=float)
    equivalents: set[Hkl] = set()
    for text in operations:
        operation = parse_affine_operation(text)
        transformed = np.linalg.inv(operation.rotation).T @ source
        equivalents.add(reduce_hkl(transformed))
    if not equivalents:
        equivalents.add(reduce_hkl(source))
    return tuple(sorted(equivalents))


def reflection_is_systematically_absent(
    hkl: Iterable[int | float],
    operations: Iterable[str],
    tolerance: float = 1e-8,
) -> bool:
    return reflection_is_systematically_absent_ordered(hkl, operations, tolerance)


def first_allowed_order(
    hkl: Iterable[int | float],
    operations: Iterable[str],
    max_order: int = 12,
) -> int | None:
    primitive = reduce_hkl(hkl)
    if max_order < 1:
        raise ValueError("Maximum reflection order must be positive.")
    operation_tuple = tuple(operations)
    for order in range(1, int(max_order) + 1):
        ordered = tuple(order * value for value in primitive)
        if not reflection_is_systematically_absent_ordered(ordered, operation_tuple):
            return order
    return None


def reflection_is_systematically_absent_ordered(
    hkl: Iterable[int | float],
    operations: Iterable[str],
    tolerance: float = 1e-8,
) -> bool:
    values = tuple(float(value) for value in hkl)
    if len(values) != 3 or not all(math.isfinite(value) and math.isclose(value, round(value)) for value in values):
        raise ValueError("Reflection index must contain three finite integers.")
    indices = np.asarray(tuple(int(round(value)) for value in values), dtype=int)
    if not np.any(indices):
        raise ValueError("Reflection index (0, 0, 0) is invalid.")
    coefficients: dict[Hkl, complex] = {}
    seen: set[tuple[tuple[int, ...], tuple[float, ...]]] = set()
    for text in operations:
        operation = parse_affine_operation(text)
        key = (
            tuple(int(value) for value in operation.rotation.flat),
            tuple(round(float(value % 1.0), 12) for value in operation.translation),
        )
        if key in seen:
            continue
        seen.add(key)
        transformed = tuple(int(value) for value in operation.rotation.T @ indices)
        phase = float(np.dot(indices, operation.translation))
        coefficients[transformed] = coefficients.get(transformed, 0j) + cmath.exp(2j * math.pi * phase)
    return bool(coefficients) and all(abs(value) <= tolerance for value in coefficients.values())


def _has_explicit_symmetry_loop(structure: CrystalStructure) -> bool:
    symmetry_tags = {"_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"}
    return any(symmetry_tags.intersection(loop.tags) for loop in structure.source_data.loops)


def resolve_symmetry_operations(structure: CrystalStructure) -> ResolvedSymmetry:
    provided = tuple(text for text in structure.symmetry_operations if str(text).strip()) or ("x,y,z",)
    if _has_explicit_symmetry_loop(structure) or provided != ("x,y,z",):
        return ResolvedSymmetry(provided, "cif-loop")
    if structure.space_group.strip():
        try:
            from pymatgen.symmetry.groups import SpaceGroup

            group = SpaceGroup(structure.space_group)
            operations = tuple(sorted(operation.as_xyz_str() for operation in group.symmetry_ops))
            if operations:
                return ResolvedSymmetry(operations, "space-group-symbol")
        except (ImportError, KeyError, ValueError):
            pass
    return ResolvedSymmetry(
        ("x,y,z",),
        "identity-fallback",
        "Full space-group symmetry is unavailable; using the identity operation only.",
    )


def build_bfdh_planes(structure: CrystalStructure, max_index: int = 3) -> tuple[MorphologyPlane, ...]:
    if not 1 <= int(max_index) <= 12:
        raise ValueError("max_index must be between 1 and 12.")
    symmetry = resolve_symmetry_operations(structure)
    candidates = {
        reduce_hkl((h, k, l))
        for h in range(-int(max_index), int(max_index) + 1)
        for k in range(-int(max_index), int(max_index) + 1)
        for l in range(-int(max_index), int(max_index) + 1)
        if (h, k, l) != (0, 0, 0)
    }
    remaining = set(candidates)
    families: list[MillerFamily] = []
    while remaining:
        seed = min(remaining)
        equivalents = equivalent_hkls(seed, symmetry.operations)
        remaining.difference_update(equivalents)
        representative = min(equivalents)
        order = first_allowed_order(representative, symmetry.operations)
        if order is None:
            continue
        spacing = interplanar_spacing(structure.cell, representative)
        families.append(
            MillerFamily(
                representative,
                equivalents,
                spacing,
                order,
                spacing / order,
                symmetry.provenance,
                symmetry.warning,
            )
        )
    if not families:
        return ()
    raw_distances = [1.0 / family.d_effective for family in families]
    scale = min(raw_distances)
    planes = [
        MorphologyPlane(family, raw / scale, raw / scale)
        for family, raw in zip(families, raw_distances, strict=True)
    ]
    return tuple(sorted(planes, key=lambda plane: (plane.rho0, plane.family.hkl)))


__all__ = [
    "Hkl",
    "MillerFamily",
    "MorphologyPlane",
    "ResolvedSymmetry",
    "build_bfdh_planes",
    "equivalent_hkls",
    "first_allowed_order",
    "interplanar_spacing",
    "reciprocal_normal",
    "reduce_hkl",
    "reflection_is_systematically_absent",
    "resolve_symmetry_operations",
]
