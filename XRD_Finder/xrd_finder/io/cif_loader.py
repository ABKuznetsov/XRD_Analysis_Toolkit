from __future__ import annotations

import math
import re
from pathlib import Path

from xrd_finder.core.phase import Phase
from xrd_finder.core.structure import AtomSite, CellParameters, Structure


def _clean_value(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().strip("'").strip('"')
    if text in {".", "?"}:
        return ""
    # CIF numbers often carry uncertainty as 24.70999(5). Keep chemical
    # groups such as Ca28 (Al57 Si135 O384), remove only numeric uncertainty.
    text = re.sub(r"(?<=\d)\([0-9]+\)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _float_or_none(value: str | None) -> float | None:
    try:
        text = _clean_value(value)
        return float(text.replace(",", ".")) if text else None
    except Exception:
        return None


def _int_or_none(value: str | None) -> int | None:
    try:
        text = _clean_value(value)
        return int(float(text)) if text else None
    except Exception:
        return None


def _cell_volume(a, b, c, alpha, beta, gamma) -> float | None:
    if None in (a, b, c, alpha, beta, gamma):
        return None
    ar, br, gr = math.radians(alpha), math.radians(beta), math.radians(gamma)
    term = 1 + 2 * math.cos(ar) * math.cos(br) * math.cos(gr)
    term -= math.cos(ar) ** 2 + math.cos(br) ** 2 + math.cos(gr) ** 2
    if term < 0:
        return None
    return a * b * c * math.sqrt(term)


def _guess_element(label: str, symbol: str = "") -> str:
    symbol = _clean_value(symbol)
    if symbol:
        match = re.match(r"([A-Z][a-z]?)", symbol)
        if match:
            return match.group(1)
    match = re.match(r"([A-Z][a-z]?)", _clean_value(label))
    return match.group(1) if match else symbol or label


def _normalize_formula(formula: str) -> str:
    return _clean_value(formula).replace(" ", "")


def _best_structure_name(*values: str) -> str:
    for value in values:
        cleaned = _clean_value(value)
        if cleaned:
            return cleaned
    return ""


def _gemmi_loop_values(block, tag: str, count: int) -> list[str]:
    loop = block.find_loop(tag)
    if loop is None:
        return [""] * count
    return [str(value) for value in loop]


def _gemmi_atoms(block) -> list[AtomSite]:
    labels = block.find_loop("_atom_site_label")
    if labels is None:
        return []
    labels = [str(label) for label in labels]
    symbols = _gemmi_loop_values(block, "_atom_site_type_symbol", len(labels))
    xs = _gemmi_loop_values(block, "_atom_site_fract_x", len(labels))
    ys = _gemmi_loop_values(block, "_atom_site_fract_y", len(labels))
    zs = _gemmi_loop_values(block, "_atom_site_fract_z", len(labels))
    occs = _gemmi_loop_values(block, "_atom_site_occupancy", len(labels))
    bisos = _gemmi_loop_values(block, "_atom_site_B_iso_or_equiv", len(labels))
    uisos = _gemmi_loop_values(block, "_atom_site_U_iso_or_equiv", len(labels))
    wyckoffs = _gemmi_loop_values(block, "_atom_site_Wyckoff_symbol", len(labels))
    multiplicities = _gemmi_loop_values(block, "_atom_site_symmetry_multiplicity", len(labels))

    atoms = []
    for index, label in enumerate(labels):
        atoms.append(
            AtomSite(
                label=_clean_value(label),
                element=_guess_element(label, symbols[index] if index < len(symbols) else ""),
                x=_float_or_none(xs[index] if index < len(xs) else None),
                y=_float_or_none(ys[index] if index < len(ys) else None),
                z=_float_or_none(zs[index] if index < len(zs) else None),
                occupancy=_float_or_none(occs[index] if index < len(occs) else None),
                biso=_float_or_none(bisos[index] if index < len(bisos) else None),
                uiso=_float_or_none(uisos[index] if index < len(uisos) else None),
                wyckoff=_clean_value(wyckoffs[index] if index < len(wyckoffs) else ""),
                multiplicity=_int_or_none(multiplicities[index] if index < len(multiplicities) else None),
            )
        )
    return atoms


def _gemmi_symops(block) -> list[str]:
    for tag in ["_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"]:
        loop = block.find_loop(tag)
        if loop is not None:
            ops = [_clean_value(str(value)).replace(" ", "") for value in loop]
            ops = [op for op in ops if op]
            if ops:
                return ops
        value = block.find_value(tag)
        op = _clean_value(str(value)).replace(" ", "") if value else ""
        if op:
            return [op]
    return ["x,y,z"]


def _gemmi_value(block, *tags: str) -> str:
    for tag in tags:
        value = block.find_value(tag)
        cleaned = _clean_value(str(value)) if value else ""
        if cleaned:
            return cleaned
    return ""


def _gemmi_loop_clean_values(block, tag: str) -> list[str]:
    loop = block.find_loop(tag)
    if loop is None:
        return []
    return [value for value in (_clean_value(str(item)) for item in loop) if value]


def _publication_details(metadata: dict[str, str]) -> str:
    lines = []
    title = metadata.get("publication_title", "")
    authors = metadata.get("publication_authors", "")
    journal = metadata.get("journal", "")
    year = metadata.get("year", "")
    volume = metadata.get("volume", "")
    pages = metadata.get("pages", "")
    doi = metadata.get("doi", "")
    if title:
        lines.append(title)
    if authors:
        lines.append(authors)
    journal_parts = [part for part in [journal, year, f"vol. {volume}" if volume else "", f"pp. {pages}" if pages else ""] if part]
    if journal_parts:
        lines.append(", ".join(journal_parts))
    if doi:
        lines.append(f"DOI {doi}")
    return "\n".join(lines)


def _gemmi_metadata(block) -> dict[str, str]:
    pages = ""
    page_first = _gemmi_value(block, "_journal_page_first")
    page_last = _gemmi_value(block, "_journal_page_last")
    if page_first and page_last:
        pages = f"{page_first}-{page_last}"
    elif page_first:
        pages = page_first
    metadata = {
        "chemical_name_mineral": _gemmi_value(block, "_chemical_name_mineral"),
        "chemical_name_common": _gemmi_value(block, "_chemical_name_common"),
        "chemical_name_systematic": _gemmi_value(block, "_chemical_name_systematic"),
        "formula_structural": _gemmi_value(block, "_chemical_formula_structural"),
        "formula_sum": _gemmi_value(block, "_chemical_formula_sum"),
        "formula_calculated": _gemmi_value(block, "_chemical_formula_analytical", "_chemical_formula_iupac"),
        "publication_title": _gemmi_value(block, "_publ_section_title"),
        "publication_authors": "; ".join(_gemmi_loop_clean_values(block, "_publ_author_name")),
        "journal": _gemmi_value(block, "_journal_name_full"),
        "year": _gemmi_value(block, "_journal_year"),
        "volume": _gemmi_value(block, "_journal_volume"),
        "pages": pages,
        "doi": _gemmi_value(block, "_journal_paper_doi", "_publ_section_references"),
    }
    metadata["publication"] = _publication_details(metadata)
    return {key: value for key, value in metadata.items() if value}


def _fallback_loop(text: str, required_tag: str) -> tuple[list[str], list[list[str]]]:
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip().lower() != "loop_":
            index += 1
            continue
        cursor = index + 1
        tags = []
        while cursor < len(lines) and lines[cursor].strip().startswith("_"):
            tags.append(lines[cursor].strip().split()[0])
            cursor += 1
        if required_tag not in tags:
            index = cursor
            continue
        rows = []
        while cursor < len(lines):
            line = lines[cursor].strip()
            if not line or line.lower() == "loop_" or line.startswith("_") or line.startswith("data_"):
                break
            if not line.startswith("#"):
                parts = re.findall(r"(?:'[^']*'|\"[^\"]*\"|\S+)", line)
                if len(parts) >= len(tags):
                    rows.append(parts[: len(tags)])
            cursor += 1
        return tags, rows
    return [], []


def _fallback_atoms(text: str) -> list[AtomSite]:
    tags, rows = _fallback_loop(text, "_atom_site_label")
    if not tags:
        return []
    tag_index = {tag: index for index, tag in enumerate(tags)}

    def get(row: list[str], tag: str) -> str:
        index = tag_index.get(tag)
        return row[index] if index is not None and index < len(row) else ""

    atoms = []
    for row in rows:
        label = _clean_value(get(row, "_atom_site_label"))
        atoms.append(
            AtomSite(
                label=label,
                element=_guess_element(label, get(row, "_atom_site_type_symbol")),
                x=_float_or_none(get(row, "_atom_site_fract_x")),
                y=_float_or_none(get(row, "_atom_site_fract_y")),
                z=_float_or_none(get(row, "_atom_site_fract_z")),
                occupancy=_float_or_none(get(row, "_atom_site_occupancy")),
                biso=_float_or_none(get(row, "_atom_site_B_iso_or_equiv")),
                uiso=_float_or_none(get(row, "_atom_site_U_iso_or_equiv")),
                wyckoff=_clean_value(get(row, "_atom_site_Wyckoff_symbol")),
                multiplicity=_int_or_none(get(row, "_atom_site_symmetry_multiplicity")),
            )
        )
    return atoms


def _fallback_symops(text: str) -> list[str]:
    for tag in ["_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"]:
        tags, rows = _fallback_loop(text, tag)
        if tags:
            tag_index = tags.index(tag)
            ops = [_clean_value(row[tag_index]).replace(" ", "") for row in rows if len(row) > tag_index]
            ops = [op for op in ops if op]
            if ops:
                return ops
        match = re.search(rf"^{re.escape(tag)}\s+(.+)$", text, flags=re.MULTILINE)
        if match:
            op = _clean_value(match.group(1)).replace(" ", "")
            if op:
                return [op]
    return ["x,y,z"]


def _fallback_values(text: str) -> dict[str, str]:
    values = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 1 and parts[0].startswith("_") and index + 1 < len(lines) and lines[index + 1].strip() == ";":
            tag = parts[0]
            index += 2
            value_lines = []
            while index < len(lines) and lines[index].strip() != ";":
                value_lines.append(lines[index].strip())
                index += 1
            values[tag] = " ".join(value_lines).strip()
        elif len(parts) == 2 and parts[0].startswith("_"):
            values[parts[0]] = parts[1].strip()
        index += 1
    return values


def _fallback_metadata(text: str, values: dict[str, str]) -> dict[str, str]:
    def value(*keys: str) -> str:
        for key in keys:
            if key in values:
                return _clean_value(values[key])
        return ""

    author_tags, author_rows = _fallback_loop(text, "_publ_author_name")
    authors = []
    if author_tags:
        author_index = author_tags.index("_publ_author_name")
        authors = [_clean_value(row[author_index]) for row in author_rows if len(row) > author_index]
        authors = [author for author in authors if author]
    pages = ""
    page_first = value("_journal_page_first")
    page_last = value("_journal_page_last")
    if page_first and page_last:
        pages = f"{page_first}-{page_last}"
    elif page_first:
        pages = page_first
    metadata = {
        "chemical_name_mineral": value("_chemical_name_mineral"),
        "chemical_name_common": value("_chemical_name_common"),
        "chemical_name_systematic": value("_chemical_name_systematic"),
        "formula_structural": value("_chemical_formula_structural"),
        "formula_sum": value("_chemical_formula_sum"),
        "publication_title": value("_publ_section_title"),
        "publication_authors": "; ".join(authors),
        "journal": value("_journal_name_full"),
        "year": value("_journal_year"),
        "volume": value("_journal_volume"),
        "pages": pages,
        "doi": value("_journal_paper_doi"),
    }
    metadata["publication"] = _publication_details(metadata)
    return {key: val for key, val in metadata.items() if val}


def _read_structure_from_cif(path: Path) -> Structure:
    try:
        import gemmi

        doc = gemmi.cif.read_file(str(path))
        block = doc.sole_block()
        a = _float_or_none(str(block.find_value("_cell_length_a") or ""))
        b = _float_or_none(str(block.find_value("_cell_length_b") or ""))
        c = _float_or_none(str(block.find_value("_cell_length_c") or ""))
        alpha = _float_or_none(str(block.find_value("_cell_angle_alpha") or ""))
        beta = _float_or_none(str(block.find_value("_cell_angle_beta") or ""))
        gamma = _float_or_none(str(block.find_value("_cell_angle_gamma") or ""))
        if None in (a, b, c, alpha, beta, gamma):
            raise ValueError("CIF cell parameters are incomplete")
        metadata = _gemmi_metadata(block)
        formula = metadata.get("formula_sum") or metadata.get("formula_structural") or ""
        name = _best_structure_name(
            metadata.get("chemical_name_mineral", ""),
            metadata.get("chemical_name_common", ""),
            metadata.get("chemical_name_systematic", ""),
            str(block.name or ""),
            path.stem,
        )
        if str(name).isdigit() and formula:
            name = _normalize_formula(str(formula))
        structure = Structure.create(name=str(name), source_path=str(path), origin="original")
        structure.formula = _normalize_formula(str(formula))
        structure.metadata.update(metadata)
        structure.space_group = str(
            block.find_value("_symmetry_space_group_name_H-M")
            or block.find_value("_space_group_name_H-M_alt")
            or ""
        ).strip("'\"")
        structure.space_group_number = str(
            block.find_value("_symmetry_Int_Tables_number")
            or block.find_value("_space_group_IT_number")
            or ""
        ).strip("'\"")
        structure.wavelength = _float_or_none(str(block.find_value("_cell_measurement_wavelength") or ""))
        cell = gemmi.UnitCell(a, b, c, alpha, beta, gamma)
        structure.cell = CellParameters(a=a, b=b, c=c, alpha=alpha, beta=beta, gamma=gamma, volume=float(cell.volume))
        structure.atoms = _gemmi_atoms(block)
        structure.symops = _gemmi_symops(block)
        structure.atom_count = len(structure.atoms)
        return structure
    except Exception:
        pass

    text = path.read_text(encoding="utf-8", errors="ignore")
    values = _fallback_values(text)

    def value(*keys: str) -> str:
        for key in keys:
            if key in values:
                return values[key]
        return ""

    a = _float_or_none(value("_cell_length_a"))
    b = _float_or_none(value("_cell_length_b"))
    c = _float_or_none(value("_cell_length_c"))
    alpha = _float_or_none(value("_cell_angle_alpha"))
    beta = _float_or_none(value("_cell_angle_beta"))
    gamma = _float_or_none(value("_cell_angle_gamma"))
    formula = _normalize_formula(value("_chemical_formula_sum", "_chemical_formula_structural"))
    metadata = _fallback_metadata(text, values)
    name = _best_structure_name(
        value("_chemical_name_mineral"),
        value("_chemical_name_common"),
        value("_chemical_name_systematic"),
        formula,
        path.stem,
    )
    structure = Structure.create(name=name, source_path=str(path), origin="original")
    structure.formula = formula
    structure.metadata.update(metadata)
    structure.space_group = _clean_value(value("_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt"))
    structure.space_group_number = _clean_value(value("_symmetry_Int_Tables_number", "_space_group_IT_number"))
    structure.wavelength = _float_or_none(value("_cell_measurement_wavelength"))
    structure.cell = CellParameters(
        a=a,
        b=b,
        c=c,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        volume=_float_or_none(value("_cell_volume")) or _cell_volume(a, b, c, alpha, beta, gamma),
    )
    structure.atoms = _fallback_atoms(text)
    structure.symops = _fallback_symops(text)
    structure.atom_count = len(structure.atoms)
    return structure


def create_phase_from_cif(path: str | Path) -> tuple[Phase, Structure]:
    source = Path(path)
    structure = _read_structure_from_cif(source)
    phase = Phase.create(name=structure.name or source.stem, source_path=str(source))
    phase.formula = structure.formula
    phase.space_group = structure.space_group
    phase.structure_id = structure.id
    structure.phase_id = phase.id
    return phase, structure
