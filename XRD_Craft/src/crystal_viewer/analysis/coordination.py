from __future__ import annotations

import math
import time
from collections import defaultdict
from itertools import product
from typing import Protocol

import numpy as np

from crystal_viewer.adapters import to_pymatgen
from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult
from crystal_viewer.analysis.structural_analysis import (
    CoordinationCandidate,
    CoordinationEnvironment,
    StructuralAnalysisSettings,
)
from crystal_viewer.core.chemistry import SiteRole, site_role
from crystal_viewer.core.model import CrystalStructure
from crystal_viewer.core.site_orbits import site_orbit_key


class GeometryFinder(Protocol):
    def compute_coordination_environments(self, structure, **kwargs): ...


def _primary_memberships(
    structure: CrystalStructure,
    periodic_bonds: PeriodicBondResult,
) -> dict[int, tuple[tuple[int, tuple[int, int, int]], ...]]:
    memberships: dict[int, set[tuple[int, tuple[int, int, int]]]] = defaultdict(set)
    for bond in periodic_bonds.bonds:
        memberships[bond.first].add((bond.second, bond.image))
        memberships[bond.second].add((bond.first, tuple(-value for value in bond.image)))
    return {
        center: tuple(sorted(neighbours, key=lambda item: (item[0], item[1])))
        for center, neighbours in memberships.items()
        if neighbours and site_role(structure.sites[center]) is not SiteRole.ANION
    }


