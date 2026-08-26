from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np

from crystal_viewer.core.measurement import MeasuredValue
from crystal_viewer.core.source_data import CifSourceData


@dataclass(frozen=True, slots=True)
class UnitCell:
    a: float
    b: float
    c: float
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0

    def __post_init__(self) -> None:
        if min(self.a, self.b, self.c) <= 0:
            raise ValueError("Cell lengths must be positive.")
        if not all(0.0 < angle < 180.0 for angle in (self.alpha, self.beta, self.gamma)):
            raise ValueError("Cell angles must be between 0 and 180 degrees.")

    @property
    def matrix(self) -> np.ndarray:
        """Lattice vectors as rows (a, b, c)."""
        alpha, beta, gamma = np.radians([self.alpha, self.beta, self.gamma])
        sin_gamma = math.sin(gamma)
        if abs(sin_gamma) < 1e-12:
            raise ValueError("Degenerate unit cell: sin(gamma) is zero.")
        a_vec = np.array([self.a, 0.0, 0.0])
        b_vec = np.array([self.b * math.cos(gamma), self.b * sin_gamma, 0.0])
        c_x = self.c * math.cos(beta)
        c_y = self.c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sin_gamma
        c_z_sq = self.c**2 - c_x**2 - c_y**2
        if c_z_sq < -1e-8:
            raise ValueError("Invalid cell parameters produce an imaginary c vector.")
        c_vec = np.array([c_x, c_y, math.sqrt(max(c_z_sq, 0.0))])
        return np.vstack((a_vec, b_vec, c_vec))

    @property
    def volume(self) -> float:
        return float(abs(np.linalg.det(self.matrix)))

    def frac_to_cart(self, fractional: np.ndarray | tuple[float, float, float]) -> np.ndarray:
        return np.asarray(fractional, dtype=float) @ self.matrix


@dataclass(frozen=True, slots=True)
class SiteComponent:
    """One chemical component of a crystallographic site."""

    element: str
    occupancy: float

    def __post_init__(self) -> None:
        if self.occupancy < 0.0:
            raise ValueError("Site-component occupancy cannot be negative.")


@dataclass(frozen=True, slots=True)
class AtomSite:
    label: str
    element: str
    fractional: tuple[float, float, float]
    occupancy: float = 1.0
    u_iso: float | None = None
    reported: Mapping[str, MeasuredValue] = field(default_factory=dict)
    components: tuple[SiteComponent, ...] = ()
    disorder_group: str = ""
    assembly: str = ""
    source_site_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "reported", MappingProxyType(dict(self.reported)))
        if not self.components:
            object.__setattr__(
                self,
                "components",
                (SiteComponent(self.element, max(0.0, float(self.occupancy))),),
            )

    @property
    def reported_occupancy(self) -> float:
        measured = self.reported.get("occupancy")
        if measured is not None and measured.value is not None:
            return float(measured.value)
        return float(self.occupancy)

    @property
    def effective_occupancy(self) -> float:
        return min(1.0, max(0.0, self.reported_occupancy))

    @property
    def occupancy_warning(self) -> str:
        if 0.0 <= self.reported_occupancy <= 1.0:
            return ""
        return "Reported occupancy is outside 0–1."

    @property
    def vacancy_fraction(self) -> float:
        return max(0.0, 1.0 - sum(component.occupancy for component in self.components))

    @property
    def is_disordered(self) -> bool:
        return len(self.components) > 1 or self.vacancy_fraction > 1e-6


@dataclass(slots=True)
class CrystalStructure:
    name: str
    cell: UnitCell
    asymmetric_sites: list[AtomSite]
    sites: list[AtomSite]
    symmetry_operations: list[str] = field(default_factory=lambda: ["x,y,z"])
    formula: str = ""
    space_group: str = ""
    source_path: Path | None = None
    source_data: CifSourceData = field(default_factory=CifSourceData)

    @property
    def cartesian_positions(self) -> np.ndarray:
        if not self.sites:
            return np.empty((0, 3), dtype=float)
        return np.asarray([self.cell.frac_to_cart(site.fractional) for site in self.sites])

    @property
    def elements(self) -> list[str]:
        return sorted({site.element for site in self.sites})

    @property
    def display_formula(self) -> str:
        if self.formula:
            return self.formula
        counts: dict[str, float] = {}
        for site in self.sites:
            counts[site.element] = counts.get(site.element, 0.0) + site.occupancy
        parts = []
        for element in sorted(counts):
            value = counts[element]
            count = str(int(round(value))) if abs(value - round(value)) < 1e-6 else f"{value:.2f}"
            parts.append(element if count == "1" else f"{element}{count}")
        return " ".join(parts)
