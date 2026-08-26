from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyReport,
    PeriodicSiteRef,
    StructuralBlock,
    StructuralUnit,
)
from crystal_viewer.analysis.inorganic_topology import (
    CationTopologyEdge,
    InorganicTopologyReport,
    TopologyComponent,
    TopologyFamily,
)
from crystal_viewer.analysis.organic.pipeline import iter_analyze_organic
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui.sites_panel import SitesPanel


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _document() -> StructureDocument:
    asymmetric = (
        AtomSite("B1", "B", (0.1, 0.2, 0.3)),
        AtomSite("O1", "O", (0.2, 0.2, 0.3)),
    )
    sites = (
        asymmetric[0],
        AtomSite("B1·2", "B", (0.9, 0.8, 0.7)),
        asymmetric[1],
        AtomSite("O1·2", "O", (0.8, 0.8, 0.7)),
    )
    polyhedra = tuple(
        CoordinationPolyhedron(
            id=identifier,
            center_index=center,
            center_element="B",
            ligand_element="O",
            ligands=(PeriodicSiteRef(2), PeriodicSiteRef(3)),
            bond_lengths=(1.4, 1.4),
            vertex_coordinates=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            distortion=0.0,
            angle_dispersion=0.0,
        )
        for identifier, center in (("P1", 0), ("P2", 1))
    )
    structure = CrystalStructure("test", UnitCell(5, 5, 5), list(asymmetric), list(sites))
    hierarchy = HierarchyReport(
        polyhedra=list(polyhedra),
        structural_units=[StructuralUnit("SU1", ("P1", "P2"), (0, 1, 2, 3), "ring")],
        blocks=[StructuralBlock("B1", ("P1", "P2"), (0, 1, 2, 3), "rigid", 0.8, 1.0)],
    )
    return StructureDocument.from_structure(structure, hierarchy)


def _symmetry_document() -> StructureDocument:
    asymmetric = (
        AtomSite("B1", "B", (0.1, 0.2, 0.3)),
        AtomSite("O1", "O", (0.2, 0.2, 0.3)),
    )
    sites = (
        asymmetric[0],
        AtomSite("B1·2", "B", (0.9, 0.8, 0.7)),
        asymmetric[1],
        AtomSite("O1·2", "O", (0.8, 0.8, 0.7)),
    )
    polyhedra = [
        CoordinationPolyhedron(
            f"P{number}",
            center,
            "B",
            "O",
            (PeriodicSiteRef(ligand),),
            (1.4,),
            ((0.0, 0.0, 0.0),),
            0.0,
            0.0,
        )
        for number, center, ligand in ((1, 0, 2), (2, 1, 3))
    ]
    structure = CrystalStructure(
        "symmetry",
        UnitCell(5, 5, 5),
        list(asymmetric),
        list(sites),
        symmetry_operations=["x,y,z", "-x,-y,-z"],
    )
    hierarchy = HierarchyReport(
        polyhedra=polyhedra,
        structural_units=[
            StructuralUnit("SU1", ("P1",), (0, 2), "island"),
            StructuralUnit("SU2", ("P2",), (1, 3), "island"),
        ],
        blocks=[
            StructuralBlock("RB1", ("P1",), (0, 2), "rigid", 0.8, 1.0),
            StructuralBlock("RB2", ("P2",), (1, 3), "rigid", 0.8, 1.0),
        ],
    )
    return StructureDocument.from_structure(structure, hierarchy)


def test_sites_panel_lists_only_asymmetric_sites_and_polyhedron_families() -> None:
    _application()
    panel = SitesPanel()
    panel.set_document(_document())

    assert panel.atom_table.rowCount() == 2
    assert [panel.atom_table.item(row, 0).text() for row in range(2)] == ["B1", "O1"]
    assert panel.polyhedron_table.rowCount() == 1
    assert panel.polyhedron_table.item(0, 0).text() == "B1O₂"

    panel.set_category("atoms")
    assert panel.current_table() is panel.atom_table
    panel.set_category("polyhedra")
    assert panel.current_table() is panel.polyhedron_table


def test_sites_panel_has_one_dynamic_table_for_every_drawable_hierarchy_class() -> None:
    _application()
    panel = SitesPanel()
    panel.set_document(_document())

    for category, expected_rows in (
        ("atoms", 2),
        ("bonds", 1),
        ("polyhedra", 1),
        ("units", 1),
        ("blocks", 1),
    ):
        panel.set_category(category)
        assert panel.current_table().rowCount() == expected_rows


