from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import crystal_viewer.core.cif as cif_module
from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyAnalyzer,
    HierarchyReport,
    polyhedron_rigidity_index,
)
from crystal_viewer.analysis.motif_graph import build_motif_graph
from crystal_viewer.analysis.motion import compare_block_coordinates
from crystal_viewer.analysis.reporting.crystal import build_atomic_sites_table
from crystal_viewer.analysis.reporting.model import Provenance
from crystal_viewer.analysis.series import analyze_structure_series
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.chemistry import (
    COVALENT_RADII,
    ELEMENT_COLORS,
    SiteRole,
    site_elements,
    site_colour,
    site_radius,
    site_role,
)
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, SiteComponent, UnitCell
from crystal_viewer.core.scene import build_scene
from crystal_viewer.core.symmetry import apply_operation, expand_sites

ROOT = Path(__file__).resolve().parents[1]


def test_mixed_site_chemistry_uses_occupied_components_instead_of_combined_label() -> None:
    site = AtomSite(
        "M1",
        "Na/Li",
        (0.0, 0.0, 0.0),
        components=(SiteComponent("Na", 0.75), SiteComponent("Li", 0.25)),
    )

    estimate = site_radius(site)

    assert site_elements(site) == ("Na", "Li")
    assert estimate.value == pytest.approx(1.565)
    assert estimate.method == "occupancy-weighted-covalent"
    assert estimate.estimated is False
    assert site_colour(site) not in {"#aab4c0", "#c7d0da", "#778596"}
    assert site_colour(site) == site_colour(
        AtomSite(
            "M2",
            "Li/Na",
            (0.0, 0.0, 0.0),
            components=(SiteComponent("Li", 0.25), SiteComponent("Na", 0.75)),
        )
    )


def test_mixed_site_role_preserves_anion_and_ambiguous_composition() -> None:
    anion = AtomSite(
        "X1",
        "O/F",
        (0.0, 0.0, 0.0),
        components=(SiteComponent("O", 0.6), SiteComponent("F", 0.3)),
    )
    ambiguous = AtomSite(
        "X2",
        "O/Fe",
        (0.0, 0.0, 0.0),
        components=(SiteComponent("O", 0.5), SiteComponent("Fe", 0.5)),
    )

    assert site_role(anion) is SiteRole.ANION
    assert anion.vacancy_fraction == pytest.approx(0.1)
    assert site_role(ambiguous) is SiteRole.AMBIGUOUS


def test_periodic_table_has_finite_colour_and_radius_provenance() -> None:
    from pymatgen.core import Element

    for atomic_number in range(1, 119):
        symbol = Element.from_Z(atomic_number).symbol
        estimate = site_radius(AtomSite(symbol, symbol, (0.0, 0.0, 0.0)))
        assert np.isfinite(estimate.value) and estimate.value > 0.0
        assert COVALENT_RADII[symbol] == estimate.value
        assert ELEMENT_COLORS[symbol].startswith("#")
        assert len(ELEMENT_COLORS[symbol]) == 7

    assert site_radius(AtomSite("Og1", "Og", (0.0, 0.0, 0.0))).estimated is True


@pytest.mark.parametrize(
    ("filename", "space_group", "operation_count"),
    (
        ("primitive_cubic.cif", "P1", 1),
        ("body_centered.cif", "I222", 8),
        ("screw_axis.cif", "P12_11", 2),
    ),
)
def test_morphology_fixture_preserves_space_group_operations(
    filename: str,
    space_group: str,
    operation_count: int,
) -> None:
    structure = load_cif(ROOT / "tests" / "data" / "morphology" / filename)

    assert structure.space_group.replace(" ", "") == space_group
    assert len(structure.symmetry_operations) == operation_count


def test_unit_cell_volume_and_transform() -> None:
    cell = UnitCell(3.0, 4.0, 5.0)
    assert np.isclose(cell.volume, 60.0)
    assert np.allclose(cell.frac_to_cart((0.5, 0.5, 0.5)), (1.5, 2.0, 2.5))


def test_scene_fractional_bounds_add_only_the_requested_cell_slices() -> None:
    sites = (
        AtomSite("X1", "C", (0.05, 0.5, 0.5)),
        AtomSite("X2", "C", (0.50, 0.5, 0.5)),
        AtomSite("X3", "C", (0.95, 0.5, 0.5)),
    )
    structure = CrystalStructure(
        name="bounded",
        cell=UnitCell(10.0, 10.0, 10.0),
        asymmetric_sites=sites,
        sites=sites,
    )

    scene = build_scene(
        structure,
        bounds=((-0.1, 1.1), (0.0, 1.0), (0.0, 1.0)),
        include_bonds=False,
        complete_boundary=False,
    )

    assert sorted(round(atom.fractional[0], 2) for atom in scene.atoms) == [
        -0.05,
        0.05,
        0.5,
        0.95,
        1.05,
    ]
    assert np.allclose(scene.cell_corners[0], (-1.0, 0.0, 0.0))
    assert np.allclose(scene.cell_corners[6], (11.0, 10.0, 10.0))


