import numpy as np

from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.measurement import MissingState, parse_cif_number


def test_parse_cif_number_preserves_esd_and_raw_token() -> None:
    result = parse_cif_number("7.7360(2)", unit="Å", source_name="_cell_length_a")

    assert result.raw == "7.7360(2)"
    assert result.value == 7.7360
    assert result.su == 0.0002
    assert result.unit == "Å"
    assert result.source_name == "_cell_length_a"
    assert result.state is MissingState.PRESENT


def test_parse_cif_number_handles_exponent_and_decimal_esd() -> None:
    result = parse_cif_number("1.234(5)e2")

    assert result.value == 123.4
    assert result.su == 0.5


def test_parse_cif_number_distinguishes_dot_question_and_absent() -> None:
    assert parse_cif_number(".").state is MissingState.MISSING
    assert parse_cif_number("?").state is MissingState.UNKNOWN
    assert parse_cif_number(None).state is MissingState.ABSENT


def test_cif_ingestion_preserves_reported_values_and_converts_b_iso(tmp_path) -> None:
    path = tmp_path / "esd.cif"
    path.write_text(
        """data_esd
_cell_length_a 7.7360(2)
_cell_length_b 7.7360(2)
_cell_length_c 5.1230(3)
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_refine_ls_R_factor_gt 0.0412
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_B_iso_or_equiv
Al1 Al 0 0 0.1234(5) 0.75(2) 1.20(4)
""",
        encoding="utf-8",
    )

    structure = load_cif(path, expand_symmetry=False)

    assert structure.cell.a == 7.736
    assert structure.source_data.numeric("_cell_length_a").su == 0.0002
    assert structure.source_data.raw("_refine_ls_R_factor_gt") == "0.0412"
    site = structure.asymmetric_sites[0]
    assert site.reported["fract_z"].raw == "0.1234(5)"
    assert site.reported["occupancy"].su == 0.02
    assert site.reported["B_iso_or_equiv"].unit == "Å²"
    assert np.isclose(site.u_iso, 1.20 / (8.0 * np.pi**2))


def test_cif_source_mappings_are_immutable(tmp_path) -> None:
    path = tmp_path / "minimal.cif"
    path.write_text(
        """data_minimal
_cell_length_a 1
_cell_length_b 1
_cell_length_c 1
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
O1 O 0 0 0
""",
        encoding="utf-8",
    )
    structure = load_cif(path, expand_symmetry=False)

    try:
        structure.source_data.scalars["_cell_length_a"] = "2"
    except TypeError:
        pass
    else:
        raise AssertionError("CIF scalar data must be immutable")

    try:
        structure.asymmetric_sites[0].reported["fract_x"] = parse_cif_number("1")
    except TypeError:
        pass
    else:
        raise AssertionError("Reported site data must be immutable")
