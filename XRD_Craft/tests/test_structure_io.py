from __future__ import annotations

from pathlib import Path

import pytest

from crystal_viewer.core.structure_io import (
    is_supported_structure_path,
    load_structure_files,
)


SHELX_RES = """\
TITL test in P2(1)/n
CELL 0.71073 17.6787 4.4989 24.7670 90.000 90.987 90.000
ZERR 5.0000 0.0021 0.0005 0.0021 0.000 0.008 0.000
LATT 1
SYMM 0.5-X, 0.5+Y, 0.5-Z
SFAC C H N O S AG
UNIT 60 40 10 20 10 5
FVAR 0.55079
AG1 6 0.044425 0.947004 0.198152 11.00000 0.05554
S3  5 0.340082 0.525717 0.214517 11.00000 0.04947
C1  1 0.106507 1.433210 0.096736 11.00000 0.05548 =
       0.03094 0.01587 -0.00145 -0.00054
HKLF 4
END
Q1 1 0.0220 1.0912 0.1859 11.00000 0.05 1.44
"""


def test_shelx_res_ignores_refinement_commands_and_difference_peaks(tmp_path: Path) -> None:
    source = tmp_path / "zdk288.res"
    source.write_text(SHELX_RES, encoding="utf-8")

    (structure,) = load_structure_files(source)

    assert structure.name == "test"
    assert structure.cell.a == pytest.approx(17.6787)
    assert structure.cell.beta == pytest.approx(90.987)
    assert [(site.label, site.element) for site in structure.asymmetric_sites] == [
        ("Ag1", "Ag"),
        ("S3", "S"),
        ("C1", "C"),
    ]
    assert len(structure.symmetry_operations) == 4
    assert len(structure.sites) == 12
    assert all(not site.label.startswith("Q") for site in structure.sites)


def test_shelx_accepts_one_scattering_factor_record_per_element(tmp_path: Path) -> None:
    source = tmp_path / "separate-sfac.ins"
    source.write_text(
        "TITL separate SFAC\nCELL 0.71073 10 10 10 90 90 90\nLATT -1\n"
        "SFAC C 2.31 20.84 1.02 10.21 1.59 0.57 0.87 51.65 0.22 0 0 0\n"
        "SFAC O 3.05 13.28 2.29 5.70 1.55 0.32 0.87 32.91 0.25 0 0 0\n"
        "UNIT 1 1\nC1 1 0.1 0.2 0.3 11 0.05\nO1 2 0.2 0.2 0.3 11 0.05\nEND\n",
        encoding="utf-8",
    )

    (structure,) = load_structure_files(source)

    assert [site.element for site in structure.asymmetric_sites] == ["C", "O"]


def test_shelx_strips_inline_comments_and_accepts_ionic_sfac_labels(tmp_path: Path) -> None:
    source = tmp_path / "ionic.res"
    source.write_text(
        "TITL ionic labels\nCELL 0.71073 10 10 10 90 90 90\nLATT -1\n"
        "SYMM -X, Y, -Z ! twofold operation\n"
        "SFAC Ca2+ $C O ! ionic and special scattering-factor labels\n"
        "CA1 1 0.1 0.2 0.3 11 0.05\n"
        "C1 2 0.2 0.2 0.3 11 0.05\n"
        "O1 3 0.3 0.2 0.3 11 0.05\nEND\n",
        encoding="utf-8",
    )

    (structure,) = load_structure_files(source)

    assert [site.element for site in structure.asymmetric_sites] == ["Ca", "C", "O"]
    assert len(structure.symmetry_operations) == 2


def test_xyz_receives_a_padded_non_periodic_display_cell(tmp_path: Path) -> None:
    source = tmp_path / "water.xyz"
    source.write_text(
        "3\nwater molecule\nO 0 0 0\nH 0.96 0 0\nH -0.24 0.93 0\n",
        encoding="utf-8",
    )

    (structure,) = load_structure_files(source)

    assert structure.name == "water molecule"
    assert [site.element for site in structure.sites] == ["O", "H", "H"]
    assert min(structure.cell.a, structure.cell.b, structure.cell.c) >= 10.0
    assert structure.space_group == "molecule (display cell)"
    assert all(0.0 < value < 1.0 for site in structure.sites for value in site.fractional)


def test_poscar_is_adapted_to_the_shared_crystal_model(tmp_path: Path) -> None:
    source = tmp_path / "POSCAR"
    source.write_text(
        "example\n1.0\n3 0 0\n0 4 0\n0 0 5\nC O\n1 1\nDirect\n0 0 0\n0.5 0.5 0.5\n",
        encoding="utf-8",
    )

    (structure,) = load_structure_files(source)

    assert (structure.cell.a, structure.cell.b, structure.cell.c) == pytest.approx((3, 4, 5))
    assert [site.element for site in structure.sites] == ["C", "O"]
    assert structure.source_path == source.resolve()


def test_pdb_cryst1_and_atoms_are_adapted_without_losing_the_cell(tmp_path: Path) -> None:
    source = tmp_path / "molecule.pdb"
    source.write_text(
        "CRYST1   10.000   12.000   14.000  90.00  90.00  90.00 P 1           1\n"
        "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00 20.00           C\n"
        "HETATM    2  O1  LIG A   1       2.000   2.000   3.000  0.50 20.00           O\n"
        "END\n",
        encoding="utf-8",
    )

    (structure,) = load_structure_files(source)

    assert structure.space_group == "P 1"
    assert (structure.cell.a, structure.cell.b, structure.cell.c) == pytest.approx((10, 12, 14))
    assert structure.sites[0].fractional == pytest.approx((0.1, 1 / 6, 3 / 14))
    assert structure.sites[1].occupancy == pytest.approx(0.5)


def test_pdb_infers_elements_from_aligned_atom_names_when_column_is_blank(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.pdb"
    source.write_text(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00\n"
        "ATOM      2  CD  GLU A   1       2.000   2.000   3.000  1.00 20.00\n"
        "ATOM      3  HG  CYS A   1       3.000   2.000   3.000  1.00 20.00\n"
        "HETATM    4 CA   CA  A   2       4.000   2.000   3.000  1.00 20.00\n"
        "ATOM      5 1HG  CYS A   1       5.000   2.000   3.000  1.00 20.00\n"
        "ATOM      6 2HE  GLN A   1       6.000   2.000   3.000  1.00 20.00\n"
        "END\n",
        encoding="utf-8",
    )

    (structure,) = load_structure_files(source)

    assert [site.element for site in structure.sites] == ["C", "C", "H", "Ca", "H", "H"]


@pytest.mark.parametrize(
    ("filename", "supported"),
    (
        ("sample.cif", True),
        ("sample.xpff", True),
        ("sample.res", True),
        ("sample.ins", True),
        ("POSCAR", True),
        ("CONTCAR", True),
        ("sample.vasp", True),
        ("sample.pdb", True),
        ("sample.xyz", True),
        ("notes.txt", False),
    ),
)
def test_supported_structure_path_is_shared_by_dialog_and_drop(
    filename: str,
    supported: bool,
) -> None:
    assert is_supported_structure_path(filename) is supported