def _coordination_number(symbol: str) -> int | None:
    try:
        value = int(symbol.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None
    return value if value > 0 else None


def _secondary_anion_shell(
    structure: CrystalStructure,
    center_index: int,
    primary: tuple[tuple[int, tuple[int, int, int]], ...],
    maximum_distance: float,
) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    """Find a complete, symmetry-like second shell without element-specific rules."""
    if len(primary) < 3 or any(
        site_role(structure.sites[index]) is not SiteRole.ANION
        for index, _image in primary
    ):
        return ()
    matrix = np.asarray(structure.cell.matrix, dtype=float)
    center = np.asarray(structure.sites[center_index].fractional, dtype=float)

    def separation(index: int, image: tuple[int, int, int]) -> float:
        delta = (
            np.asarray(structure.sites[index].fractional, dtype=float)
            + np.asarray(image, dtype=float)
            - center
        )
        return float(np.linalg.norm(delta @ matrix))

    primary_keys = set(primary)
    primary_distances = tuple(separation(index, image) for index, image in primary)
    primary_mean = math.fsum(primary_distances) / len(primary_distances)
    primary_limit = max(primary_distances)
    gap = max(0.05, primary_limit * 0.02)
    candidates: list[tuple[float, int, tuple[int, int, int]]] = []
    for index, site in enumerate(structure.sites):
        if site_role(site) is not SiteRole.ANION:
            continue
        for image in product((-1, 0, 1), repeat=3):
            key = (index, image)
            if key in primary_keys:
                continue
            distance = separation(index, image)
            if primary_limit + gap < distance <= maximum_distance:
                candidates.append((distance, index, image))
    if not candidates:
        return ()
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    shell_start = candidates[0][0]
    shell_tolerance = max(0.08, shell_start * 0.03)
    shell = tuple(
        item for item in candidates if item[0] <= shell_start + shell_tolerance
    )
    if len(shell) != len(primary):
        return ()
    distances = tuple(item[0] for item in shell)
    secondary_mean = math.fsum(distances) / len(distances)
    relative_spread = float(np.std(distances) / secondary_mean)
    if relative_spread > 0.06 or secondary_mean > primary_mean * 1.4:
        return ()
    return tuple((index, image) for _distance, index, image in shell)


def _geometry_name(symbol: str) -> str:
    try:
        from pymatgen.analysis.chemenv.coordination_environments.coordination_geometries import (
            AllCoordinationGeometries,
        )

        geometry = AllCoordinationGeometries().get_geometry_from_mp_symbol(symbol)
        return str(geometry.name)
    except Exception:
        return symbol


_ORDER_PARAMETERS = {
    2: (("bent", "A:2", "Angular"),),
    3: (("tri_plan", "TL:3", "Trigonal plane"), ("tri_pyr", "TY:3", "Trigonal pyramid")),
    4: (
        ("tet", "T:4", "Tetrahedron"),
        ("sq_plan", "S:4", "Square plane"),
        ("see_saw_rect", "SS:4", "See-saw"),
    ),
    5: (("sq_pyr", "S:5", "Square pyramid"), ("tri_bipyr", "T:5", "Trigonal bipyramid")),
    6: (("oct", "O:6", "Octahedron"), ("pent_pyr", "PP:6", "Pentagonal pyramid")),
    8: (("bcc", "C:8", "Cubic"),),
    12: (("cuboct", "C:12", "Cuboctahedron"),),
}


def _local_order_candidates(
    structure: CrystalStructure,
    center_index: int,
    neighbours: tuple[tuple[int, tuple[int, int, int]], ...],
) -> list[CoordinationCandidate]:
    definitions = _ORDER_PARAMETERS.get(len(neighbours), ())
    if not definitions:
        return []
    try:
        from pymatgen.analysis.local_env import LocalStructOrderParams
        from pymatgen.core import Molecule

        center = structure.sites[center_index]
        center_cart = structure.cell.frac_to_cart(center.fractional)
        species = [center.components[0].element]
        coordinates = [center_cart]
        for neighbour_index, image in neighbours:
            neighbour = structure.sites[neighbour_index]
            species.append(neighbour.components[0].element)
            fractional = np.asarray(neighbour.fractional, dtype=float) + np.asarray(image, dtype=float)
            coordinates.append(structure.cell.frac_to_cart(fractional))
        molecule = Molecule(species, coordinates)
        parameters = [item[0] for item in definitions]
        values = LocalStructOrderParams(parameters).get_order_parameters(
            molecule,
            0,
            indices_neighs=list(range(1, len(neighbours) + 1)),
        )
    except Exception:
        return []
    candidates = [
        CoordinationCandidate(
            symbol=symbol,
            name=name,
            fraction=float(np.clip(value, 0.0, 1.0)),
            csm=float(max(0.0, 100.0 * (1.0 - float(value)))),
            method="local-order-fallback",
        )
        for (_, symbol, name), value in zip(definitions, values, strict=True)
        if value is not None and math.isfinite(float(value))
    ]
    candidates.sort(key=lambda item: (-item.fraction, item.csm, item.symbol))
    return candidates


def describe_coordination(
    structure: CrystalStructure,
    periodic_bonds: PeriodicBondResult,
    settings: StructuralAnalysisSettings,
    *,
    geometry_finder: GeometryFinder | None = None,
) -> tuple[CoordinationEnvironment, ...]:
    """Describe local geometry while preserving primary periodic-bond membership."""
    settings.validate()
    memberships = _primary_memberships(structure, periodic_bonds)
    if not memberships:
        return ()
    secondary_shell_centers: set[int] = set()
    augmented_memberships = {}
    for center_index, primary in memberships.items():
        secondary = _secondary_anion_shell(
            structure,
            center_index,
            primary,
            settings.bond_settings.maximum_distance,
        )
        if secondary:
            secondary_shell_centers.add(center_index)
        augmented_memberships[center_index] = (*primary, *secondary)
    memberships = augmented_memberships

    # ChemEnv is comparatively expensive.  Symmetry-expanded structures can
    # contain dozens of copies of the same asymmetric coordination site, so
    # evaluate one representative for every chemically identical orbit and
    # retain the individual periodic neighbour membership for each copy.
    representative_for: dict[int, int] = {}
    representatives: dict[tuple[str, tuple[str, ...]], int] = {}
    for center_index in sorted(memberships):
        neighbours = memberships[center_index]
        signature = (
            site_orbit_key(structure.sites[center_index].label),
            tuple(
                sorted(
                    site_orbit_key(structure.sites[index].label)
                    for index, _image in neighbours
                )
            ),
        )
        representative_for[center_index] = representatives.setdefault(
            signature,
            center_index,
        )
    if geometry_finder is None:
        from pymatgen.analysis.chemenv.coordination_environments.coordination_geometry_finder import (
            LocalGeometryFinder,
        )

        geometry_finder = LocalGeometryFinder()

    started = time.monotonic()
    global_warning = ""
    try:
        raw_results = geometry_finder.compute_coordination_environments(
            to_pymatgen(structure),
            indices=sorted(set(representative_for.values())),
            only_cations=False,
            valences="undefined",
        )
    except Exception as error:
        raw_results = [None] * len(structure.sites)
        global_warning = f"ChemEnv evaluation failed: {error}"
    elapsed = time.monotonic() - started
    over_budget = elapsed > settings.maximum_seconds

    candidates_by_representative: dict[int, tuple[CoordinationCandidate, ...]] = {}
    for representative in sorted(set(representative_for.values())):
        raw = raw_results[representative] if representative < len(raw_results) else None
        candidates: list[CoordinationCandidate] = []
        for item in raw or ():
            symbol = str(item.get("ce_symbol", ""))
            fraction = float(item.get("ce_fraction", 0.0))
            csm = float(item.get("csm", math.inf))
            if not symbol or not math.isfinite(fraction) or fraction < 0.0:
                continue
            candidates.append(
                CoordinationCandidate(
                    symbol=symbol,
                    name=_geometry_name(symbol),
                    fraction=fraction,
                    csm=csm,
                )
            )
        candidates.sort(key=lambda item: (-item.fraction, item.csm, item.symbol))
        if not candidates and not global_warning:
            candidates = _local_order_candidates(
                structure,
                representative,
                memberships[representative],
            )
        candidates_by_representative[representative] = tuple(candidates)

    environments: list[CoordinationEnvironment] = []
    for center_index in sorted(memberships):
        neighbours = memberships[center_index]
        representative = representative_for[center_index]
        candidates = candidates_by_representative[representative]
        messages: list[str] = []
        if center_index in secondary_shell_centers:
            messages.append(
                "A complete secondary anion shell was retained as nested coordination."
            )
        if global_warning:
            messages.append(global_warning)
        if over_budget:
            messages.append(
                f"ChemEnv time budget exceeded ({elapsed:.3f} s > {settings.maximum_seconds:.3f} s)."
            )
        if candidates and candidates[0].method == "local-order-fallback":
            raw = (
                raw_results[representative]
                if representative < len(raw_results)
                else None
            )
            if not raw and not global_warning:
                if candidates:
                    messages.append(
                        "ChemEnv returned no geometry; local order-parameter fallback was used."
                    )
        primary_cn = len(neighbours)
        preferred_cn = _coordination_number(candidates[0].symbol) if candidates else None
        disagreement = preferred_cn is not None and preferred_cn != primary_cn
        if disagreement:
            messages.append(
                f"ChemEnv coordination {preferred_cn} disagrees with primary bond coordination {primary_cn}."
            )
        plausible = sum(candidate.fraction >= 0.05 for candidate in candidates)
        ambiguous = disagreement or plausible > 1
        environments.append(
            CoordinationEnvironment(
                center_index=center_index,
                neighbor_indices=tuple(item[0] for item in neighbours),
                neighbor_images=tuple(item[1] for item in neighbours),
                candidates=candidates,
                ambiguous=ambiguous,
                complete=not global_warning and not over_budget,
                warnings=tuple(messages),
            )
        )
    return tuple(environments)


__all__ = ["describe_coordination"]
