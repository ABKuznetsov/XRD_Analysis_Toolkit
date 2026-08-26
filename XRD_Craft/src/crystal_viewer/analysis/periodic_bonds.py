from __future__ import annotations

import warnings as python_warnings
from dataclasses import dataclass
from itertools import product
from typing import Protocol

import numpy as np

from crystal_viewer.adapters import to_pymatgen
from crystal_viewer.core.chemistry import SiteRole, site_radius, site_role
from crystal_viewer.core.model import CrystalStructure


Translation = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class BondSettings:
    radius_tolerance: float = 1.18
    maximum_distance: float = 4.2
    minimum_crystalnn_weight: float = 0.5
    confirmed_additions: tuple[tuple[int, int, Translation], ...] = ()
    confirmed_removals: tuple[tuple[int, int, Translation], ...] = ()

    def __post_init__(self) -> None:
        if self.radius_tolerance <= 0.0:
            raise ValueError("radius_tolerance must be positive")
        if self.maximum_distance <= 0.0:
            raise ValueError("maximum_distance must be positive")
        if not 0.0 <= self.minimum_crystalnn_weight <= 1.0:
            raise ValueError("minimum_crystalnn_weight must be between 0 and 1")
        for first, second, image in self.confirmed_additions + self.confirmed_removals:
            if first < 0 or second < 0 or first == second:
                raise ValueError("confirmed bond site indices must be distinct and non-negative")
            if len(image) != 3 or any(isinstance(value, bool) or not isinstance(value, int) for value in image):
                raise ValueError("confirmed bond image must contain three integers")


@dataclass(frozen=True, slots=True)
class PeriodicBond:
    first: int
    second: int
    image: Translation
    distance: float
    weight: float
    method: str
    confidence: float
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PeriodicBondResult:
    bonds: tuple[PeriodicBond, ...]
    complete: bool
    warnings: tuple[str, ...] = ()
    method_version: str = "periodic-bonds-v1"


class NeighborFinder(Protocol):
    def get_nn_info(self, structure, index: int) -> list[dict[str, object]]: ...


def _primary_neighbours(finder: NeighborFinder, structure, index: int) -> list[dict[str, object]]:
    get_nn_data = getattr(finder, "get_nn_data", None)
    if callable(get_nn_data):
        data = get_nn_data(structure, index)
        if not data.cn_weights:
            return []
        coordination = max(
            data.cn_weights,
            key=lambda value: (float(data.cn_weights[value]), int(value)),
        )
        return list(data.cn_nninfo[coordination])
    return finder.get_nn_info(structure, index)


def _translation(value: object) -> Translation:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError("Periodic image must contain three finite values")
    rounded = np.rint(array).astype(int)
    if not np.allclose(array, rounded, atol=1e-7):
        raise ValueError("Periodic image must be integral")
    return tuple(int(item) for item in rounded)


def _canonical(first: int, second: int, image: Translation) -> tuple[int, int, Translation]:
    if first < second:
        return first, second, image
    if first > second:
        return second, first, tuple(-value for value in image)
    reverse = tuple(-value for value in image)
    return first, second, min(image, reverse)


def _distance(structure: CrystalStructure, first: int, second: int, image: Translation) -> float:
    delta = (
        np.asarray(structure.sites[second].fractional, dtype=float)
        + np.asarray(image, dtype=float)
        - np.asarray(structure.sites[first].fractional, dtype=float)
    )
    return float(np.linalg.norm(delta @ structure.cell.matrix))