def test_scene_fractional_bounds_require_an_increasing_interval() -> None:
    sites = (AtomSite("C1", "C", (0.5, 0.5, 0.5)),)
    structure = CrystalStructure(
        name="invalid-bounds",
        cell=UnitCell(1.0, 1.0, 1.0),
        asymmetric_sites=sites,
        sites=sites,
    )

    with pytest.raises(ValueError, match="minimum must be smaller"):
        build_scene(structure, bounds=((0.5, 0.5), (0.0, 1.0), (0.0, 1.0)))


def test_safe_symmetry_expansion() -> None:
    assert np.allclose(apply_operation("-x+1/2,y,z+1/2", (0.1, 0.2, 0.3)), (0.4, 0.2, 0.8))
    site = AtomSite("O1", "O", (0.1, 0.2, 0.3))
    expanded = expand_sites([site], ["x,y,z", "-x,-y,-z"])
    assert len(expanded) == 2


def test_symmetry_expansion_merges_rounded_special_position_equivalents() -> None:
    """A site of order two must not become two atoms from rounded CIF coordinates."""
    site = AtomSite("B11", "B", (0.9155, 0.5822, -0.16667))
    operations = [
        "x, y, z",
        "-y, x-y, z",
        "-x+y, -x, z",
        "y, x, -z",
        "x-y, -y, -z",
        "-x, -x+y, -z",
        "x+2/3, y+1/3, z+1/3",
        "-y+2/3, x-y+1/3, z+1/3",
        "-x+y+2/3, -x+1/3, z+1/3",
        "y+2/3, x+1/3, -z+1/3",
        "x-y+2/3, -y+1/3, -z+1/3",
        "-x+2/3, -x+y+1/3, -z+1/3",
        "x+1/3, y+2/3, z+2/3",
        "-y+1/3, x-y+2/3, z+2/3",
        "-x+y+1/3, -x+2/3, z+2/3",
        "y+1/3, x+2/3, -z+2/3",
        "x-y+1/3, -y+2/3, -z+2/3",
        "-x+1/3, -x+y+2/3, -z+2/3",
    ]

    expanded = expand_sites([site], operations)

    assert len(expanded) == 9


def test_demo_cif_builds_hierarchy() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    report = HierarchyAnalyzer().analyze(structure)
    assert structure.display_formula == "Si2 O7"
    assert len(report.polyhedra) == 2
    assert all(polyhedron.type_name == "SiO4" for polyhedron in report.polyhedra)
    assert len(report.structural_units) == 1
    assert report.structural_units[0].classification == "pyro group"
    assert len(report.blocks) == 1
    assert report.blocks[0].classification == "pyro group"
    assert len(report.connectors) == 0
    expected_index = 4.0 / (4.0 * 0.26)
    assert np.isclose(polyhedron_rigidity_index(report.polyhedra[0]), expected_index)
    assert np.isclose(report.blocks[0].rigidity_index, expected_index)
    assert np.isclose(report.blocks[0].rigidity_score, expected_index / (1.0 + expected_index))


def test_gehlenite_example_has_a_rich_hierarchy() -> None:
    structure = load_cif(ROOT / "examples" / "gehlenite_Ca2Al2SiO7.cif")
    report = HierarchyAnalyzer().analyze(structure)
    polyhedron_types = {polyhedron.type_name for polyhedron in report.polyhedra}
    assert structure.display_formula == "Ca4 Al4 Si2 O14"
    assert len(structure.sites) == 24
    assert polyhedron_types == {"CaO8", "AlO4", "SiO4"}
    assert len(report.polyhedra) == 10
    unit_types = [unit.classification for unit in report.structural_units]
    assert unit_types.count("interlayer polyhedron") == 4
    assert unit_types.count("linking tetrahedron") == 2
    assert unit_types.count("tetrahedral unit") == 4
    assert len(report.blocks) == 10
    assert len(report.connectors) == 10


