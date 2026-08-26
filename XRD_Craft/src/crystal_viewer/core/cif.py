from __future__ import annotations

import math
import re
import shlex
from dataclasses import replace
from pathlib import Path

from crystal_viewer.core.measurement import MeasuredValue, parse_cif_number
from crystal_viewer.core.model import AtomSite, CrystalStructure, SiteComponent, UnitCell
from crystal_viewer.core.source_data import CifLoop, CifSourceData
from crystal_viewer.core.symmetry import expand_sites

try:
    import gemmi
except ImportError:  # A small fallback keeps core tests and basic CIFs usable.
    gemmi = None


def _load_with_pymatgen(path: Path) -> CrystalStructure:
    """Use the XRD environment's mature CIF reader when gemmi is unavailable."""
    from pymatgen.core import Structure
    from pymatgen.symmetry.groups import SpaceGroup

    from crystal_viewer.adapters import from_pymatgen

    result = from_pymatgen(Structure.from_file(path), name=path.stem)
    result.source_path = path
    values, loops = _fallback_tokens(path.read_text(encoding="utf-8", errors="replace"))
    result.source_data = _source_data(values, loops)
    operations: list[str] = []
    for tags, rows in loops:
        for sym_tag in ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"):
            if sym_tag in tags:
                column = tags.index(sym_tag)
                operations = [_clean(row[column]) for row in rows if column < len(row)]
                if operations:
                    break
        if operations:
            break
    reported_space_group = _clean(
        values.get("_space_group_name_H-M_alt")
        or values.get("_symmetry_space_group_name_H-M")
    )
    if reported_space_group:
        try:
            group = SpaceGroup(reported_space_group)
            result.space_group = group.symbol
            if not operations:
                operations = [operation.as_xyz_str() for operation in group.symmetry_ops]
        except ValueError:
            result.space_group = reported_space_group
    operations = operations or ["x,y,z"]
    result.symmetry_operations = operations

    # pymatgen intentionally returns the expanded conventional structure.  The
    # original CIF atom loop remains the authoritative list of independent
    # crystallographic positions used by tables and reports.
    try:
        raw = _load_fallback(path, expand_symmetry=False)
    except (OSError, ValueError, IndexError):
        raw = None
    if raw is not None and raw.asymmetric_sites:
        result.asymmetric_sites = list(raw.asymmetric_sites)
        result.sites = expand_sites(result.asymmetric_sites, operations)
    return result


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().strip("'\"")
    if text in {".", "?"}:
        return ""
    return text


_SCREW_AXIS_TOKENS = frozenset({"21", "31", "32", "41", "42", "43", "61", "62", "63", "64", "65"})


def _space_group_symbol(value: str | None) -> str:
    """Keep the CIF Hermann–Mauguin setting while making screw axes explicit."""
    tokens = _clean(value).split()
    return "".join(
        f"{token[0]}_{token[1]}" if token in _SCREW_AXIS_TOKENS else token
        for token in tokens
    )


def _number(value: str | None, default: float | None = None) -> float | None:
    if value is None:
        return default
    text = str(value).strip().strip("'\"")
    if not text or text in {".", "?"}:
        return default
    try:
        return parse_cif_number(text.replace(",", ".")).value
    except ValueError:
        return default


def _element(label: str, symbol: str = "") -> str:
    """Resolve a CIF element symbol without assuming labels are capitalized."""
    from pymatgen.core import Element

    for source in (_clean(symbol), _clean(label)):
        match = re.match(r"([A-Za-z]+)", source)
        if match is None:
            continue
        letters = match.group(1)
        for width in (2, 1):
            if len(letters) < width:
                continue
            candidate = letters[:width].capitalize()
            try:
                Element(candidate)
            except ValueError:
                continue
            return candidate
    return "X"


def _normalize_site_labels(sites: list[AtomSite]) -> list[AtomSite]:
    """Canonicalize display labels while retaining raw labels in source data."""
    normalized: list[AtomSite] = []
    used: set[str] = set()
    counters: dict[str, int] = {}
    for site in sites:
        if "/" in site.element:
            raw_parts = _clean(site.label).split("/")
            elements = site.element.split("/")
            if len(raw_parts) == len(elements):
                parts = []
                for raw_part, element in zip(raw_parts, elements, strict=True):
                    suffix = (
                        raw_part[len(element) :]
                        if raw_part.casefold().startswith(element.casefold())
                        else ""
                    )
                    parts.append(f"{element}{suffix}")
                candidate = "/".join(parts)
            else:
                candidate = site.label
        else:
            raw = _clean(site.label)
            suffix = (
                raw[len(site.element) :]
                if raw.casefold().startswith(site.element.casefold())
                else ""
            )
            candidate = f"{site.element}{suffix}" if suffix else ""
        if not candidate or candidate.casefold() in used:
            number = counters.get(site.element, 0) + 1
            candidate = f"{site.element}{number}"
            while candidate.casefold() in used:
                number += 1
                candidate = f"{site.element}{number}"
            counters[site.element] = number
        used.add(candidate.casefold())
        normalized.append(replace(site, label=candidate))
    return normalized