def test_organic_categories_reuse_one_context_table_below_the_tree() -> None:
    _application()
    sites = [
        AtomSite("C1", "C", (0.10, 0.50, 0.50)),
        AtomSite("C2", "C", (0.24, 0.50, 0.50)),
        AtomSite("O1", "O", (0.38, 0.50, 0.50)),
    ]
    structure = CrystalStructure("organic", UnitCell(10, 10, 10), sites, sites)
    document = StructureDocument.from_preview(structure)
    for bundle in iter_analyze_organic(structure):
        document.install_organic_bundle(bundle)
    panel = SitesPanel()
    panel.set_document(document)

    expected = {
        "covalent_bonds": len(document.organic_analysis.bonds.covalent),
        "coordination_bonds": len(document.organic_analysis.bonds.coordination),
        "molecules": len(document.organic_analysis.components.components),
        "rings": len(document.organic_analysis.components.rings),
        "contacts": len(document.organic_analysis.contacts.contacts),
        "packing": len(document.organic_analysis.packing.assemblies),
        "voids": len(document.organic_analysis.packing.voids),
    }
    tables = []
    for category, row_count in expected.items():
        panel.set_category(category)
        tables.append(panel.current_table())
        assert panel.current_table().rowCount() == row_count

    assert len({id(table) for table in tables}) == 1


def test_sites_panel_controls_whole_symmetry_orbits() -> None:
    _application()
    document = _document()
    panel = SitesPanel()
    panel.set_document(document)

    panel.atom_table.item(0, 2).setCheckState(Qt.CheckState.Unchecked)
    panel.set_category("bonds")
    panel.bond_table.item(0, 2).setCheckState(Qt.CheckState.Unchecked)
    panel.polyhedron_table.item(0, 2).setCheckState(Qt.CheckState.Unchecked)

    assert document.visual.hidden_atom_indices == {0, 1}
    assert document.visual.hidden_bond_families == {("B", "O")}
    assert document.visual.hidden_polyhedron_ids == {"P1", "P2"}


def test_scene_pick_selects_matching_context_table_row() -> None:
    _application()
    document = _document()
    panel = SitesPanel()
    panel.set_document(document)

    assert panel.select_object("atom", 1)
    assert panel.current_table() is panel.atom_table
    assert panel.atom_table.currentRow() == 0

    assert panel.select_object("bond", ("B", "O"))
    assert panel.current_table() is panel.bond_table
    assert panel.bond_table.currentRow() == 0

    assert panel.select_object("polyhedron", "P2")
    assert panel.current_table() is panel.polyhedron_table
    assert panel.polyhedron_table.currentRow() == 0

    assert panel.select_object("unit", "SU1")
    assert panel.current_table() is panel.unit_table
    assert panel.unit_table.currentRow() == 0

    assert panel.select_object("block", "B1")
    assert panel.current_table() is panel.block_table
    assert panel.block_table.currentRow() == 0


def test_units_and_blocks_can_be_enabled_simultaneously_in_the_mixed_scene() -> None:
    _application()
    document = _document()
    panel = SitesPanel()
    panel.set_document(document)

    panel.unit_table.item(0, 2).setCheckState(Qt.CheckState.Checked)
    panel.block_table.item(0, 2).setCheckState(Qt.CheckState.Checked)

    assert document.visual.shown_unit_ids == {"SU1"}
    assert document.visual.shown_block_ids == {"B1"}


def test_units_and_blocks_tables_group_symmetry_equivalent_positions() -> None:
    _application()
    document = _symmetry_document()
    panel = SitesPanel()
    panel.set_document(document)

    assert panel.unit_table.rowCount() == 1
    assert panel.block_table.rowCount() == 1
    assert panel.unit_table.item(0, 0).text() == "island · B1"
    assert panel.block_table.item(0, 0).text() == "rigid · B1"

    panel.unit_table.item(0, 2).setCheckState(Qt.CheckState.Checked)
    panel.block_table.item(0, 2).setCheckState(Qt.CheckState.Checked)
    panel.set_unit_color(("SU1", "SU2"), "#112233")
    panel.set_block_color(("RB1", "RB2"), "#445566")

    assert document.visual.shown_unit_ids == {"SU1", "SU2"}
    assert document.visual.shown_block_ids == {"RB1", "RB2"}
    assert document.visual.unit_colors == {"SU1": "#112233", "SU2": "#112233"}
    assert document.visual.block_colors == {"RB1": "#445566", "RB2": "#445566"}


