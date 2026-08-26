from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    FlexibleConnector,
    HierarchyReport,
    PeriodicSiteRef,
    StructuralBlock,
    StructuralUnit,
)
from crystal_viewer.analysis.inorganic_topology import (
    InorganicTopologyReport,
    TopologyComponent,
    TopologyFamily,
)
from crystal_viewer.analysis.organic.pipeline import iter_analyze_organic
from crystal_viewer.analysis.structural_domains import StructuralDomain
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui.hierarchy_tree import HierarchyTree
from crystal_viewer.knowledge.model import InterpretationChanges
from crystal_viewer.knowledge.resolve import set_manual_changes


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _document(name: str) -> StructureDocument:
    sites = [
        AtomSite("Si1", "Si", (0.5, 0.5, 0.5)),
        AtomSite("O1", "O", (0.6, 0.5, 0.5)),
        AtomSite("O2", "O", (0.4, 0.5, 0.5)),
    ]
    polyhedra = [
        CoordinationPolyhedron(
            id=identifier,
            center_index=0,
            center_element="Si",
            ligand_element="O",
            ligands=(PeriodicSiteRef(1), PeriodicSiteRef(2)),
            bond_lengths=(1.6, 1.6),
            vertex_coordinates=((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)),
            distortion=0.0,
            angle_dispersion=0.0,
        )
        for identifier in ("P1", "P2")
    ]
    structure = CrystalStructure(name, UnitCell(5.0, 5.0, 5.0), sites, sites)
    return StructureDocument.from_structure(structure, HierarchyReport(polyhedra=polyhedra))


def _collection() -> StructureCollection:
    collection = StructureCollection()
    collection.add(_document("first"))
    collection.add(_document("second"))
    return collection


def _symmetry_repeated_document() -> StructureDocument:
    asymmetric = [
        AtomSite("B1", "B", (0.1, 0.2, 0.3)),
        AtomSite("O1", "O", (0.2, 0.2, 0.3)),
    ]
    sites = [
        asymmetric[0],
        AtomSite("B1·2", "B", (0.9, 0.8, 0.7)),
        asymmetric[1],
        AtomSite("O1·2", "O", (0.8, 0.8, 0.7)),
    ]
    polyhedra = [
        CoordinationPolyhedron(
            f"P{number}", center, "B", "O", (PeriodicSiteRef(ligand),),
            (1.4,), ((0.0, 0.0, 0.0),), 0.0, 0.0,
        )
        for number, center, ligand in ((1, 0, 2), (2, 1, 3))
    ]
    structure = CrystalStructure(
        "symmetry", UnitCell(5, 5, 5), asymmetric, sites,
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
        connectors=[
            FlexibleConnector("C1", "RB1", "RB2", "P1", "P2", "corner", (2,), ()),
            FlexibleConnector("C2", "RB2", "RB1", "P2", "P1", "corner", (3,), ()),
        ],
    )
    return StructureDocument.from_structure(structure, hierarchy)


def _find_child(parent, prefix: str):
    for index in range(parent.childCount()):
        child = parent.child(index)
        if child.text(0).startswith(prefix):
            return child
    raise AssertionError(prefix)