def _first(block, *tags: str) -> str:
    for tag in tags:
        value = _clean(block.find_value(tag))
        if value:
            return value
    return ""


def _loop(block, tag: str) -> list[str]:
    values = block.find_loop(tag)
    return [_clean(str(value)) for value in values] if values is not None else []


def _raw_loop(block, tag: str) -> list[str]:
    values = block.find_loop(tag)
    return [str(value).strip().strip("'\"") for value in values] if values is not None else []


def _source_data(
    values: dict[str, str],
    loops: list[tuple[list[str], list[list[str]]]],
) -> CifSourceData:
    return CifSourceData(
        scalars=values,
        loops=tuple(
            CifLoop(
                tags=tuple(tags),
                rows=tuple(tuple(str(value) for value in row) for row in rows),
            )
            for tags, rows in loops
        ),
    )


def _gemmi_source_data(block) -> CifSourceData:
    scalars: dict[str, str] = {}
    loops: list[CifLoop] = []
    for item in block:
        pair = item.pair
        if pair is not None:
            tag, value = pair
            scalars[str(tag)] = str(value).strip().strip("'\"")
            continue
        loop = item.loop
        if loop is None:
            continue
        tags = tuple(str(tag) for tag in loop.tags)
        width = len(tags)
        raw_values = [str(value).strip().strip("'\"") for value in loop.values]
        rows = tuple(
            tuple(raw_values[index : index + width])
            for index in range(0, len(raw_values), width)
            if len(raw_values[index : index + width]) == width
        )
        loops.append(CifLoop(tags=tags, rows=rows))
    return CifSourceData(scalars=scalars, loops=tuple(loops))


def _site_measurements(
    index: int,
    columns: dict[str, tuple[list[str], str, str]],
) -> dict[str, MeasuredValue]:
    reported: dict[str, MeasuredValue] = {}
    for key, (tokens, unit, source_name) in columns.items():
        token = tokens[index] if index < len(tokens) else None
        reported[key] = parse_cif_number(token, unit=unit, source_name=source_name)
    return reported


def _site_identity(site: AtomSite) -> str | None:
    """Return the label portion that identifies a crystallographic position."""
    label = _clean(site.label)
    element = _clean(site.element)
    if element and label.casefold().startswith(element.casefold()):
        identity = label[len(element) :].casefold()
        return identity or None
    match = re.match(r"[A-Z][a-z]?", label)
    identity = label[match.end() :].casefold() if match is not None else label.casefold()
    return identity or None


def _fractional_key(
    fractional: tuple[float, float, float],
    tolerance_decimals: int = 6,
) -> tuple[float, float, float]:
    normalized = []
    for value in fractional:
        wrapped = float(value) % 1.0
        if math.isclose(wrapped, 0.0, abs_tol=10.0 ** (-tolerance_decimals)) or math.isclose(
            wrapped,
            1.0,
            abs_tol=10.0 ** (-tolerance_decimals),
        ):
            wrapped = 0.0
        normalized.append(round(wrapped, tolerance_decimals))
    return tuple(normalized)


