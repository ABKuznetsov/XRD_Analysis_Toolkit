from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from pymatgen.core import Element

from crystal_viewer.analysis.organic.components import ComponentReport
from crystal_viewer.analysis.organic.model import BondLayerReport
from crystal_viewer.core.chemistry import site_elements
from crystal_viewer.core.model import CrystalStructure


class ContactKind(StrEnum):
    HYDROGEN_BOND = "hydrogen-bond"
    PI_STACK = "pi-stack"
    CH_PI = "c-h-pi"
    SHORT = "short-contact"


@dataclass(frozen=True, slots=True)
class ContactSettings:
    hydrogen_angle_minimum: float = 120.0
    hydrogen_acceptor_margin: float = 0.20
    pi_centroid_minimum: float = 3.2
    pi_centroid_maximum: float = 4.2
    pi_plane_angle_maximum: float = 20.0
    pi_lateral_offset_maximum: float = 2.0
    ch_pi_h_centroid_maximum: float = 3.0

    def validate(self) -> None:
        if not 0.0 <= self.hydrogen_angle_minimum <= 180.0:
            raise ValueError("hydrogen_angle_minimum must be between 0 and 180")
        if min(
            self.hydrogen_acceptor_margin,
            self.pi_centroid_minimum,
            self.pi_centroid_maximum,
            self.pi_plane_angle_maximum,
            self.pi_lateral_offset_maximum,
            self.ch_pi_h_centroid_maximum,
        ) < 0.0:
            raise ValueError("contact distances and margins must be non-negative")
        if self.pi_centroid_minimum > self.pi_centroid_maximum:
            raise ValueError("pi centroid minimum cannot exceed maximum")


@dataclass(frozen=True, slots=True)
class IntermolecularContact:
    id: str
    kind: ContactKind
    first_component_id: str
    second_component_id: str
    image: tuple[int, int, int]
    distance: float
    angle: float | None
    confidence: float
    method: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContactReport:
    contacts: tuple[IntermolecularContact, ...]
    hydrogen_bonds_evaluated: bool
    complete: bool = True
    warnings: tuple[str, ...] = ()
    method_version: str = "organic-contacts-v1"

    @property
    def hydrogen_bonds(self) -> tuple[IntermolecularContact, ...]:
        return tuple(contact for contact in self.contacts if contact.kind is ContactKind.HYDROGEN_BOND)


def _symbol(structure: CrystalStructure, index: int) -> str:
    elements = site_elements(structure.sites[index])
    return elements[0] if elements else structure.sites[index].element


def _minimum_vector(
    structure: CrystalStructure, first: np.ndarray, second: np.ndarray
) -> tuple[np.ndarray, tuple[int, int, int]]:
    delta = second - first
    shift = -np.rint(delta).astype(int)
    return (delta + shift) @ structure.cell.matrix, tuple(int(value) for value in shift)


def _angle(first: np.ndarray, second: np.ndarray) -> float:
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 1e-12:
        return 0.0
    cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def _vdw(symbol: str) -> float:
    try:
        value = Element(symbol).van_der_waals_radius
        return float(value) if value is not None else 1.8
    except (ValueError, TypeError):
        return 1.8


