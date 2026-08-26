from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

import numpy as np

from crystal_viewer.adapters import from_pymatgen
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.core.symmetry import expand_sites, parse_affine_operation
from crystal_viewer.core.xpff import load_xpff_structures


SUPPORTED_STRUCTURE_SUFFIXES = frozenset(
    {".cif", ".xpff", ".res", ".ins", ".vasp", ".pdb", ".xyz"}
)
SUPPORTED_STRUCTURE_BASENAMES = frozenset({"poscar", "contcar"})


def is_supported_structure_path(path: str | Path) -> bool:
    source = Path(path)
    return (
        source.suffix.lower() in SUPPORTED_STRUCTURE_SUFFIXES
        or source.name.casefold() in SUPPORTED_STRUCTURE_BASENAMES
    )


def _element_symbol(value: str) -> str:
    from pymatgen.core import Element

    match = re.match(r"[A-Za-z]{1,2}", value.strip().lstrip("$"))
    if match is None:
        raise ValueError(f"Cannot determine element from {value!r}.")
    letters = match.group(0)
    for width in (2, 1):
        candidate = letters[:width].capitalize()
        try:
            Element(candidate)
        except ValueError:
            continue
        return candidate
    raise ValueError(f"Unknown chemical element {value!r}.")


def _shelx_sfac_elements(fields: list[str]) -> list[str]:
    elements: list[str] = []
    for value in fields:
        try:
            float(value)
        except ValueError:
            pass
        else:
            continue
        try:
            elements.append(_element_symbol(value))
        except ValueError:
            continue
    return elements


def _pdb_atom_name_element(raw_name: str) -> str:
    if raw_name[:1].isspace():
        match = re.search(r"[A-Za-z]", raw_name)
        if match is None:
            raise ValueError(f"Cannot determine element from PDB atom name {raw_name!r}.")
        return _element_symbol(match.group(0))
    name = raw_name.strip()
    if name[:1].isdigit():
        name = name.lstrip("0123456789")
        match = re.search(r"[A-Za-z]", name)
        if match is None:
            raise ValueError(f"Cannot determine element from PDB atom name {raw_name!r}.")
        return _element_symbol(match.group(0))
    return _element_symbol(name)