def _merge_coincident_mixed_sites(
    sites: list[AtomSite],
    disorder_assemblies: list[str] | None = None,
    disorder_groups: list[str] | None = None,
) -> list[AtomSite]:
    """Merge chemical alternatives representing one physical position.

    Matching label identities remain authoritative.  Independently of labels,
    exactly coincident rows with distinct elements are also one mixed site when
    every component is partial and their total occupancy does not exceed one.
    Disorder assemblies remain strict boundaries.
    """
    coordinate_groups: dict[
        tuple[tuple[float, float, float], str, str],
        list[int],
    ] = {}
    for index, site in enumerate(sites):
        disorder_assembly = (
            _clean(disorder_assemblies[index])
            if disorder_assemblies is not None and index < len(disorder_assemblies)
            else ""
        )
        disorder_group = (
            _clean(disorder_groups[index])
            if disorder_groups is not None and index < len(disorder_groups)
            else ""
        )
        coordinate_groups.setdefault(
            (
                _fractional_key(site.fractional),
                disorder_assembly.casefold(),
                disorder_group.casefold(),
            ),
            [],
        ).append(index)

    grouped_indices: list[list[int]] = []
    for coordinate_indices in coordinate_groups.values():
        coordinate_sites = [sites[index] for index in coordinate_indices]
        coordinate_elements = [
            component.element
            for site in coordinate_sites
            for component in site.components
        ]
        coordinate_occupancy = math.fsum(
            component.occupancy
            for site in coordinate_sites
            for component in site.components
        )
        complementary = (
            len(coordinate_indices) > 1
            and len(coordinate_elements) == len(set(coordinate_elements))
            and all(site.reported_occupancy < 1.0 - 1e-9 for site in coordinate_sites)
            and coordinate_occupancy <= 1.0 + 1e-9
        )
        if complementary:
            grouped_indices.append(coordinate_indices)
            continue
        identity_groups: dict[str, list[int]] = {}
        for index in coordinate_indices:
            identity = _site_identity(sites[index])
            if identity is not None:
                identity_groups.setdefault(identity, []).append(index)
        grouped_indices.extend(identity_groups.values())

    merged_at: dict[int, AtomSite] = {}
    consumed: set[int] = set()
    for indices in grouped_indices:
        if len(indices) < 2:
            continue
        group = [sites[index] for index in indices]
        elements = [component.element for site in group for component in site.components]
        if len(elements) != len(set(elements)):
            continue

        components = tuple(
            SiteComponent(component.element, float(component.occupancy))
            for site in group
            for component in site.components
        )
        total_occupancy = math.fsum(component.occupancy for component in components)
        first = group[0]
        reported = dict(first.reported)
        reported.pop("occupancy", None)
        for component_site in group:
            measured = component_site.reported.get("occupancy")
            if measured is None:
                continue
            base_key = f"component_occupancy:{component_site.label}"
            key = base_key
            suffix = 2
            while key in reported:
                key = f"{base_key}#{suffix}"
                suffix += 1
            reported[key] = measured
        merged_at[indices[0]] = AtomSite(
            label="/".join(site.label for site in group),
            element="/".join(component.element for component in components),
            fractional=first.fractional,
            occupancy=total_occupancy,
            u_iso=first.u_iso,
            reported=reported,
            components=components,
            disorder_group=first.disorder_group,
            assembly=first.assembly,
            source_site_key=first.source_site_key or first.label,
        )
        consumed.update(indices[1:])

    return [
        merged_at.get(index, site)
        for index, site in enumerate(sites)
        if index not in consumed
    ]