def test_invalid_symmetry_operation_does_not_break_hierarchy_tables() -> None:
    _application()
    document = _symmetry_document()
    document.structure.symmetry_operations = ["x,y,z", "not-an-operation"]
    panel = SitesPanel()

    panel.set_document(document)

    assert panel.unit_table.rowCount() == 2
    assert panel.block_table.rowCount() == 2


def test_sites_panel_stores_atom_and_polyhedron_colours_by_orbit() -> None:
    _application()
    document = _document()
    panel = SitesPanel()
    panel.set_document(document)

    panel.set_atom_color("B1", "#112233")
    panel.set_polyhedron_color("B1", "#445566")

    assert document.visual.atom_orbit_colors == {"B1": "#112233"}
    assert document.visual.polyhedron_orbit_colors == {"B1": "#445566"}


def test_sites_panel_disables_colour_cells_ignored_by_the_active_colour_mode() -> None:
    _application()
    panel = SitesPanel()
    panel.set_document(_document())

    panel.set_color_mode("automatic")
    assert panel.polyhedron_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert not panel.block_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled

    panel.set_color_mode("rigidity")
    assert not panel.polyhedron_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert not panel.block_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled

    panel.set_color_mode("block")
    assert not panel.polyhedron_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert panel.block_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled

    panel.set_color_mode("element")
    assert panel.polyhedron_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert panel.block_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled

    panel.set_comparison_locked(True)
    assert not panel.atom_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert not panel.polyhedron_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert not panel.unit_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert not panel.block_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled

    panel.set_comparison_locked(False)
    assert panel.atom_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled
    assert panel.polyhedron_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEnabled


def test_topology_category_lists_network_families_and_controls_visibility() -> None:
    _application()
    document = _document()
    component = TopologyComponent(
        "TC1", ("P1", "P2"), 1, "chain", ((2, 0, 0),),
        ((1, 0, 0),), None, (("corner", 2),),
    )
    document.inorganic_topology = InorganicTopologyReport(
        (component,),
        (
            TopologyFamily(
                "TF1", ("TC1",), "chain", 1, ((1, 0, 0),), None,
                ("BO2",), (("corner", 2),),
            ),
        ),
        frozenset({"P1", "P2"}),
        (),
        True,
    )
    panel = SitesPanel()
    panel.set_document(document)
    panel.set_category("topology")

    table = panel.current_table()
    assert tuple(
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    ) == ("Network", "Type", "Direction / plane", "Connections", "Visible")
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "BO2"
    assert table.item(0, 1).text() == "chain"
    assert table.item(0, 2).text() == "[1 0 0]"
    assert table.item(0, 3).text() == "corner: 2"

    table.item(0, 4).setCheckState(Qt.CheckState.Unchecked)

    assert document.visual.hidden_topology_family_ids == {"TF1"}


def test_topology_category_lists_cation_network_with_distance_and_edge_modes() -> None:
    _application()
    document = _document()
    component = TopologyComponent(
        "CC1", ("P1", "P2"), 1, "chain", ((1, 0, 0),),
        ((1, 0, 0),), None, (("shared-ligand", 1), ("geometric", 1)),
    )
    document.inorganic_topology = InorganicTopologyReport(
        (), (), frozenset(), (), True,
        cation_components=(component,),
        cation_families=(
            TopologyFamily(
                "CF1", ("CC1",), "chain", 1, ((1, 0, 0),), None,
                ("YO6",), (("shared-ligand", 1), ("geometric", 1)),
                representation="cation", distance_range=(3.0, 4.25),
            ),
        ),
        cation_edges=(
            CationTopologyEdge("P1", "P2", (0, 0, 0), "shared-ligand", 3.0, (2,)),
        ),
        cation_polyhedron_ids=frozenset({"P1", "P2"}),
    )
    panel = SitesPanel()
    panel.set_document(document)
    panel.set_category("topology")

    table = panel.current_table()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "YO6 · cation network"
    assert table.item(0, 3).text() == (
        "shared-ligand: 1 · geometric: 1 · d: 3.00–4.25 Å"
    )


def test_unavailable_topology_uses_selectable_warning_text() -> None:
    _application()
    document = _document()
    document.inorganic_topology = InorganicTopologyReport(
        (), (), frozenset(), ("Structural network could not be evaluated.",), False
    )
    panel = SitesPanel()

    panel.set_document(document)
    panel.set_category("topology")

    assert panel.topology_status.isVisibleTo(panel)
    assert panel.topology_status.text() == "Structural network could not be evaluated."
    assert panel.topology_status.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