def test_average_gehlenite_preserves_the_mixed_t2_site() -> None:
    structure = load_cif(ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif")
    report = HierarchyAnalyzer().analyze(structure)
    assert structure.space_group.replace(" ", "") == "P-42_1m"
    assert sum(site.element == "Al/Si" for site in structure.sites) == 4
    assert sum(polyhedron.type_name == "(Al/Si)O4" for polyhedron in report.polyhedra) == 4
    assert sum(unit.classification == "tetrahedral unit" for unit in report.structural_units) == 4

    mixed = next(site for site in structure.sites if site.element == "Al/Si")
    assert mixed.components == (
        SiteComponent("Al", 0.5),
        SiteComponent("Si", 0.5),
    )
    assert np.isclose(mixed.vacancy_fraction, 0.0)


def test_coincident_complementary_occupancies_merge_despite_different_site_numbers(
    tmp_path,
) -> None:
    source = (ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif").read_text(
        encoding="utf-8"
    )
    path = tmp_path / "cod-style-labels.cif"
    path.write_text(
        source.replace("Al_T2", "Al2").replace("Si_T2", "Si1"),
        encoding="utf-8",
    )

    structure = load_cif(path)
    report = HierarchyAnalyzer().analyze(structure)

    assert sum(site.element == "Al/Si" for site in structure.sites) == 4
    assert sum(polyhedron.type_name == "(Al/Si)O4" for polyhedron in report.polyhedra) == 4
    assert len(report.polyhedra) == 10


def test_fallback_cif_merges_four_same_identity_mixed_positions_before_graph_build(
    monkeypatch,
) -> None:
    monkeypatch.setattr(cif_module, "gemmi", None)
    structure = load_cif(
        ROOT / "tests" / "data" / "mixed_occupancy_positions.cif",
        expand_symmetry=False,
    )

    mixed = tuple(site for site in structure.sites if len(site.components) == 2)
    assert tuple(site.label for site in mixed) == (
        "Na06/Li06",
        "Na07/Li07",
        "Na00/Li00",
        "Li2/Na2",
        "NaA/LiB",
        "Na/Li",
    )
    assert tuple(site.components for site in mixed) == (
        (SiteComponent("Na", 0.669), SiteComponent("Li", 0.331)),
        (SiteComponent("Na", 0.669), SiteComponent("Li", 0.331)),
        (SiteComponent("Na", 0.669), SiteComponent("Li", 0.331)),
        (SiteComponent("Li", 0.960), SiteComponent("Na", 0.040)),
        (SiteComponent("Na", 0.250), SiteComponent("Li", 0.750)),
        (SiteComponent("Na", 0.500), SiteComponent("Li", 0.500)),
    )
    assert all(np.isclose(site.reported_occupancy, 1.0) for site in mixed)
    assert "occupancy" not in mixed[0].reported
    assert mixed[0].reported["component_occupancy:Na06"].raw == "0.669"
    assert mixed[0].reported["component_occupancy:Li06"].raw == "0.331"

    atomic_sites = build_atomic_sites_table(structure)
    merged_row = next(row for row in atomic_sites.rows if row.id == "atom:Na06/Li06")
    assert merged_row.cells["occupancy"].provenance is Provenance.CALCULATED
    assert merged_row.cells["occupancy"].method_id == "site-component-occupancy-sum"

    # Exact complementary occupancies at one coordinate are one physical site
    # even when a database has assigned unrelated label suffixes.
    relabelled = tuple(
        site for site in structure.sites if np.allclose(site.fractional, (0.7, 0.5, 0.5))
    )
    assert tuple(site.label for site in relabelled) == ("NaA/LiB",)

    # The coordinates and complementary occupancies also disambiguate bare labels.
    bare = tuple(
        site for site in structure.sites if np.allclose(site.fractional, (0.8, 0.5, 0.5))
    )
    assert tuple(site.label for site in bare) == ("Na/Li",)

    # Conflicting disorder assemblies keep otherwise matching identities separate.
    disorder_distinct = tuple(
        site for site in structure.sites if np.allclose(site.fractional, (0.9, 0.5, 0.5))
    )
    assert tuple(site.label for site in disorder_distinct) == ("NaD", "LiD")

    polyhedron = CoordinationPolyhedron(
        id="P1",
        center_index=0,
        center_element="Mo",
        ligand_element="O",
        ligands=(),
        bond_lengths=(),
        vertex_coordinates=(),
        distortion=0.0,
        angle_dispersion=0.0,
    )
    graph = build_motif_graph(
        StructureDocument.from_structure(
            structure,
            HierarchyReport(polyhedra=[polyhedron]),
        )
    )
    for fractional in (
        (0.6, 0.5, 0.5),
        (0.5, 0.6, 0.5),
        (0.5, 0.5, 0.6),
        (0.6, 0.6, 0.5),
    ):
        nodes = tuple(
            node
            for node in graph.nodes.values()
            if node.kind == "interstitial"
            and node.site_index is not None
            and np.allclose(structure.sites[node.site_index].fractional, fractional)
        )
        assert len(nodes) == 1


def test_partially_occupied_site_exposes_vacancy_fraction() -> None:
    site = AtomSite(
        "M1",
        "Al/Si",
        (0.0, 0.0, 0.0),
        occupancy=0.85,
        components=(SiteComponent("Al", 0.55), SiteComponent("Si", 0.30)),
    )

    assert np.isclose(site.vacancy_fraction, 0.15)


def test_overoccupied_site_preserves_reported_and_clamps_effective() -> None:
    site = AtomSite("O00M", "O", (0.0, 0.0, 0.0), occupancy=1.024)

    assert np.isclose(site.reported_occupancy, 1.024)
    assert np.isclose(site.effective_occupancy, 1.0)
    assert "outside 0–1" in site.occupancy_warning


def test_normal_occupancy_has_no_warning() -> None:
    site = AtomSite("O1", "O", (0.0, 0.0, 0.0), occupancy=0.75)

    assert np.isclose(site.reported_occupancy, 0.75)
    assert np.isclose(site.effective_occupancy, 0.75)
    assert site.occupancy_warning == ""


def test_load_cif_falls_back_when_primary_reader_rejects_occupancy(
    monkeypatch,
    tmp_path,
) -> None:
    source = ROOT / "tests" / "data" / "overoccupied_minimal.cif"
    target = tmp_path / source.name
    target.write_bytes(source.read_bytes())
    before = target.read_bytes()
    monkeypatch.setattr(cif_module, "gemmi", None)

    def rejected_reader(_path):
        raise ValueError("occupancy exceeds one")

    monkeypatch.setattr(cif_module, "_load_with_pymatgen", rejected_reader)

    structure = cif_module.load_cif(target)

    assert np.isclose(structure.asymmetric_sites[0].reported_occupancy, 1.024)
    assert np.isclose(structure.asymmetric_sites[0].effective_occupancy, 1.0)
    assert target.read_bytes() == before


def test_supercell_scene_repeats_atoms() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    scene = build_scene(structure, repeat=(2, 1, 1))
    assert len(scene.atoms) == len(structure.sites) * 2
    assert scene.repeat == (2, 1, 1)
    assert len(scene.translations) == 2
    assert np.isclose(scene.cell_corners[:, 0].max(), 20.0)


def test_lithium_oxygen_coordination_is_present_in_the_atomic_scene() -> None:
    structure = CrystalStructure(
        name="LiO4 coordination",
        cell=UnitCell(10.0, 10.0, 10.0),
        asymmetric_sites=[
            AtomSite("Li1", "Li", (0.5, 0.5, 0.5)),
            AtomSite("O1", "O", (0.7, 0.5, 0.5)),
            AtomSite("O2", "O", (0.3, 0.5, 0.5)),
            AtomSite("O3", "O", (0.5, 0.7, 0.5)),
            AtomSite("O4", "O", (0.5, 0.3, 0.5)),
        ],
        sites=[
            AtomSite("Li1", "Li", (0.5, 0.5, 0.5)),
            AtomSite("O1", "O", (0.7, 0.5, 0.5)),
            AtomSite("O2", "O", (0.3, 0.5, 0.5)),
            AtomSite("O3", "O", (0.5, 0.7, 0.5)),
            AtomSite("O4", "O", (0.5, 0.3, 0.5)),
        ],
    )

    scene = build_scene(structure, complete_boundary=False)
    pairs = [
        {scene.atoms[bond.first].site.element, scene.atoms[bond.second].site.element}
        for bond in scene.bonds
    ]

    assert pairs.count({"Li", "O"}) == 4


def test_rigid_motion_decomposition() -> None:
    reference = np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), dtype=float)
    angle = np.radians(12.0)
    rotation = np.asarray(
        ((np.cos(angle), -np.sin(angle), 0), (np.sin(angle), np.cos(angle), 0), (0, 0, 1))
    )
    target = reference @ rotation.T + np.asarray((0.02, -0.01, 0.0))
    motion = compare_block_coordinates(reference, target)
    assert np.isclose(motion.rotation_degrees, 12.0)
    assert np.isclose(motion.translation, np.sqrt(0.02**2 + 0.01**2))
    assert motion.distortion_percent < 1e-10


