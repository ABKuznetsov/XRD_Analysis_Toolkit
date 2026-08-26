from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import ceil, floor

import numpy as np

from crystal_viewer.core.chemistry import COVALENT_RADII, SiteRole, site_radius, site_role
from crystal_viewer.core.model import AtomSite, CrystalStructure

if False:  # pragma: no cover - type-only import without a runtime cycle
    from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult


@dataclass(frozen=True, slots=True)
class DisplayAtom:
    site_index: int
    site: AtomSite
    fractional: tuple[float, float, float]
    cartesian: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class Bond:
    first: int
    second: int
    distance: float


@dataclass(slots=True)
class SceneData:
    atoms: list[DisplayAtom]
    bonds: list[Bond]
    cell_corners: np.ndarray
    cell_edges: list[tuple[int, int]]
    translations: tuple[tuple[float, float, float], ...]
    fractional_translations: tuple[tuple[int, int, int], ...]
    repeat: tuple[int, int, int]
    bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


BOUNDARY_ANIONS = frozenset({"O", "F", "Cl", "Br", "I", "S", "Se", "N"})


def _display_atoms(
    structure: CrystalStructure,
    bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    complete_boundary: bool,
    bond_tolerance: float,
) -> list[DisplayAtom]:
    atoms = []
    translation_ranges = tuple(
        range(floor(minimum), ceil(maximum))
        for minimum, maximum in bounds
    )
    for translation in product(*translation_ranges):
        for site_index, site in enumerate(structure.sites):
            fractional = tuple(site.fractional[i] + translation[i] for i in range(3))
            if not all(
                bounds[axis][0] - 1e-8 <= fractional[axis] < bounds[axis][1] - 1e-8
                for axis in range(3)
            ):
                continue
            cartesian = tuple(float(value) for value in structure.cell.frac_to_cart(fractional))
            atoms.append(DisplayAtom(site_index=site_index, site=site, fractional=fractional, cartesian=cartesian))
    if not complete_boundary or not atoms:
        return atoms
    interior_coordinates = np.asarray([atom.cartesian for atom in atoms])
    interior_radii = [site_radius(atom.site).value for atom in atoms]
    seen = {
        (atom.site_index, tuple(round(value, 7) for value in atom.fractional))
        for atom in atoms
    }
    boundary_ranges = tuple(
        range(floor(minimum) - 1, ceil(maximum) + 1)
        for minimum, maximum in bounds
    )
    for translation in product(*boundary_ranges):
        for site_index, site in enumerate(structure.sites):
            if site_role(site) is not SiteRole.ANION:
                continue
            fractional = tuple(site.fractional[axis] + translation[axis] for axis in range(3))
            if all(
                bounds[axis][0] - 1e-8 <= fractional[axis] < bounds[axis][1] - 1e-8
                for axis in range(3)
            ):
                continue
            key = (site_index, tuple(round(value, 7) for value in fractional))
            if key in seen:
                continue
            cartesian = np.asarray(structure.cell.frac_to_cart(fractional), dtype=float)
            distances = np.linalg.norm(interior_coordinates - cartesian, axis=1)
            ligand_radius = site_radius(site).value
            bonded = any(
                0.25 < distance
                <= (ligand_radius + radius) * bond_tolerance
                for distance, radius in zip(distances, interior_radii, strict=True)
            )
            if bonded:
                seen.add(key)
                atoms.append(
                    DisplayAtom(
                        site_index=site_index,
                        site=site,
                        fractional=fractional,
                        cartesian=tuple(float(value) for value in cartesian),
                    )
                )
    return atoms


def _bonds(atoms: list[DisplayAtom], tolerance: float, max_bonds: int = 20_000) -> list[Bond]:
    if len(atoms) < 2:
        return []
    coordinates = np.asarray([atom.cartesian for atom in atoms])
    bonds = []
    for first in range(len(atoms)):
        radii = site_radius(atoms[first].site).value
        deltas = coordinates[first + 1 :] - coordinates[first]
        distances = np.linalg.norm(deltas, axis=1)
        for offset in np.flatnonzero((distances > 0.25) & (distances <= 4.2)):
            second = first + 1 + int(offset)
            cutoff = (radii + site_radius(atoms[second].site).value) * tolerance
            distance = float(distances[offset])
            if distance <= cutoff:
                bonds.append(Bond(first, second, distance))
                if len(bonds) >= max_bonds:
                    return bonds
    return bonds


def _periodic_bonds(atoms: list[DisplayAtom], result: "PeriodicBondResult") -> list[Bond]:
    by_key: dict[tuple[int, tuple[int, int, int]], int] = {}
    for index, atom in enumerate(atoms):
        translation = tuple(
            int(round(atom.fractional[axis] - atom.site.fractional[axis]))
            for axis in range(3)
        )
        by_key[(atom.site_index, translation)] = index
    bonds: list[Bond] = []
    for first_index, first_atom in enumerate(atoms):
        first_translation = tuple(
            int(round(first_atom.fractional[axis] - first_atom.site.fractional[axis]))
            for axis in range(3)
        )
        for periodic in result.bonds:
            if first_atom.site_index != periodic.first:
                continue
            second_translation = tuple(
                first_translation[axis] + periodic.image[axis]
                for axis in range(3)
            )
            second_index = by_key.get((periodic.second, second_translation))
            if second_index is not None:
                bonds.append(Bond(first_index, second_index, periodic.distance))
    return bonds


def _cell_geometry(
    structure: CrystalStructure,
    bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    (amin, amax), (bmin, bmax), (cmin, cmax) = bounds
    fractional_corners = (
        (amin, bmin, cmin), (amax, bmin, cmin),
        (amax, bmax, cmin), (amin, bmax, cmin),
        (amin, bmin, cmax), (amax, bmin, cmax),
        (amax, bmax, cmax), (amin, bmax, cmax),
    )
    corners = np.asarray(
        [structure.cell.frac_to_cart(point) for point in fractional_corners],
        dtype=float,
    )
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    return corners, edges


def build_scene(
    structure: CrystalStructure,
    repeat: tuple[int, int, int] = (1, 1, 1),
    bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None = None,
    bond_tolerance: float = 1.18,
    include_bonds: bool = True,
    complete_boundary: bool = True,
    periodic_bonds: "PeriodicBondResult | None" = None,
) -> SceneData:
    if any(value < 1 for value in repeat):
        raise ValueError("Supercell repeat values must be at least one.")
    if bounds is None:
        bounds = tuple((0.0, float(value)) for value in repeat)
    bounds = tuple((float(pair[0]), float(pair[1])) for pair in bounds)
    if len(bounds) != 3 or any(minimum >= maximum for minimum, maximum in bounds):
        raise ValueError("Each cell-bound minimum must be smaller than its maximum.")
    atoms = _display_atoms(structure, bounds, complete_boundary, bond_tolerance)
    corners, edges = _cell_geometry(structure, bounds)
    translation_ranges = tuple(
        range(floor(minimum), ceil(maximum))
        for minimum, maximum in bounds
    )
    fractional_translations = tuple(product(*translation_ranges))
    translations = tuple(
        tuple(float(value) for value in structure.cell.frac_to_cart(translation))
        for translation in fractional_translations
    )
    return SceneData(
        atoms=atoms,
        bonds=(
            _periodic_bonds(atoms, periodic_bonds)
            if include_bonds and periodic_bonds is not None
            else _bonds(atoms, bond_tolerance)
            if include_bonds
            else []
        ),
        cell_corners=corners,
        cell_edges=edges,
        translations=translations,
        fractional_translations=fractional_translations,
        repeat=repeat,
        bounds=bounds,
    )