def _fallback_for_site(
    structure: CrystalStructure,
    site_index: int,
    settings: BondSettings,
) -> list[PeriodicBond]:
    bonds: list[PeriodicBond] = []
    first_site = structure.sites[site_index]
    first_radius = site_radius(first_site)
    for other_index, other_site in enumerate(structure.sites):
        roles = {site_role(first_site), site_role(other_site)}
        if roles != {SiteRole.ANION, SiteRole.NON_ANION}:
            continue
        for image in product((-1, 0, 1), repeat=3):
            if site_index == other_index and image == (0, 0, 0):
                continue
            distance = _distance(structure, site_index, other_index, image)
            if not 0.25 < distance <= settings.maximum_distance:
                continue
            second_radius = site_radius(other_site)
            cutoff = (first_radius.value + second_radius.value) * settings.radius_tolerance
            if distance > cutoff:
                continue
            first, second, canonical_image = _canonical(site_index, other_index, image)
            normalized = min(1.0, max(0.0, distance / max(cutoff, 1e-12)))
            estimated = first_radius.estimated or second_radius.estimated
            warning = ("Estimated elemental radius used.",) if estimated else ()
            bonds.append(
                PeriodicBond(
                    first,
                    second,
                    canonical_image,
                    distance,
                    max(0.0, 1.0 - normalized),
                    "radius-fallback",
                    0.35 if estimated else 0.55,
                    warning,
                )
            )
    return bonds


def build_periodic_bonds(
    structure: CrystalStructure,
    settings: BondSettings | None = None,
    *,
    neighbor_finder: NeighborFinder | None = None,
) -> PeriodicBondResult:
    """Build one deterministic periodic bond graph for analysis and rendering."""
    from pymatgen.analysis.local_env import CrystalNN

    settings = settings or BondSettings()
    finder = neighbor_finder or CrystalNN(weighted_cn=True, cation_anion=False)
    messages: list[str] = []
    failed_sites: set[int] = set()
    by_key: dict[tuple[int, int, Translation], PeriodicBond] = {}
    try:
        pymatgen_structure = to_pymatgen(structure)
    except Exception as error:
        pymatgen_structure = None
        failed_sites.update(range(len(structure.sites)))
        messages.append(f"CrystalNN conversion failed: {error}")

    if pymatgen_structure is not None:
        with python_warnings.catch_warnings(record=True) as caught:
            python_warnings.simplefilter("always")
            for first_index in range(len(structure.sites)):
                try:
                    neighbours = _primary_neighbours(finder, pymatgen_structure, first_index)
                except Exception as error:
                    failed_sites.add(first_index)
                    messages.append(f"Site {first_index}: {error}")
                    continue
                for neighbour in neighbours:
                    second_index = int(neighbour["site_index"])
                    image = _translation(neighbour.get("image", (0, 0, 0)))
                    first, second, canonical_image = _canonical(first_index, second_index, image)
                    key = (first, second, canonical_image)
                    distance = _distance(structure, first, second, canonical_image)
                    weight = float(neighbour.get("weight", 1.0))
                    if not np.isfinite(weight):
                        weight = 0.0
                    if weight < settings.minimum_crystalnn_weight:
                        continue
                    candidate = PeriodicBond(
                        first,
                        second,
                        canonical_image,
                        distance,
                        weight,
                        "crystalnn",
                        float(np.clip(weight, 0.0, 1.0)),
                    )
                    previous = by_key.get(key)
                    if previous is None or candidate.weight > previous.weight:
                        by_key[key] = candidate
            messages.extend(str(item.message) for item in caught)

    for site_index in sorted(failed_sites):
        for candidate in _fallback_for_site(structure, site_index, settings):
            key = (candidate.first, candidate.second, candidate.image)
            previous = by_key.get(key)
            if previous is None or previous.method != "crystalnn":
                by_key[key] = candidate

    for first_index, second_index, image in settings.confirmed_additions:
        if first_index >= len(structure.sites) or second_index >= len(structure.sites):
            raise ValueError("confirmed bond references a site outside the structure")
        first, second, canonical_image = _canonical(first_index, second_index, image)
        distance = _distance(structure, first, second, canonical_image)
        by_key[(first, second, canonical_image)] = PeriodicBond(
            first,
            second,
            canonical_image,
            distance,
            1.0,
            "user-confirmed",
            1.0,
        )
    for first_index, second_index, image in settings.confirmed_removals:
        first, second, canonical_image = _canonical(first_index, second_index, image)
        by_key.pop((first, second, canonical_image), None)

    unique_messages = tuple(dict.fromkeys(message for message in messages if message))
    bonds = tuple(by_key[key] for key in sorted(by_key))
    return PeriodicBondResult(bonds=bonds, complete=True, warnings=unique_messages)


__all__ = [
    "BondSettings",
    "PeriodicBond",
    "PeriodicBondResult",
    "build_periodic_bonds",
]