def test_tree_has_one_column_with_compare_checks_on_structure_roots() -> None:
    _application()
    collection = _collection()
    tree = HierarchyTree()

    tree.set_collection(collection)

    assert tree.topLevelItemCount() == 2
    assert tree.columnCount() == 1
    assert tree.topLevelItem(0).text(0) == ""
    assert tree.root_label(0).text() == "first"
    assert not tree.topLevelItem(0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert not tree.root_checkbox(0).isChecked()


def test_tree_is_fully_collapsed_after_loading_collection() -> None:
    _application()
    tree = HierarchyTree()
    tree.set_collection(_collection())

    assert all(
        not tree.topLevelItem(index).isExpanded()
        for index in range(tree.topLevelItemCount())
    )


def test_tree_contains_object_classes_without_expanded_object_leaves() -> None:
    _application()
    tree = HierarchyTree()
    tree.set_collection(_collection())
    root = tree.topLevelItem(0)

    labels = [root.child(index).text(0) for index in range(root.childCount())]
    assert any(label.startswith("Atoms (") for label in labels)
    assert _find_child(root, "Bonds (").text(0) == "Bonds (1)"
    assert any(label.startswith("Polyhedra (") for label in labels)
    assert _find_child(root, "Atoms (").childCount() == 0
    assert _find_child(root, "Bonds (").childCount() == 0
    assert _find_child(root, "Polyhedra (").childCount() == 0


def test_preview_tree_marks_dependent_categories_as_calculating() -> None:
    _application()
    structure = _document("preview").structure
    collection = StructureCollection()
    collection.add(StructureDocument.from_preview(structure))
    tree = HierarchyTree()

    tree.set_collection(collection)

    root = tree.topLevelItem(0)
    assert _find_child(root, "Atoms (").flags() & Qt.ItemFlag.ItemIsEnabled
    for prefix in ("Bonds", "Polyhedra", "Structural Units", "Rigid Blocks", "Topology"):
        item = _find_child(root, prefix)
        assert item.text(0).endswith("— calculating…")
        assert not item.flags() & Qt.ItemFlag.ItemIsEnabled


def test_organic_tree_replaces_inorganic_categories_with_profile_results() -> None:
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
    collection = StructureCollection()
    collection.add(document)
    tree = HierarchyTree()

    tree.set_collection(collection)

    root = tree.topLevelItem(0)
    labels = [root.child(index).text(0) for index in range(root.childCount())]
    assert any(label.startswith("Covalent Bonds (") for label in labels)
    assert any(label.startswith("Coordination Bonds (") for label in labels)
    assert any(label.startswith("Molecules (") for label in labels)
    assert any(label.startswith("Rings (") for label in labels)
    assert any(label.startswith("Contacts (") for label in labels)
    assert any(label.startswith("Packing Assemblies (") for label in labels)
    assert any(label.startswith("Geometric Voids (") for label in labels)
    assert not any(label.startswith("Polyhedra") for label in labels)
    assert not any(label.startswith("Rigid Blocks") for label in labels)


def test_tree_reports_the_number_of_canonical_topology_families() -> None:
    _application()
    document = _document("network")
    component = TopologyComponent(
        "TC1", ("P1", "P2"), 1, "chain", ((1, 0, 0),),
        ((1, 0, 0),), None, (("corner", 1),),
    )
    document.inorganic_topology = InorganicTopologyReport(
        (component,),
        (
            TopologyFamily(
                "TF1", ("TC1",), "chain", 1, ((1, 0, 0),), None,
                ("SiO₂",), (("corner", 1),),
            ),
        ),
        frozenset({"P1", "P2"}),
        (),
        True,
    )
    collection = StructureCollection()
    collection.add(document)
    tree = HierarchyTree()

    tree.set_collection(collection)

    assert _find_child(tree.topLevelItem(0), "Topology").text(0) == "Topology (1)"


def test_tree_counts_independent_symmetry_rows_instead_of_expanded_copies() -> None:
    _application()
    collection = StructureCollection()
    collection.add(_symmetry_repeated_document())
    tree = HierarchyTree()

    tree.set_collection(collection)

    root = tree.topLevelItem(0)
    assert _find_child(root, "Polyhedra (").text(0) == "Polyhedra (1)"
    assert _find_child(root, "Structural Units (").text(0) == "Structural Units (1)"
    assert _find_child(root, "Rigid Blocks (").text(0) == "Rigid Blocks (1)"
    assert _find_child(root, "Shared sites").text(0).endswith("(1)")


def test_root_check_emits_compare_selection() -> None:
    _application()
    collection = _collection()
    tree = HierarchyTree()
    tree.set_collection(collection)
    requested: list[tuple[str, bool]] = []
    tree.compare_toggled.connect(lambda document_id, enabled: requested.append((document_id, enabled)))

    tree.root_checkbox(0).setChecked(True)

    assert requested[-1] == (collection.order[0], True)
    assert tree.root_checkbox(0).text() == "✓"


def test_compare_column_accepts_only_two_checked_structures() -> None:
    _application()
    collection = _collection()
    collection.add(_document("third"))
    tree = HierarchyTree()
    tree.set_collection(collection)

    for index in range(3):
        tree.root_checkbox(index).setChecked(True)

    assert tree.root_checkbox(0).isChecked()
    assert tree.root_checkbox(1).isChecked()
    assert not tree.root_checkbox(2).isChecked()


def test_tree_keeps_interpretations_as_one_dynamic_table_category():
    _application()
    document = _document("interpreted")
    document.hierarchy.structural_domains = [
        StructuralDomain("D1", ("P1", "P2"), (0, 1, 2), 0, "dimer", 0.9)
    ]
    set_manual_changes(
        document,
        "D1",
        InterpretationChanges(name="confirmed motif"),
    )
    collection = StructureCollection()
    collection.add(document)
    tree = HierarchyTree()

    tree.set_collection(collection)

    interpretation = _find_child(tree.topLevelItem(0), "Interpretation")
    assert interpretation.childCount() == 0
    assert interpretation.data(0, Qt.ItemDataRole.UserRole) == (
        document.id,
        "category",
        "interpretations",
    )