def _shelx_occupancy(raw: float, free_variables: tuple[float, ...]) -> float:
    value = abs(float(raw))
    variable = int(value // 10.0)
    multiplier = value - 10.0 * variable
    if variable <= 1:
        return multiplier
    free_value = free_variables[variable - 1] if variable <= len(free_variables) else 1.0
    return multiplier * (1.0 - free_value if raw < 0.0 else free_value)


def _affine_triplet(rotation: np.ndarray, translation: np.ndarray) -> str:
    expressions: list[str] = []
    for row, offset in zip(rotation, translation, strict=True):
        terms: list[str] = []
        for coefficient, variable in zip(row, "xyz", strict=True):
            value = int(coefficient)
            if value:
                terms.append(("+" if value > 0 and terms else "") + ("-" if value < 0 else "") + variable)
        fraction = Fraction(float(offset) % 1.0).limit_denominator(24)
        if fraction:
            token = str(fraction.numerator) if fraction.denominator == 1 else f"{fraction.numerator}/{fraction.denominator}"
            terms.append(("+" if terms else "") + token)
        expressions.append("".join(terms) or "0")
    return ",".join(expressions)


def _shelx_operations(latt: int, symm: list[str]) -> list[str]:
    base = [parse_affine_operation(value) for value in ["x,y,z", *symm]]
    if latt > 0:
        base.extend(
            type(operation)(-operation.rotation, -operation.translation)
            for operation in tuple(base)
        )
    translations = {
        1: ("x,y,z",),
        2: ("x,y,z", "x+1/2,y+1/2,z+1/2"),
        3: ("x,y,z", "x+2/3,y+1/3,z+1/3", "x+1/3,y+2/3,z+2/3"),
        4: ("x,y,z", "x,y+1/2,z+1/2", "x+1/2,y,z+1/2", "x+1/2,y+1/2,z"),
        5: ("x,y,z", "x,y+1/2,z+1/2"),
        6: ("x,y,z", "x+1/2,y,z+1/2"),
        7: ("x,y,z", "x+1/2,y+1/2,z"),
    }.get(abs(latt), ("x,y,z",))
    shifts = [parse_affine_operation(value).translation for value in translations]
    result: list[str] = []
    for shift in shifts:
        for operation in base:
            triplet = _affine_triplet(operation.rotation, operation.translation + shift)
            if triplet not in result:
                result.append(triplet)
    return result


def _load_shelx(path: Path) -> CrystalStructure:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    title = path.stem
    cell: UnitCell | None = None
    latt = -1
    symm: list[str] = []
    elements: list[str] = []
    free_variables: tuple[float, ...] = ()
    sites: list[AtomSite] = []
    used_labels: set[str] = set()
    reading_atoms = False
    space_group = ""
    for raw_line in lines:
        line = raw_line.split("!", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        command = fields[0].upper()
        if command == "TITL":
            raw_title = line[4:].strip()
            title = re.split(r"\s+in\s+", raw_title, maxsplit=1, flags=re.IGNORECASE)[0] or path.stem
            match = re.search(r"\s+in\s+(.+)$", raw_title, flags=re.IGNORECASE)
            space_group = match.group(1).strip() if match else ""
            continue
        if command == "CELL" and len(fields) >= 8:
            cell = UnitCell(*(float(value) for value in fields[2:8]))
            continue
        if command == "LATT" and len(fields) >= 2:
            latt = int(fields[1])
            continue
        if command == "SYMM":
            symm.append(line[4:].strip())
            continue
        if command == "SFAC":
            elements.extend(_shelx_sfac_elements(fields[1:]))
            reading_atoms = True
            continue
        if command == "FVAR":
            free_variables = tuple(float(value) for value in fields[1:])
            continue
        if command in {"HKLF", "END"}:
            break
        if not reading_atoms or command.startswith("Q") or len(fields) < 6:
            continue
        try:
            sfac_index = int(fields[1])
            fractional = tuple(float(value) for value in fields[2:5])
            raw_occupancy = float(fields[5])
        except ValueError:
            continue
        if not 1 <= sfac_index <= len(elements):
            continue
        element = elements[sfac_index - 1]
        raw_label = fields[0]
        suffix_match = re.match(r"[A-Za-z]+(.*)$", raw_label)
        suffix = suffix_match.group(1) if suffix_match else ""
        label = f"{element}{suffix}" if suffix else element
        if label.casefold() in used_labels:
            number = 2
            while f"{label}.{number}".casefold() in used_labels:
                number += 1
            label = f"{label}.{number}"
        used_labels.add(label.casefold())
        u_iso = None
        if len(fields) >= 7:
            try:
                u_iso = float(fields[6])
            except ValueError:
                pass
        sites.append(
            AtomSite(
                label=label,
                element=element,
                fractional=fractional,
                occupancy=_shelx_occupancy(raw_occupancy, free_variables),
                u_iso=u_iso,
                source_site_key=raw_label,
            )
        )
    if cell is None:
        raise ValueError("SHELX file does not contain a valid CELL instruction.")
    if not elements or not sites:
        raise ValueError("SHELX file does not contain SFAC atom records.")
    operations = _shelx_operations(latt, symm)
    return CrystalStructure(
        name=title,
        cell=cell,
        asymmetric_sites=sites,
        sites=expand_sites(sites, operations),
        symmetry_operations=operations,
        space_group=space_group,
        source_path=path,
    )


def _load_xyz(path: Path) -> CrystalStructure:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        raise ValueError("XYZ file is empty.")
    try:
        count = int(lines[0].strip())
    except ValueError as error:
        raise ValueError("XYZ first line must contain the atom count.") from error
    if count <= 0 or len(lines) < count + 2:
        raise ValueError("XYZ atom count does not match the file contents.")
    elements: list[str] = []
    cartesian: list[tuple[float, float, float]] = []
    for line in lines[2 : count + 2]:
        fields = line.split()
        if len(fields) < 4:
            raise ValueError("XYZ atom rows require element, x, y and z.")
        elements.append(_element_symbol(fields[0]))
        cartesian.append(tuple(float(value) for value in fields[1:4]))
    points = np.asarray(cartesian, dtype=float)
    low = points.min(axis=0) - 5.0
    lengths = np.maximum(points.max(axis=0) - points.min(axis=0) + 10.0, 10.0)
    fractional = (points - low) / lengths
    counters: dict[str, int] = {}
    sites: list[AtomSite] = []
    for element, coordinates in zip(elements, fractional, strict=True):
        counters[element] = counters.get(element, 0) + 1
        label = f"{element}{counters[element]}"
        sites.append(
            AtomSite(
                label,
                element,
                tuple(float(value) for value in coordinates),
                source_site_key=label,
            )
        )
    name = lines[1].strip() or path.stem
    return CrystalStructure(
        name=name,
        cell=UnitCell(*map(float, lengths)),
        asymmetric_sites=list(sites),
        sites=sites,
        formula="",
        space_group="molecule (display cell)",
        source_path=path,
    )


def _load_vasp(path: Path) -> CrystalStructure:
    from pymatgen.core import Structure

    result = from_pymatgen(Structure.from_file(path), name=path.stem)
    result.source_path = path
    return result


def _load_pdb(path: Path) -> CrystalStructure:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    cell: UnitCell | None = None
    space_group = ""
    atom_rows: list[tuple[str, str, np.ndarray, float]] = []
    for line in lines:
        record = line[:6].strip().upper()
        if record == "CRYST1":
            try:
                cell = UnitCell(
                    float(line[6:15]),
                    float(line[15:24]),
                    float(line[24:33]),
                    float(line[33:40]),
                    float(line[40:47]),
                    float(line[47:54]),
                )
            except ValueError as error:
                raise ValueError("PDB contains an invalid CRYST1 record.") from error
            space_group = line[55:66].strip()
            continue
        if record == "ENDMDL":
            break
        if record not in {"ATOM", "HETATM"}:
            continue
        alternate = line[16:17].strip()
        if alternate not in {"", "A", "1"}:
            continue
        raw_atom_name = line[12:16]
        label = raw_atom_name.strip() or f"site{len(atom_rows) + 1}"
        explicit_element = line[76:78].strip()
        try:
            element = (
                _element_symbol(explicit_element)
                if explicit_element
                else _pdb_atom_name_element(raw_atom_name)
            )
            coordinates = np.asarray(
                [float(line[30:38]), float(line[38:46]), float(line[46:54])],
                dtype=float,
            )
            occupancy = float(line[54:60].strip() or 1.0)
        except ValueError as error:
            raise ValueError(f"PDB contains an invalid atom record: {line!r}") from error
        atom_rows.append((label, element, coordinates, occupancy))
    if not atom_rows:
        raise ValueError("PDB does not contain ATOM or HETATM records.")
    points = np.asarray([row[2] for row in atom_rows], dtype=float)
    if cell is None:
        low = points.min(axis=0) - 5.0
        lengths = np.maximum(points.max(axis=0) - points.min(axis=0) + 10.0, 10.0)
        cell = UnitCell(*map(float, lengths))
        fractional = (points - low) / lengths
        space_group = "molecule (display cell)"
    else:
        fractional = points @ np.linalg.inv(cell.matrix)
    used: dict[str, int] = {}
    sites: list[AtomSite] = []
    for row, coordinates in zip(atom_rows, fractional, strict=True):
        raw_label, element, _, occupancy = row
        used[raw_label] = used.get(raw_label, 0) + 1
        label = raw_label if used[raw_label] == 1 else f"{raw_label}.{used[raw_label]}"
        sites.append(
            AtomSite(
                label,
                element,
                tuple(float(value % 1.0) for value in coordinates),
                occupancy=occupancy,
                source_site_key=label,
            )
        )
    return CrystalStructure(
        name=path.stem,
        cell=cell,
        asymmetric_sites=list(sites),
        sites=sites,
        symmetry_operations=["x,y,z"],
        space_group=space_group,
        source_path=path,
    )


def load_structure_files(path: str | Path) -> list[CrystalStructure]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix == ".xpff":
        return load_xpff_structures(source)
    if suffix == ".cif":
        return [load_cif(source)]
    if suffix in {".res", ".ins"}:
        return [_load_shelx(source)]
    if suffix == ".xyz":
        return [_load_xyz(source)]
    if suffix == ".pdb":
        return [_load_pdb(source)]
    if suffix == ".vasp" or source.name.casefold() in SUPPORTED_STRUCTURE_BASENAMES:
        return [_load_vasp(source)]
    raise ValueError(f"Unsupported structure format: {source.name}")


__all__ = [
    "SUPPORTED_STRUCTURE_BASENAMES",
    "SUPPORTED_STRUCTURE_SUFFIXES",
    "is_supported_structure_path",
    "load_structure_files",
]