def test_structure_series_reports_rigid_block_motion() -> None:
    reference = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    angle = np.radians(3.0)
    rotation = np.asarray(
        ((np.cos(angle), -np.sin(angle), 0), (np.sin(angle), np.cos(angle), 0), (0, 0, 1))
    )
    translation = np.asarray((0.04, -0.02, 0.01))
    moved_sites = []
    for site, cartesian in zip(reference.sites, reference.cartesian_positions, strict=True):
        moved_cartesian = cartesian @ rotation.T + translation
        fractional = tuple(moved_cartesian / np.asarray((10.0, 10.0, 10.0)))
        moved_sites.append(
            AtomSite(site.label, site.element, fractional, site.occupancy, site.u_iso)
        )
    moved = CrystalStructure(
        name="700 K",
        cell=reference.cell,
        asymmetric_sites=moved_sites,
        sites=moved_sites,
        formula=reference.formula,
        space_group=reference.space_group,
    )
    hierarchy = HierarchyAnalyzer().analyze(reference)
    report = analyze_structure_series([reference, moved], hierarchy, ["300 K", "700 K"])
    assert len(report.blocks) == 1
    assert all(np.isclose(block.motion.rotation_degrees, 3.0) for block in report.blocks)
    assert all(block.motion.distortion_percent < 1e-10 for block in report.blocks)
    assert all(block.rigidity_confidence > 0.999 for block in report.blocks)


