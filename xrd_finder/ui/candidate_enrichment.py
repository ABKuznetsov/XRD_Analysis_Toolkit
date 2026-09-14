from __future__ import annotations

from xrd_finder.core.structure import CellParameters


def crystal_system_from_cell(cell: CellParameters) -> str:
    lengths = [cell.a, cell.b, cell.c]
    angles = [cell.alpha, cell.beta, cell.gamma]
    if any(value is None for value in lengths + angles):
        return ""
    a, b, c = (float(value) for value in lengths)
    alpha, beta, gamma = (float(value) for value in angles)

    def close(left: float, right: float, tolerance: float = 0.03) -> bool:
        return abs(left - right) <= tolerance

    def angle90(value: float) -> bool:
        return abs(value - 90.0) <= 0.2

    if all(angle90(value) for value in (alpha, beta, gamma)):
        if close(a, b) and close(b, c):
            return "cubic"
        if close(a, b):
            return "tetragonal"
        return "orthorhombic"
    if angle90(alpha) and angle90(beta) and abs(gamma - 120.0) <= 0.3 and close(a, b):
        return "hexagonal/trigonal"
    if sum(angle90(value) for value in (alpha, beta, gamma)) == 2:
        return "monoclinic"
    return "triclinic"


def format_cell(cell: CellParameters) -> str:
    return (
        f"a {cell.a:.4g}   b {cell.b:.4g}   c {cell.c:.4g}\n"
        f"alpha {cell.alpha:.4g}   beta {cell.beta:.4g}   gamma {cell.gamma:.4g}"
    )


def has_complete_cell(cell: CellParameters) -> bool:
    return all(getattr(cell, name, None) is not None for name in ("a", "b", "c", "alpha", "beta", "gamma"))


def enrich_candidate_from_structure(
    candidate: dict[str, str],
    structure,
    display_formula,
    diffraction_rows_for_structure,
) -> None:
    if structure.name:
        candidate["Phase"] = structure.name
    if structure.formula:
        candidate["Formula"] = display_formula(structure.formula)
    candidate["Space group"] = structure.space_group or structure.space_group_number or ""
    cell = structure.cell
    if has_complete_cell(cell):
        candidate["Cell"] = format_cell(cell)
        candidate["Crystal system"] = crystal_system_from_cell(cell)

    atoms = []
    atom_rows = []
    for atom in (structure.atoms or [])[:48]:
        coords = []
        for value in (atom.x, atom.y, atom.z):
            coords.append(f"{value:.4g}" if value is not None else "?")
        occ = f", occ={atom.occupancy:.3g}" if atom.occupancy is not None else ""
        atoms.append(f"{atom.label or atom.element} {atom.element} ({', '.join(coords)}{occ})")
        b_value = atom.biso if atom.biso is not None else atom.uiso
        atom_rows.append(
            [
                atom.label or atom.element,
                atom.element,
                coords[0],
                coords[1],
                coords[2],
                f"{atom.occupancy:.3g}" if atom.occupancy is not None else "",
                f"{b_value:.3g}" if b_value is not None else "",
            ]
        )
    if atoms:
        suffix = "" if len(structure.atoms) <= 48 else f"\n... +{len(structure.atoms) - 48} atoms"
        candidate["Atoms"] = "\n".join(atoms) + suffix
        candidate["_AtomRows"] = atom_rows

    diffraction_rows = diffraction_rows_for_structure(structure)
    if diffraction_rows:
        candidate["_DiffractionRows"] = diffraction_rows
    publication = str(structure.metadata.get("publication", "") or "")
    if publication:
        candidate["Notes"] = publication
    doi = str(structure.metadata.get("doi", "") or "")
    if doi:
        candidate["DOI"] = doi


def enrich_candidate_from_pdf2_details(candidate: dict[str, str], details: dict, peaks) -> None:
    if details.get("space_group"):
        candidate["Space group"] = str(details.get("space_group", ""))
    if details.get("space_group_number"):
        candidate["Space group"] = " ".join(
            part for part in [candidate.get("Space group", ""), str(details.get("space_group_number", ""))] if part
        )
    cell_details = details.get("cell")
    if isinstance(cell_details, dict):
        cell = CellParameters(
            a=cell_details.get("a"),
            b=cell_details.get("b"),
            c=cell_details.get("c"),
            alpha=cell_details.get("alpha"),
            beta=cell_details.get("beta"),
            gamma=cell_details.get("gamma"),
            volume=cell_details.get("volume"),
        )
        if has_complete_cell(cell):
            candidate["Cell"] = format_cell(cell)
            candidate["Crystal system"] = crystal_system_from_cell(cell)
    if not peaks:
        return
    candidate["_DiffractionRows"] = [
        [
            f"{getattr(peak, 'd_spacing', 0.0):.5g}",
            f"{getattr(peak, 'two_theta', 0.0):.5g}",
            f"{getattr(peak, 'intensity', 0.0):.3g}",
            str(getattr(peak, "h", "") or ""),
            str(getattr(peak, "k", "") or ""),
            str(getattr(peak, "l", "") or ""),
            "",
        ]
        for peak in peaks[:80]
    ]