def _load_with_gemmi(path: Path, expand_symmetry: bool) -> CrystalStructure:
    document = gemmi.cif.read_file(str(path))
    block = document.sole_block()
    cell = UnitCell(
        a=_number(block.find_value("_cell_length_a")),
        b=_number(block.find_value("_cell_length_b")),
        c=_number(block.find_value("_cell_length_c")),
        alpha=_number(block.find_value("_cell_angle_alpha"), 90.0),
        beta=_number(block.find_value("_cell_angle_beta"), 90.0),
        gamma=_number(block.find_value("_cell_angle_gamma"), 90.0),
    )
    labels = _loop(block, "_atom_site_label")
    xs = _raw_loop(block, "_atom_site_fract_x")
    ys = _raw_loop(block, "_atom_site_fract_y")
    zs = _raw_loop(block, "_atom_site_fract_z")
    if not labels or not (len(labels) == len(xs) == len(ys) == len(zs)):
        raise ValueError("CIF does not contain a complete atom-site fractional-coordinate loop.")
    symbols = _loop(block, "_atom_site_type_symbol")
    occupancies = _raw_loop(block, "_atom_site_occupancy")
    u_iso = _raw_loop(block, "_atom_site_U_iso_or_equiv")
    b_iso = _raw_loop(block, "_atom_site_B_iso_or_equiv")
    disorder_assemblies = _raw_loop(block, "_atom_site_disorder_assembly")
    disorder_groups = _raw_loop(block, "_atom_site_disorder_group")
    asymmetric = []
    for index, label in enumerate(labels):
        reported = _site_measurements(
            index,
            {
                "fract_x": (xs, "", "_atom_site_fract_x"),
                "fract_y": (ys, "", "_atom_site_fract_y"),
                "fract_z": (zs, "", "_atom_site_fract_z"),
                "occupancy": (occupancies, "", "_atom_site_occupancy"),
                "U_iso_or_equiv": (u_iso, "Å²", "_atom_site_U_iso_or_equiv"),
                "B_iso_or_equiv": (b_iso, "Å²", "_atom_site_B_iso_or_equiv"),
            },
        )
        u_value = _number(u_iso[index]) if index < len(u_iso) else None
        if u_value is None and index < len(b_iso):
            b_value = _number(b_iso[index])
            u_value = b_value / (8.0 * math.pi**2) if b_value is not None else None
        asymmetric.append(
            AtomSite(
                label=label,
                element=_element(label, symbols[index] if index < len(symbols) else ""),
                fractional=(
                    _number(xs[index], 0.0),
                    _number(ys[index], 0.0),
                    _number(zs[index], 0.0),
                ),
                occupancy=_number(occupancies[index], 1.0) if index < len(occupancies) else 1.0,
                u_iso=u_value,
                reported=reported,
                disorder_group=(
                    _clean(disorder_groups[index]) if index < len(disorder_groups) else ""
                ),
                assembly=(
                    _clean(disorder_assemblies[index])
                    if index < len(disorder_assemblies)
                    else ""
                ),
                source_site_key=label,
            )
        )
    asymmetric = _normalize_site_labels(
        _merge_coincident_mixed_sites(asymmetric, disorder_assemblies, disorder_groups)
    )
    operations = []
    for tag in ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"):
        operations = _loop(block, tag)
        if operations:
            break
    operations = operations or ["x,y,z"]
    sites = expand_sites(asymmetric, operations) if expand_symmetry else list(asymmetric)
    return CrystalStructure(
        name=_first(block, "_chemical_name_mineral", "_chemical_name_common") or path.stem,
        cell=cell,
        asymmetric_sites=asymmetric,
        sites=sites,
        symmetry_operations=operations,
        formula=_first(block, "_chemical_formula_sum", "_chemical_formula_structural"),
        space_group=_space_group_symbol(
            _first(block, "_space_group_name_H-M_alt", "_symmetry_space_group_name_H-M")
        ),
        source_path=path,
        source_data=_gemmi_source_data(block),
    )


def _fallback_tokens(text: str) -> tuple[dict[str, str], list[tuple[list[str], list[list[str]]]]]:
    lines = text.splitlines()
    values: dict[str, str] = {}
    loops: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.startswith("#"):
            index += 1
            continue
        if line.lower() == "loop_":
            index += 1
            tags = []
            while index < len(lines) and lines[index].lstrip().startswith("_"):
                tags.append(lines[index].strip().split()[0])
                index += 1
            tokens: list[str] = []
            while index < len(lines):
                candidate = lines[index].strip()
                if candidate.lower() == "loop_" or candidate.startswith("_") or candidate.lower().startswith("data_"):
                    break
                if candidate and not candidate.startswith("#"):
                    tokens.extend(shlex.split(candidate, comments=True))
                index += 1
            width = len(tags)
            loops.append((tags, [tokens[i : i + width] for i in range(0, len(tokens), width) if len(tokens[i : i + width]) == width]))
            continue
        if line.startswith("_"):
            parts = shlex.split(line, comments=True)
            if len(parts) > 1:
                values[parts[0]] = parts[1]
        index += 1
    return values, loops