def test_pymatgen_fallback_keeps_cif_asymmetric_sites_separate_from_expansion(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "inversion.cif"
    path.write_text(
        """data_test
_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P -1'
loop_
_space_group_symop_operation_xyz
x,y,z
-x,-y,-z
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0.123 0.234 0.345 1
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(cif_module, "gemmi", None)

    structure = load_cif(path)

    assert [site.label for site in structure.asymmetric_sites] == ["Si1"]
    assert [site.label for site in structure.sites] == ["Si1", "Si1·2"]


def test_lowercase_site_labels_without_type_symbols_resolve_real_elements(
    tmp_path,
) -> None:
    path = tmp_path / "lowercase-labels.cif"
    path.write_text(
        """data_test
_cell_length_a 8
_cell_length_b 8
_cell_length_c 8
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
ca 0.0 0.0 0.0
al 0.1 0.1 0.1
si 0.2 0.2 0.2
o  0.3 0.3 0.3
cl1 0.4 0.4 0.4
""",
        encoding="utf-8",
    )

    structure = load_cif(path)

    assert [site.element for site in structure.asymmetric_sites] == [
        "Ca",
        "Al",
        "Si",
        "O",
        "Cl",
    ]
    assert [site.label for site in structure.asymmetric_sites] == [
        "Ca1",
        "Al1",
        "Si1",
        "O1",
        "Cl1",
    ]


def test_cif_preserves_disorder_identity_through_symmetry_expansion(tmp_path) -> None:
    path = tmp_path / "disorder.cif"
    path.write_text(
        """data_disorder
_cell_length_a 10
_cell_length_b 10
_cell_length_c 10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_space_group_symop_operation_xyz
x,y,z
-x,-y,-z
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_disorder_assembly
_atom_site_disorder_group
O2A O 0.21 0.31 0.41 0.6 A 1
O2B O 0.22 0.32 0.42 0.4 A 2
""",
        encoding="utf-8",
    )

    structure = load_cif(path)

    assert [
        (site.label, site.assembly, site.disorder_group, site.source_site_key)
        for site in structure.asymmetric_sites
    ] == [
        ("O2A", "A", "1", "O2A"),
        ("O2B", "A", "2", "O2B"),
    ]
    assert {
        (site.assembly, site.disorder_group, site.source_site_key)
        for site in structure.sites
    } == {
        ("A", "1", "O2A"),
        ("A", "2", "O2B"),
    }


def test_labels_are_canonical_for_mixed_and_repeated_positions(tmp_path) -> None:
    path = tmp_path / "mixed-labels.cif"
    path.write_text(
        """data_test
_cell_length_a 8
_cell_length_b 8
_cell_length_c 8
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_occupancy
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
na06 Na 0.6 0.0 0.0 0.0
li06 Li 0.4 0.0 0.0 0.0
fe2A Fe 1.0 0.2 0.2 0.2
o O 1.0 0.3 0.3 0.3
o O 1.0 0.4 0.4 0.4
""",
        encoding="utf-8",
    )

    structure = load_cif(path, expand_symmetry=False)

    assert [site.label for site in structure.asymmetric_sites] == [
        "Na06/Li06",
        "Fe2A",
        "O1",
        "O2",
    ]
