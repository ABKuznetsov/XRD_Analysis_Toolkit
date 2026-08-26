from pathlib import Path

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.analysis.reporting import Provenance
from crystal_viewer.analysis.reporting.geometry import (
    GeometrySettings,
    build_angle_table,
    build_bond_table,
)
from crystal_viewer.core.cif import load_cif


ROOT = Path(__file__).resolve().parents[1]


def test_bonds_are_unique_and_keep_periodic_image() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    table = build_bond_table(structure, hierarchy, GeometrySettings())

    keys = [row.id for row in table.rows]
    assert len(keys) == len(set(keys))
    assert all("symmetry" in row.cells for row in table.rows)
    assert all(row.cells["distance"].provenance is Provenance.CALCULATED for row in table.rows)
    assert all("(" not in row.cells["distance"].display for row in table.rows)


def test_bridge_angle_is_present_for_pyro_group() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    table = build_angle_table(structure, hierarchy, GeometrySettings())

    bridge_rows = [row for row in table.rows if row.cells["kind"].display == "bridge"]
    assert len(bridge_rows) == 1
    # The analytical demo places Si–O–Si exactly on one Cartesian line.
    assert 90.0 < float(bridge_rows[0].cells["angle"].value) <= 180.0


def test_reported_bond_keeps_esd_symmetry_and_publication_flag(tmp_path) -> None:
    path = tmp_path / "reported_geometry.cif"
    path.write_text(
        """data_reported
_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Al1 Al 0 0 0
O1 O 0.34 0 0
loop_
_geom_bond_atom_site_label_1
_geom_bond_atom_site_label_2
_geom_bond_distance
_geom_bond_site_symmetry_1
_geom_bond_site_symmetry_2
_geom_bond_publ_flag
Al1 O1 1.734(4) . 1_555 yes
""",
        encoding="utf-8",
    )
    structure = load_cif(path, expand_symmetry=False)
    hierarchy = HierarchyAnalyzer().analyze(structure)

    table = build_bond_table(structure, hierarchy, GeometrySettings())

    assert len(table.rows) == 1
    row = table.rows[0]
    distance = row.cells["distance"]
    assert distance.display == "1.734(4)"
    assert distance.value.su == 0.004
    assert distance.provenance is Provenance.REPORTED
    assert row.cells["symmetry"].display == ". / 1_555"
    assert row.include_in_publication is True
