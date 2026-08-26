from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult
from crystal_viewer.core.model import AtomSite, CrystalStructure

if TYPE_CHECKING:
    from crystal_viewer.analysis.structural_analysis import CoordinationEnvironment


STRUCTURAL_MINIMUM = 0.45
INTERSTITIAL_MAXIMUM = 0.30

# A mixed inorganic graph can contain a strongly bonded anionic motif and a
# weaker coordination scaffold whose centres still clear STRUCTURAL_MINIMUM.
# These guards identify a *data gap* rather than any named element or compound.
PRIMARY_MOTIF_MINIMUM_GAP = 0.12
PRIMARY_MOTIF_MINIMUM_RATIO = 1.35
PRIMARY_MOTIF_GAP_DOMINANCE = 1.5


@dataclass(frozen=True, slots=True)
class PolyhedronRoleEvidence:
    center_index: int
    role: str
    mean_bond_valence: float
    confidence: float
    method: str
    warnings: tuple[str, ...] = ()


def primary_motif_center_indices(
    roles: tuple[PolyhedronRoleEvidence, ...] | list[PolyhedronRoleEvidence],
    center_kinds: dict[int, str | frozenset[str]] | None = None,
) -> frozenset[int]:
    """Select a strongly separated primary-motif tier, when one exists.

    The ordinary structural/interstitial classification is intentionally kept:
    this function only prevents a weaker coordination subnetwork from gluing a
    finite, strongly bonded motif into an apparent infinite framework.  If the
    bond-valence evidence is continuous or too sparse, every structural centre
    is retained.
    """
    structural = sorted(
        (
            (float(item.mean_bond_valence), int(item.center_index))
            for item in roles
            if item.role == "structural" and math.isfinite(item.mean_bond_valence)
        ),
        key=lambda item: (item[0], item[1]),
    )
    all_centres = frozenset(center for _, center in structural)
    if len(structural) < 4:
        return all_centres

    gaps = [
        (structural[index + 1][0] - structural[index][0], index)
        for index in range(len(structural) - 1)
    ]
    candidate_gaps = gaps
    if center_kinds is not None:
        def tokens(center: int) -> frozenset[str]:
            value = center_kinds.get(center, frozenset())
            return value if isinstance(value, frozenset) else frozenset((value,))

        candidate_gaps = [
            (gap, index)
            for gap, index in gaps
            if not (
                frozenset().union(*(tokens(center) for _, center in structural[: index + 1]))
                & frozenset().union(*(tokens(center) for _, center in structural[index + 1 :]))
            )
        ]
    if not candidate_gaps:
        return all_centres
    gap, split_index = max(candidate_gaps, key=lambda item: (item[0], -item[1]))
    upper_count = len(structural) - split_index - 1
    if upper_count < 3:
        return all_centres
    second_gap = max(
        (value for value, index in candidate_gaps if index != split_index),
        default=0.0,
    )
    lower = structural[split_index][0]
    upper = structural[split_index + 1][0]
    ratio = upper / max(lower, 1e-12)
    if (
        gap < PRIMARY_MOTIF_MINIMUM_GAP
        or ratio < PRIMARY_MOTIF_MINIMUM_RATIO
        or (second_gap > 0.0 and gap < PRIMARY_MOTIF_GAP_DOMINANCE * second_gap)
    ):
        return all_centres
    return frozenset(center for _, center in structural[split_index + 1 :])


def _bond_valence(first: AtomSite, second: AtomSite, distance: float) -> float:
    from pymatgen.analysis.bond_valence import BV_PARAMS, ELECTRONEG
    from pymatgen.core import Element

    total = 0.0
    for first_component in first.components:
        if first_component.occupancy <= 0.0:
            continue
        first_element = Element(first_component.element)
        for second_component in second.components:
            if second_component.occupancy <= 0.0:
                continue
            second_element = Element(second_component.element)
            if (
                first_element == second_element
                or (first_element not in ELECTRONEG and second_element not in ELECTRONEG)
            ):
                continue
            first_parameters = BV_PARAMS[first_element]
            second_parameters = BV_PARAMS[second_element]
            first_radius = float(first_parameters["r"])
            second_radius = float(second_parameters["r"])
            first_c = float(first_parameters["c"])
            second_c = float(second_parameters["c"])
            reference = (
                first_radius
                + second_radius
                - first_radius
                * second_radius
                * (math.sqrt(first_c) - math.sqrt(second_c)) ** 2
                / (first_c * first_radius + second_c * second_radius)
            )
            contribution = math.exp((reference - distance) / 0.31)
            sign = 1.0 if first_element.X < second_element.X else -1.0
            total += (
                float(first_component.occupancy)
                * float(second_component.occupancy)
                * contribution
                * sign
            )
    return total


