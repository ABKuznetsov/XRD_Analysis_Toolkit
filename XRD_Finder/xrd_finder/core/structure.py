from __future__ import annotations

from dataclasses import dataclass, field

from xrd_finder.core.base import ProjectObject, new_id


@dataclass(slots=True)
class CellParameters:
    a: float | None = None
    b: float | None = None
    c: float | None = None
    alpha: float | None = None
    beta: float | None = None
    gamma: float | None = None
    volume: float | None = None


@dataclass(slots=True)
class AtomSite:
    label: str
    element: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    occupancy: float | None = None
    biso: float | None = None
    uiso: float | None = None
    wyckoff: str = ""
    multiplicity: int | None = None


@dataclass(slots=True)
class Structure(ProjectObject):
    source_path: str = ""
    origin: str = "original"
    phase_id: str | None = None
    refinement_id: str | None = None
    formula: str = ""
    space_group: str = ""
    space_group_number: str = ""
    atom_count: int | None = None
    wavelength: float | None = None
    cell: CellParameters = field(default_factory=CellParameters)
    atoms: list[AtomSite] = field(default_factory=list)
    symops: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, name: str, source_path: str = "", origin: str = "original") -> "Structure":
        return cls(name=name, id=new_id("structure"), source_path=source_path, origin=origin)