def _load_fallback(path: Path, expand_symmetry: bool) -> CrystalStructure:
    values, loops = _fallback_tokens(path.read_text(encoding="utf-8", errors="replace"))
    cell = UnitCell(
        a=_number(values.get("_cell_length_a")),
        b=_number(values.get("_cell_length_b")),
        c=_number(values.get("_cell_length_c")),
        alpha=_number(values.get("_cell_angle_alpha"), 90.0),
        beta=_number(values.get("_cell_angle_beta"), 90.0),
        gamma=_number(values.get("_cell_angle_gamma"), 90.0),
    )
    asymmetric: list[AtomSite] = []
    disorder_assemblies: list[str] = []
    disorder_groups: list[str] = []
    operations: list[str] = []
    for tags, rows in loops:
        if "_atom_site_label" in tags:
            indices = {tag: tags.index(tag) for tag in tags}
            required = ("_atom_site_label", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z")
            if not all(tag in indices for tag in required):
                continue
            for row in rows:
                label = _clean(row[indices["_atom_site_label"]])
                symbol_index = indices.get("_atom_site_type_symbol")
                occupancy_index = indices.get("_atom_site_occupancy")
                u_iso_index = indices.get("_atom_site_U_iso_or_equiv")
                b_iso_index = indices.get("_atom_site_B_iso_or_equiv")
                disorder_assembly_index = indices.get("_atom_site_disorder_assembly")
                disorder_group_index = indices.get("_atom_site_disorder_group")
                reported = {
                    "fract_x": parse_cif_number(
                        row[indices["_atom_site_fract_x"]], source_name="_atom_site_fract_x"
                    ),
                    "fract_y": parse_cif_number(
                        row[indices["_atom_site_fract_y"]], source_name="_atom_site_fract_y"
                    ),
                    "fract_z": parse_cif_number(
                        row[indices["_atom_site_fract_z"]], source_name="_atom_site_fract_z"
                    ),
                    "occupancy": parse_cif_number(
                        row[occupancy_index] if occupancy_index is not None else None,
                        source_name="_atom_site_occupancy",
                    ),
                    "U_iso_or_equiv": parse_cif_number(
                        row[u_iso_index] if u_iso_index is not None else None,
                        unit="Å²",
                        source_name="_atom_site_U_iso_or_equiv",
                    ),
                    "B_iso_or_equiv": parse_cif_number(
                        row[b_iso_index] if b_iso_index is not None else None,
                        unit="Å²",
                        source_name="_atom_site_B_iso_or_equiv",
                    ),
                }
                u_value = _number(row[u_iso_index]) if u_iso_index is not None else None
                if u_value is None and b_iso_index is not None:
                    b_value = _number(row[b_iso_index])
                    u_value = b_value / (8.0 * math.pi**2) if b_value is not None else None
                asymmetric.append(
                    AtomSite(
                        label=label,
                        element=_element(label, row[symbol_index] if symbol_index is not None else ""),
                        fractional=tuple(_number(row[indices[tag]], 0.0) for tag in required[1:]),
                        occupancy=_number(row[occupancy_index], 1.0) if occupancy_index is not None else 1.0,
                        u_iso=u_value,
                        reported=reported,
                        disorder_group=(
                            _clean(row[disorder_group_index])
                            if disorder_group_index is not None
                            else ""
                        ),
                        assembly=(
                            _clean(row[disorder_assembly_index])
                            if disorder_assembly_index is not None
                            else ""
                        ),
                        source_site_key=label,
                    )
                )
                disorder_assemblies.append(
                    row[disorder_assembly_index]
                    if disorder_assembly_index is not None
                    else ""
                )
                disorder_groups.append(
                    row[disorder_group_index]
                    if disorder_group_index is not None
                    else ""
                )
        for sym_tag in ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"):
            if sym_tag in tags:
                operations.extend(_clean(row[tags.index(sym_tag)]) for row in rows)
    if not asymmetric:
        raise ValueError("CIF does not contain atom-site fractional coordinates.")
    asymmetric = _normalize_site_labels(
        _merge_coincident_mixed_sites(asymmetric, disorder_assemblies, disorder_groups)
    )
    operations = operations or ["x,y,z"]
    return CrystalStructure(
        name=path.stem,
        cell=cell,
        asymmetric_sites=asymmetric,
        sites=expand_sites(asymmetric, operations) if expand_symmetry else list(asymmetric),
        symmetry_operations=operations,
        formula=_clean(values.get("_chemical_formula_sum")),
        space_group=_space_group_symbol(
            values.get("_space_group_name_H-M_alt") or values.get("_symmetry_space_group_name_H-M")
        ),
        source_path=path,
        source_data=_source_data(values, loops),
    )


def load_cif(path: str | Path, expand_symmetry: bool = True) -> CrystalStructure:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    errors: list[Exception] = []
    if gemmi is not None:
        try:
            return _load_with_gemmi(source, expand_symmetry)
        except (ValueError, RuntimeError) as error:
            errors.append(error)
    if expand_symmetry:
        try:
            return _load_with_pymatgen(source)
        except (ImportError, ModuleNotFoundError, ValueError, RuntimeError) as error:
            errors.append(error)
    try:
        return _load_fallback(source, expand_symmetry)
    except Exception as error:
        details = "; ".join(str(item) for item in (*errors, error))
        raise ValueError(f"All CIF readers failed: {details}") from error