def _role(mean_bond_valence: float) -> tuple[str, float]:
    if mean_bond_valence >= STRUCTURAL_MINIMUM:
        confidence = 0.5 + 0.5 * min(
            1.0,
            (mean_bond_valence - STRUCTURAL_MINIMUM) / STRUCTURAL_MINIMUM,
        )
        return "structural", confidence
    if mean_bond_valence <= INTERSTITIAL_MAXIMUM:
        confidence = 0.5 + 0.5 * min(
            1.0,
            (INTERSTITIAL_MAXIMUM - mean_bond_valence) / INTERSTITIAL_MAXIMUM,
        )
        return "interstitial", confidence
    return "ambiguous", 0.5


def classify_polyhedron_roles(
    structure: CrystalStructure,
    bonds: PeriodicBondResult,
    environments: tuple[CoordinationEnvironment, ...],
) -> tuple[PolyhedronRoleEvidence, ...]:
    """Classify coordination centres from local bond-valence evidence."""
    distances: dict[tuple[int, int, tuple[int, int, int]], float] = {}
    for bond in bonds.bonds:
        distances[(bond.first, bond.second, bond.image)] = float(bond.distance)
        distances[
            (bond.second, bond.first, tuple(-value for value in bond.image))
        ] = float(bond.distance)

    result: list[PolyhedronRoleEvidence] = []
    for environment in environments:
        memberships = tuple(
            zip(
                environment.neighbor_indices,
                environment.neighbor_images,
                strict=True,
            )
        )
        if not memberships:
            result.append(
                PolyhedronRoleEvidence(
                    environment.center_index,
                    "ambiguous",
                    0.0,
                    0.0,
                    "pymatgen-bond-valence-unordered",
                    ("No neighbours are available for bond-valence classification.",),
                )
            )
            continue

        warnings: list[str] = []
        values: list[float] = []
        center = structure.sites[environment.center_index]
        for neighbor_index, image in memberships:
            distance = distances.get((environment.center_index, neighbor_index, image))
            if distance is None:
                warnings.append(
                    f"Missing periodic bond for centre {environment.center_index}, "
                    f"neighbour {neighbor_index}, image {image}."
                )
                continue
            try:
                value = _bond_valence(center, structure.sites[neighbor_index], distance)
            except (KeyError, TypeError, ValueError, OverflowError) as error:
                warnings.append(f"Bond-valence parameters unavailable: {error}")
                continue
            if np.isfinite(value):
                values.append(float(value))
            else:
                warnings.append("Non-finite bond-valence contribution ignored.")

        if not values:
            result.append(
                PolyhedronRoleEvidence(
                    environment.center_index,
                    "ambiguous",
                    0.0,
                    0.0,
                    "pymatgen-bond-valence-unordered",
                    tuple(dict.fromkeys(warnings or ["No usable bond-valence evidence."])),
                )
            )
            continue
        mean = abs(math.fsum(values)) / len(memberships)
        role, confidence = _role(mean)
        result.append(
            PolyhedronRoleEvidence(
                environment.center_index,
                role,
                mean,
                confidence,
                "pymatgen-bond-valence-unordered",
                tuple(dict.fromkeys(warnings)),
            )
        )
    return tuple(result)


__all__ = [
    "INTERSTITIAL_MAXIMUM",
    "PRIMARY_MOTIF_GAP_DOMINANCE",
    "PRIMARY_MOTIF_MINIMUM_GAP",
    "PRIMARY_MOTIF_MINIMUM_RATIO",
    "PolyhedronRoleEvidence",
    "STRUCTURAL_MINIMUM",
    "classify_polyhedron_roles",
    "primary_motif_center_indices",
]