def build_contacts(
    structure: CrystalStructure,
    bonds: BondLayerReport,
    components: ComponentReport,
    settings: ContactSettings = ContactSettings(),
) -> ContactReport:
    settings.validate()
    component_for = {
        atom: component.id
        for component in components.components
        for atom in component.atom_indices
    }
    covalent_pairs = {frozenset((edge.first, edge.second)) for edge in bonds.covalent}
    neighbours: dict[int, set[int]] = {}
    for edge in bonds.covalent:
        neighbours.setdefault(edge.first, set()).add(edge.second)
        neighbours.setdefault(edge.second, set()).add(edge.first)

    contacts: list[IntermolecularContact] = []
    claimed_pairs: set[frozenset[int]] = set()
    donor_hydrogens = [
        index
        for index in range(len(structure.sites))
        if _symbol(structure, index) == "H"
        and any(_symbol(structure, neighbour) in {"N", "O", "S"} for neighbour in neighbours.get(index, ()))
    ]
    hydrogen_evaluated = bool(donor_hydrogens)
    acceptors = [
        index for index in range(len(structure.sites)) if _symbol(structure, index) in {"N", "O", "S", "F", "Cl"}
    ]
    for hydrogen in donor_hydrogens:
        donor = next(
            neighbour for neighbour in neighbours[hydrogen] if _symbol(structure, neighbour) in {"N", "O", "S"}
        )
        for acceptor in acceptors:
            if acceptor in {donor, hydrogen}:
                continue
            first_component = component_for.get(hydrogen)
            second_component = component_for.get(acceptor)
            if not first_component or not second_component or first_component == second_component:
                continue
            h_position = np.asarray(structure.sites[hydrogen].fractional)
            donor_vector, _ = _minimum_vector(
                structure, h_position, np.asarray(structure.sites[donor].fractional)
            )
            acceptor_vector, image = _minimum_vector(
                structure, h_position, np.asarray(structure.sites[acceptor].fractional)
            )
            distance = float(np.linalg.norm(acceptor_vector))
            angle = _angle(donor_vector, acceptor_vector)
            if distance > _vdw("H") + _vdw(_symbol(structure, acceptor)) + settings.hydrogen_acceptor_margin:
                continue
            if angle < settings.hydrogen_angle_minimum:
                continue
            pair = frozenset((hydrogen, acceptor))
            claimed_pairs.add(pair)
            contacts.append(
                IntermolecularContact(
                    f"HB:{hydrogen}:{acceptor}:{image}", ContactKind.HYDROGEN_BOND,
                    first_component, second_component, image, distance, angle, 1.0,
                    "explicit-D-H...A-geometry",
                )
            )

    component_by_ring = {
        ring.id: ring.component_id for ring in components.rings
    }
    for hydrogen in range(len(structure.sites)):
        if _symbol(structure, hydrogen) != "H":
            continue
        carbon = next(
            (
                neighbour
                for neighbour in neighbours.get(hydrogen, ())
                if _symbol(structure, neighbour) == "C"
            ),
            None,
        )
        if carbon is None:
            continue
        first_component = component_for.get(hydrogen)
        if first_component is None:
            continue
        hydrogen_position = np.asarray(structure.sites[hydrogen].fractional, dtype=float)
        carbon_vector, _ = _minimum_vector(
            structure,
            hydrogen_position,
            np.asarray(structure.sites[carbon].fractional, dtype=float),
        )
        for pi_system in components.pi_systems:
            second_component = next(
                (
                    component_by_ring.get(ring_id)
                    for ring_id in pi_system.ring_ids
                    if ring_id in component_by_ring
                ),
                None,
            )
            if second_component is None or second_component == first_component:
                continue
            centroid_vector, image = _minimum_vector(
                structure,
                hydrogen_position,
                np.asarray(pi_system.centroid_fractional, dtype=float),
            )
            distance = float(np.linalg.norm(centroid_vector))
            angle = _angle(carbon_vector, centroid_vector)
            if distance > settings.ch_pi_h_centroid_maximum:
                continue
            if angle < settings.hydrogen_angle_minimum:
                continue
            contacts.append(
                IntermolecularContact(
                    f"CHPI:{hydrogen}:{pi_system.id}:{image}",
                    ContactKind.CH_PI,
                    first_component,
                    second_component,
                    image,
                    distance,
                    angle,
                    pi_system.confidence,
                    "explicit-C-H-to-pi-centroid-geometry",
                )
            )
    for first_index, first_pi in enumerate(components.pi_systems):
        first_component = next(
            (component_by_ring.get(ring_id) for ring_id in first_pi.ring_ids if ring_id in component_by_ring),
            None,
        )
        if first_component is None:
            continue
        for second_pi in components.pi_systems[first_index + 1 :]:
            second_component = next(
                (
                    component_by_ring.get(ring_id)
                    for ring_id in second_pi.ring_ids
                    if ring_id in component_by_ring
                ),
                None,
            )
            if second_component is None or second_component == first_component:
                continue
            vector, image = _minimum_vector(
                structure,
                np.asarray(first_pi.centroid_fractional, dtype=float),
                np.asarray(second_pi.centroid_fractional, dtype=float),
            )
            distance = float(np.linalg.norm(vector))
            if not settings.pi_centroid_minimum <= distance <= settings.pi_centroid_maximum:
                continue
            first_normal = np.asarray(first_pi.normal_cartesian, dtype=float)
            second_normal = np.asarray(second_pi.normal_cartesian, dtype=float)
            plane_angle = _angle(first_normal, second_normal)
            plane_angle = min(plane_angle, 180.0 - plane_angle)
            if plane_angle > settings.pi_plane_angle_maximum:
                continue
            normal = first_normal / max(float(np.linalg.norm(first_normal)), 1e-12)
            normal_separation = float(np.dot(vector, normal))
            lateral_offset = math.sqrt(max(0.0, distance * distance - normal_separation * normal_separation))
            if lateral_offset > settings.pi_lateral_offset_maximum:
                continue
            contacts.append(
                IntermolecularContact(
                    f"PI:{first_pi.id}:{second_pi.id}:{image}",
                    ContactKind.PI_STACK,
                    first_component,
                    second_component,
                    image,
                    distance,
                    plane_angle,
                    min(first_pi.confidence, second_pi.confidence),
                    "ring-plane-centroid-offset-geometry",
                )
            )

    for first in range(len(structure.sites)):
        for second in range(first + 1, len(structure.sites)):
            pair = frozenset((first, second))
            if pair in covalent_pairs or pair in claimed_pairs:
                continue
            first_component = component_for.get(first)
            second_component = component_for.get(second)
            if not first_component or not second_component or first_component == second_component:
                continue
            vector, image = _minimum_vector(
                structure,
                np.asarray(structure.sites[first].fractional),
                np.asarray(structure.sites[second].fractional),
            )
            distance = float(np.linalg.norm(vector))
            threshold = 0.85 * (_vdw(_symbol(structure, first)) + _vdw(_symbol(structure, second)))
            if distance <= threshold:
                contacts.append(
                    IntermolecularContact(
                        f"SC:{first}:{second}:{image}", ContactKind.SHORT,
                        first_component, second_component, image, distance, None, 0.7,
                        "vdw-short-contact",
                    )
                )

    warnings = list(bonds.warnings) + list(components.warnings)
    if not hydrogen_evaluated:
        warnings.append("Hydrogen bonds were not evaluated because explicit donor hydrogens are absent.")
    contacts.sort(key=lambda contact: (contact.kind.value, contact.first_component_id, contact.second_component_id, contact.id))
    return ContactReport(tuple(contacts), hydrogen_evaluated, bonds.complete and components.complete, tuple(warnings))


__all__ = [
    "ContactKind", "ContactReport", "ContactSettings", "IntermolecularContact", "build_contacts",
]
