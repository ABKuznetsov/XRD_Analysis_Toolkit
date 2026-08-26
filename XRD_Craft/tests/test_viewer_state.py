from __future__ import annotations

from types import MethodType, SimpleNamespace

import numpy as np

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyLevel,
    HierarchyReport,
    PeriodicSiteRef,
    PolyhedronConnection,
)
from crystal_viewer.analysis.inorganic_topology import (
    CationTopologyEdge,
    InorganicTopologyReport,
    TopologyComponent,
    TopologyFamily,
)
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, SiteComponent, UnitCell
from crystal_viewer.ui.comparison_highlight import (
    MATCH_PALETTE,
    MUTED_COLOR,
    OUTLINE_RED,
    SUBSTITUTION_YELLOW,
    ComparisonHighlight,
)
from crystal_viewer.ui import viewer as viewer_module
from crystal_viewer.ui.viewer import (
    ELEMENT_COLORS,
    VACANCY_COLOR,
    StructureViewer,
    picked_polyhedron_id,
    picked_scene_object,
    rotate_camera_about_axis,
)


def test_picked_polyhedron_id_resolves_only_tagged_polyhedron_cells() -> None:
    picked = SimpleNamespace(
        cell_data={
            "pick_kind": np.asarray([1, 1]),
            "source_index": np.asarray([1, 1]),
        }
    )
    hierarchy = SimpleNamespace(
        polyhedra=(SimpleNamespace(id="P1"), SimpleNamespace(id="P2"))
    )

    assert picked_polyhedron_id(picked, hierarchy) == "P2"
    picked.cell_data["pick_kind"] = np.asarray([0, 0])
    assert picked_polyhedron_id(picked, hierarchy) is None


def test_polyhedron_cell_pick_selects_and_emits_the_polyhedron() -> None:
    emitted: list[str] = []
    redrawn: list[bool] = []
    viewer = SimpleNamespace(
        hierarchy=SimpleNamespace(polyhedra=(SimpleNamespace(id="P1"),)),
        selected_polyhedron_id=None,
        object_picked=SimpleNamespace(emit=emitted.append),
        redraw=lambda reset_camera: redrawn.append(reset_camera),
    )
    picked = SimpleNamespace(
        cell_data={"pick_kind": np.asarray([1]), "source_index": np.asarray([0])}
    )

    StructureViewer._polyhedron_cells_picked(viewer, picked)

    assert viewer.selected_polyhedron_id == "P1"
    assert emitted == ["P1"]
    assert redrawn == [False]


def test_typed_pick_resolves_atoms_bonds_polyhedra_units_and_blocks() -> None:
    picked_atom = SimpleNamespace(
        cell_data={"pick_kind": np.asarray([2]), "source_index": np.asarray([0])}
    )
    picked_bond = SimpleNamespace(
        cell_data={"pick_kind": np.asarray([3]), "source_index": np.asarray([0])}
    )
    picked_polyhedron = SimpleNamespace(
        cell_data={"pick_kind": np.asarray([1]), "source_index": np.asarray([1])}
    )
    scene = SimpleNamespace(
        atoms=(
            SimpleNamespace(site_index=7, site=AtomSite("B1", "B", (0, 0, 0))),
            SimpleNamespace(site_index=9, site=AtomSite("O1", "O", (0, 0, 0))),
        ),
        bonds=(SimpleNamespace(first=0, second=1),),
    )
    hierarchy = SimpleNamespace(
        polyhedra=(SimpleNamespace(id="P1"), SimpleNamespace(id="P2")),
        structural_units=(SimpleNamespace(id="SU1", polyhedron_ids=("P2",)),),
        blocks=(SimpleNamespace(id="RB1", polyhedron_ids=("P2",)),),
    )

    assert picked_scene_object(picked_atom, hierarchy, scene, "atom") == ("atom", 7)
    assert picked_scene_object(picked_bond, hierarchy, scene, "bond") == (
        "bond",
        ("B", "O"),
    )
    assert picked_scene_object(picked_polyhedron, hierarchy, scene, "polyhedron") == (
        "polyhedron",
        "P2",
    )
    assert picked_scene_object(picked_polyhedron, hierarchy, scene, "unit") == (
        "unit",
        "SU1",
    )
    assert picked_scene_object(picked_polyhedron, hierarchy, scene, "block") == (
        "block",
        "RB1",
    )


def test_axis_rotation_uses_crystallographic_world_axis() -> None:
    position, view_up = rotate_camera_about_axis(
        position=(1.0, 0.0, 0.0),
        focal_point=(0.0, 0.0, 0.0),
        view_up=(0.0, 0.0, 1.0),
        axis=(0.0, 0.0, 2.0),
        angle_degrees=90.0,
    )

    assert np.allclose(position, (0.0, 1.0, 0.0), atol=1e-7)
    assert np.allclose(view_up, (0.0, 0.0, 1.0), atol=1e-7)


def test_edit_mode_and_temporary_target_have_explicit_state_transitions() -> None:
    cleared: list[bool] = []
    viewer = SimpleNamespace(
        edit_mode=False,
        edit_target_kind=None,
        selected_scene_object=("atom", 2),
        selected_polyhedron_id="P1",
        redraw=lambda reset_camera: None,
        scene_selection_cleared=SimpleNamespace(emit=lambda: cleared.append(True)),
    )

    StructureViewer.set_edit_mode(viewer, True)
    StructureViewer.set_edit_target(viewer, "unit")
    assert viewer.edit_mode is True
    assert viewer.edit_target_kind == "unit"

    StructureViewer.set_edit_target(viewer, None)
    StructureViewer.clear_scene_selection(viewer)
    assert viewer.edit_target_kind is None
    assert viewer.selected_scene_object is None
    assert viewer.selected_polyhedron_id is None
    assert cleared == [True]


def test_scene_picking_uses_immediate_left_click_element_picker() -> None:
    calls: list[dict[str, object]] = []
    plotter = SimpleNamespace(
        disable_picking=lambda: None,
        enable_element_picking=lambda **kwargs: calls.append(kwargs),
    )
    viewer = SimpleNamespace(plotter=plotter, _scene_cells_picked=lambda _picked: None)

    StructureViewer._enable_polyhedron_picking(viewer)

    assert len(calls) == 1
    assert calls[0]["mode"] == "cell"
    assert calls[0]["left_clicking"] is True
    assert calls[0]["show"] is False


def test_isolate_bond_keeps_only_the_selected_element_family() -> None:
    sites = (
        AtomSite("B1", "B", (0, 0, 0)),
        AtomSite("O1", "O", (0, 0, 0)),
        AtomSite("Li1", "Li", (0, 0, 0)),
    )
    scene = SimpleNamespace(
        atoms=tuple(SimpleNamespace(site=site) for site in sites),
        bonds=(SimpleNamespace(first=0, second=1),),
    )
    viewer = SimpleNamespace(
        structure=SimpleNamespace(sites=sites),
        scene=scene,
        hierarchy=HierarchyReport(),
        redraw=lambda reset_camera: None,
        hidden_atom_indices=set(),
        hidden_bond_orbits=set(),
        hidden_bond_families=set(),
        hidden_polyhedron_ids=set(),
        hidden_unit_ids=set(),
        hidden_block_ids=set(),
        hidden_connector_ids=set(),
        hidden_topology_family_ids=set(),
        shown_unit_ids=set(),
        shown_block_ids=set(),
        _document=SimpleNamespace(
            structure=SimpleNamespace(sites=sites),
            hierarchy=SimpleNamespace(
                polyhedra=(
                    SimpleNamespace(
                        center_index=0,
                        ligands=(SimpleNamespace(site_index=1),),
                    ),
                    SimpleNamespace(
                        center_index=2,
                        ligands=(SimpleNamespace(site_index=1),),
                    ),
                )
            ),
            periodic_bonds=None,
            structural_analysis=None,
        ),
    )
    viewer.reset_visibility = MethodType(StructureViewer.reset_visibility, viewer)

    StructureViewer.isolate_object(viewer, "bond", ("B", "O"))

    assert viewer.hidden_bond_families == {("Li", "O")}


def _document(name: str = "state-test") -> StructureDocument:
    sites = [AtomSite("Si1", "Si", (0.5, 0.5, 0.5))]
    structure = CrystalStructure(name, UnitCell(5.0, 6.0, 7.0), sites, sites)
    return StructureDocument.from_structure(structure, HierarchyReport())


def test_apply_visual_state_copies_hidden_sets() -> None:
    marker = ComparisonHighlight({"P1": "#123456"}, {}, set(), set())
    viewer = SimpleNamespace(comparison_highlight=marker)
    document = _document()
    document.visual.hidden_polyhedron_ids.add("P1")
    document.visual.hidden_bond_families.add(("O1", "Si1"))
    document.visual.shown_unit_ids.add("SU1")
    document.visual.shown_block_ids.add("B1")
    document.visual.hidden_topology_family_ids.add("TF1")

    StructureViewer.apply_visual_state(viewer, document.visual, redraw=False)
    document.visual.hidden_polyhedron_ids.add("P2")

    assert viewer.hidden_polyhedron_ids == {"P1"}
    assert viewer.hidden_bond_families == {("O1", "Si1")}
    assert viewer.shown_unit_ids == {"SU1"}
    assert viewer.shown_block_ids == {"B1"}
    assert viewer.hidden_topology_family_ids == {"TF1"}
    assert viewer.comparison_highlight is marker


def test_crossing_topology_boundary_resets_the_camera() -> None:
    redraws: list[bool] = []
    viewer = SimpleNamespace(
        level=HierarchyLevel.TOPOLOGY,
        redraw=lambda reset_camera: redraws.append(reset_camera),
    )

    StructureViewer.set_level(viewer, HierarchyLevel.SITES)
    StructureViewer.set_level(viewer, HierarchyLevel.POLYHEDRA)
    StructureViewer.set_level(viewer, HierarchyLevel.TOPOLOGY)

    assert redraws == [True, False, True]


def test_mixed_structure_hides_constituents_under_selected_aggregates() -> None:
    calls: list[tuple[str, object]] = []
    unit = SimpleNamespace(id="SU1", polyhedron_ids=("P1",), atom_indices=(0, 1))
    block = SimpleNamespace(id="B1", polyhedron_ids=("P2",), atom_indices=(2, 3))
    extra_polyhedron = SimpleNamespace(id="P3", center_index=0)
    viewer = SimpleNamespace(
        hierarchy=SimpleNamespace(
            structural_units=(unit,), blocks=(block,), polyhedra=(extra_polyhedron,)
        ),
        shown_unit_ids={"SU1"},
        shown_block_ids={"B1"},
        hidden_polyhedron_ids=set(),
        hidden_unit_ids=set(),
        hidden_block_ids=set(),
        show_bonds=True,
        show_polyhedra=True,
        show_atoms=True,
        _resolved_color_mode=lambda _default: "element",
        _draw_bonds=lambda *, excluded_site_indices=(): calls.append(
            ("bonds", set(excluded_site_indices))
        ),
        _draw_polyhedra=lambda **_kwargs: calls.append(
            ("polyhedra", set(viewer.hidden_polyhedron_ids))
        ),
        _draw_atoms=lambda **kwargs: calls.append(
            ("atoms", set(kwargs["excluded_site_indices"]))
        ),
        _draw_structural_units=lambda: calls.append(
            ("units", set(viewer.hidden_unit_ids))
        ),
        _draw_rigid_blocks=lambda: calls.append(
            ("blocks", set(viewer.hidden_block_ids))
        ),
    )

    StructureViewer._draw_mixed_structure(viewer)

    assert ("bonds", {0, 1, 2, 3}) in calls
    assert ("polyhedra", {"P1", "P2", "P3"}) in calls
    assert ("atoms", {0, 1, 2, 3}) in calls
    assert ("units", set()) in calls
    assert ("blocks", set()) in calls
    assert viewer.hidden_polyhedron_ids == set()
    assert viewer.hidden_unit_ids == set()
    assert viewer.hidden_block_ids == set()


def test_mixed_structure_keeps_ligand_shared_with_visible_polyhedron() -> None:
    calls: list[set[int]] = []
    boundary_calls: list[tuple[set[int], set[str]]] = []
    block = SimpleNamespace(id="B1", polyhedron_ids=("P1",), atom_indices=(0, 1, 2))
    selected = SimpleNamespace(
        id="P1", center_index=0, ligands=(PeriodicSiteRef(1), PeriodicSiteRef(2))
    )
    visible = SimpleNamespace(
        id="P2", center_index=3, ligands=(PeriodicSiteRef(1),)
    )
    viewer = SimpleNamespace(
        hierarchy=SimpleNamespace(
            structural_units=(), blocks=(block,), polyhedra=(selected, visible)
        ),
        shown_unit_ids=set(),
        shown_block_ids={"B1"},
        hidden_polyhedron_ids=set(),
        hidden_unit_ids=set(),
        hidden_block_ids=set(),
        show_bonds=False,
        show_polyhedra=False,
        show_atoms=True,
        _draw_atoms=lambda **kwargs: calls.append(set(kwargs["excluded_site_indices"])),
        _draw_polyhedron_vertices=lambda **kwargs: boundary_calls.append(
            (set(kwargs["site_indices"]), set(kwargs["polyhedron_ids"]))
        ),
    )

    StructureViewer._draw_mixed_structure(viewer)

    assert calls == [{0, 1, 2}]
    assert boundary_calls == [({1}, {"P2"})]


def test_mixed_legend_describes_only_objects_drawn_in_the_scene() -> None:
    sites = [
        AtomSite("Al1", "Al", (0.0, 0.0, 0.0)),
        AtomSite("O1", "O", (0.1, 0.0, 0.0)),
        AtomSite("Si1", "Si", (0.5, 0.5, 0.5)),
    ]
    block = SimpleNamespace(
        id="B1", classification="framework", polyhedron_ids=("P1",), atom_indices=(0, 1)
    )
    selected = SimpleNamespace(
        id="P1", center_index=0, center_element="Al", ligand_element="O",
        coordination_number=1, ligands=(PeriodicSiteRef(1),)
    )
    visible = SimpleNamespace(
        id="P2", center_index=2, center_element="Si", ligand_element="O",
        coordination_number=1, ligands=(PeriodicSiteRef(1),)
    )
    captured: list[list[tuple[str, str]]] = []
    viewer = SimpleNamespace(
        level=HierarchyLevel.SITES,
        hierarchy=SimpleNamespace(
            structural_units=(), blocks=(block,), polyhedra=(selected, visible)
        ),
        structure=CrystalStructure("legend", UnitCell(5, 5, 5), sites, sites),
        scene=SimpleNamespace(
            atoms=tuple(
                SimpleNamespace(site=site, site_index=index)
                for index, site in enumerate(sites)
            )
        ),
        shown_unit_ids=set(), shown_block_ids={"B1"},
        hidden_atom_indices=set(), hidden_polyhedron_ids=set(),
        hidden_unit_ids=set(), hidden_block_ids=set(),
        show_atoms=True, show_polyhedra=True,
        split_mixed_occupancies=False, show_vacancy_sectors=False,
        atom_orbit_colors={}, polyhedron_orbit_colors={}, block_colors={"B1": "#123456"},
        _document=None,
        plotter=SimpleNamespace(add_legend=lambda entries, **_kwargs: captured.append(entries)),
    )

    StructureViewer._draw_legend(viewer)

    labels = {label for label, _color in captured[0]}
    assert "Al" not in labels
    assert labels == {"O", "Si", "SiO₁ polyhedron", "framework · Al1"}


def test_set_document_assigns_structure_hierarchy_and_scene() -> None:
    assigned: list[tuple[object, object, object, bool]] = []
    viewer = SimpleNamespace(
        set_data=lambda structure, scene, hierarchy, reset_camera: assigned.append(
            (structure, scene, hierarchy, reset_camera)
        ),
        apply_visual_state=lambda _state, redraw: None,
    )
    document = _document()

    StructureViewer.set_document(viewer, document, reset_camera=False)

    structure, scene, hierarchy, reset_camera = assigned[-1]
    assert structure is document.structure
    assert hierarchy is document.hierarchy
    assert scene is not None
    assert reset_camera is False


def test_set_data_clears_stale_highlight_on_structure_change_in_single_redraw() -> None:
    first = _document("first")
    second = _document("second")
    marker = ComparisonHighlight({"P1": "#123456"}, {0: "#654321"}, set(), set())
    redraws: list[bool] = []
    viewer = SimpleNamespace(
        structure=first.structure,
        hierarchy=first.hierarchy,
        comparison_highlight=marker,
        _polyhedron_surface_cache={"P1": object()},
        reset_visibility=lambda redraw: None,
        redraw=lambda reset_camera: redraws.append(reset_camera),
    )

    StructureViewer.set_data(
        viewer,
        second.structure,
        object(),
        second.hierarchy,
        reset_camera=False,
    )

    assert viewer.comparison_highlight is None
    assert redraws == [False]


def test_set_data_retains_highlight_for_same_structure_redraw() -> None:
    document = _document()
    marker = ComparisonHighlight({"P1": "#123456"}, {}, set(), set())
    viewer = SimpleNamespace(
        structure=document.structure,
        hierarchy=document.hierarchy,
        comparison_highlight=marker,
        _polyhedron_surface_cache={},
        reset_visibility=lambda redraw: None,
        redraw=lambda reset_camera: None,
    )

    StructureViewer.set_data(
        viewer,
        document.structure,
        object(),
        document.hierarchy,
        reset_camera=False,
    )

    assert viewer.comparison_highlight is marker


def test_set_document_clears_stale_highlight_when_document_identity_changes() -> None:
    first = _document()
    second = StructureDocument(
        id="same-structure-second-document",
        structure=first.structure,
        hierarchy=first.hierarchy,
        warnings=(),
    )
    marker = ComparisonHighlight({"P1": "#123456"}, {}, set(), set())
    data_calls: list[tuple[object, object, object, bool]] = []
    visual_calls: list[tuple[object, bool]] = []
    viewer = SimpleNamespace(
        _document=first,
        comparison_highlight=marker,
        set_data=lambda structure, scene, hierarchy, reset_camera: data_calls.append(
            (structure, scene, hierarchy, reset_camera)
        ),
        apply_visual_state=lambda state, redraw: visual_calls.append((state, redraw)),
    )

    StructureViewer.set_document(viewer, second, reset_camera=False)

    assert viewer.comparison_highlight is None
    assert viewer._document is second
    assert len(data_calls) == 1
    assert visual_calls == [(second.visual, True)]


def test_set_document_retains_highlight_when_reapplying_same_document() -> None:
    document = _document()
    marker = ComparisonHighlight({"P1": "#123456"}, {}, set(), set())
    viewer = SimpleNamespace(
        _document=document,
        comparison_highlight=marker,
        set_data=lambda structure, scene, hierarchy, reset_camera: None,
        apply_visual_state=lambda state, redraw: None,
    )

    StructureViewer.set_document(viewer, document, reset_camera=False)

    assert viewer.comparison_highlight is marker


def test_camera_state_uses_offsets_from_structure_center() -> None:
    camera = SimpleNamespace(
        position=(12.5, 3.0, 3.5),
        focal_point=(2.5, 3.0, 3.5),
        up=(0.0, 0.0, 1.0),
        parallel_scale=4.0,
        view_angle=30.0,
        parallel_projection=True,
    )
    viewer = SimpleNamespace(
        structure=_document().structure,
        plotter=SimpleNamespace(camera=camera),
        _structure_center=lambda: np.asarray((2.5, 3.0, 3.5)),
    )

    state = StructureViewer.camera_state(viewer)

    assert state.position == (10.0, 0.0, 0.0)
    assert state.focal_offset == (0.0, 0.0, 0.0)
    assert state.parallel_projection is True


def test_set_and_clear_comparison_highlight_redraw_without_resetting_camera_or_visibility() -> None:
    redraws: list[bool] = []
    viewer = SimpleNamespace(
        comparison_highlight=None,
        hidden_atom_indices={1},
        hidden_polyhedron_ids={"P2"},
        hidden_unit_ids={"U2"},
        hidden_block_ids={"B2"},
        hidden_connector_ids={"C2"},
        redraw=lambda reset_camera: redraws.append(reset_camera),
    )
    highlight = ComparisonHighlight({"P1": "#123456"}, {3: "#654321"}, {"P1"}, set())

    StructureViewer.set_comparison_highlight(viewer, highlight)
    StructureViewer.set_comparison_highlight(viewer, None)

    assert viewer.comparison_highlight is None
    assert redraws == [False, False]
    assert viewer.hidden_atom_indices == {1}
    assert viewer.hidden_polyhedron_ids == {"P2"}
    assert viewer.hidden_unit_ids == {"U2"}
    assert viewer.hidden_block_ids == {"B2"}
    assert viewer.hidden_connector_ids == {"C2"}


class _RecordingPlotter:
    def __init__(self) -> None:
        self.meshes: list[tuple[object, dict[str, object]]] = []

    def add_mesh(self, mesh, **kwargs) -> None:
        self.meshes.append((mesh, kwargs))


def test_topology_is_drawn_in_crystallographic_coordinates_and_honours_families(
    monkeypatch,
) -> None:
    sites = [
        AtomSite("B1", "B", (0.1, 0.0, 0.0)),
        AtomSite("B2", "B", (0.4, 0.0, 0.0)),
        AtomSite("O1", "O", (0.2, 0.0, 0.0)),
    ]
    polyhedra = (
        CoordinationPolyhedron(
            "P1", 0, "B", "O", (PeriodicSiteRef(2),), (1.0,),
            ((2.0, 0.0, 0.0),), 0.0, 0.0,
        ),
        CoordinationPolyhedron(
            "P2", 1, "B", "O", (PeriodicSiteRef(2),), (1.0,),
            ((2.0, 0.0, 0.0),), 0.0, 0.0,
        ),
    )
    hierarchy = HierarchyReport(
        polyhedra=list(polyhedra),
        polyhedron_connections=[
            PolyhedronConnection(
                "P1", "P2", (PeriodicSiteRef(2),), "corner", False, (1, 0, 0)
            )
        ],
    )
    component = TopologyComponent(
        "TC1", ("P1", "P2"), 1, "chain", ((1, 0, 0),),
        ((1, 0, 0),), None, (("corner", 1),),
    )
    report = InorganicTopologyReport(
        (component,),
        (
            TopologyFamily(
                "TF1", ("TC1",), "chain", 1, ((1, 0, 0),), None,
                ("BO₁",), (("corner", 1),),
            ),
        ),
        frozenset({"P1", "P2"}), (), True,
    )
    structure = CrystalStructure("chain", UnitCell(10, 10, 10), sites, sites)
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        structure=structure,
        hierarchy=hierarchy,
        _document=SimpleNamespace(inorganic_topology=report),
        hidden_topology_family_ids=set(),
        plotter=plotter,
    )
    StructureViewer._draw_topology(viewer)

    assert len(plotter.meshes) == 3
    assert all(
        options["name"].startswith("topology:TF1:")
        for _mesh, options in plotter.meshes
    )
    line = plotter.meshes[-1][0]
    assert np.allclose(line.points[0], (1.0, 0.0, 0.0))
    assert np.allclose(line.points[-1], (14.0, 0.0, 0.0))

    plotter.meshes.clear()
    viewer.hidden_topology_family_ids = {"TF1"}
    StructureViewer._draw_topology(viewer)
    assert plotter.meshes == []


def test_cation_topology_distinguishes_shared_ligand_and_geometric_edges() -> None:
    sites = [
        AtomSite("Y1", "Y", (0.1, 0.0, 0.0)),
        AtomSite("Ca1", "Ca", (0.4, 0.0, 0.0)),
        AtomSite("O1", "O", (0.2, 0.0, 0.0)),
    ]
    polyhedra = (
        CoordinationPolyhedron(
            "P1", 0, "Y", "O", (PeriodicSiteRef(2),), (1.0,),
            ((2.0, 0.0, 0.0),), 0.0, 0.0,
        ),
        CoordinationPolyhedron(
            "P2", 1, "Ca", "O", (PeriodicSiteRef(2),), (1.0,),
            ((2.0, 0.0, 0.0),), 0.0, 0.0,
        ),
    )
    hierarchy = HierarchyReport(polyhedra=list(polyhedra))
    component = TopologyComponent(
        "CC1", ("P1", "P2"), 1, "chain", ((1, 0, 0),),
        ((1, 0, 0),), None, (("shared-ligand", 1), ("geometric", 1)),
    )
    report = InorganicTopologyReport(
        (), (), frozenset(), (), True,
        cation_components=(component,),
        cation_families=(
            TopologyFamily(
                "CF1", ("CC1",), "chain", 1, ((1, 0, 0),), None,
                ("CaO1", "YO1"), (("shared-ligand", 1), ("geometric", 1)),
                representation="cation", distance_range=(3.0, 7.0),
            ),
        ),
        cation_edges=(
            CationTopologyEdge("P1", "P2", (0, 0, 0), "shared-ligand", 3.0, (2,)),
            CationTopologyEdge("P1", "P2", (1, 0, 0), "geometric", 7.0),
        ),
        cation_polyhedron_ids=frozenset({"P1", "P2"}),
    )
    structure = CrystalStructure("cation-chain", UnitCell(10, 10, 10), sites, sites)
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        structure=structure,
        hierarchy=hierarchy,
        _document=SimpleNamespace(inorganic_topology=report),
        hidden_topology_family_ids=set(),
        plotter=plotter,
    )

    StructureViewer._draw_topology(viewer)

    names = [options["name"] for _mesh, options in plotter.meshes]
    assert any(name.startswith("topology:CF1:cation-node:") for name in names)
    node_colors = {
        options["color"]
        for _mesh, options in plotter.meshes
        if ":cation-node:" in options["name"]
    }
    assert node_colors == {ELEMENT_COLORS["Y"], ELEMENT_COLORS["Ca"]}
    shared = next(options for _mesh, options in plotter.meshes if ":shared-ligand-edge:" in options["name"])
    geometric = next(options for _mesh, options in plotter.meshes if ":geometric-edge:" in options["name"])
    assert shared["line_width"] > geometric["line_width"]
    assert shared["opacity"] > geometric["opacity"]


def test_topology_repeats_nodes_and_edges_over_fractional_display_bounds() -> None:
    sites = [
        AtomSite("B1", "B", (0.1, 0.0, 0.0)),
        AtomSite("B2", "B", (0.4, 0.0, 0.0)),
        AtomSite("O1", "O", (0.2, 0.0, 0.0)),
    ]
    polyhedra = (
        CoordinationPolyhedron(
            "P1", 0, "B", "O", (PeriodicSiteRef(2),), (1.0,),
            ((2.0, 0.0, 0.0),), 0.0, 0.0,
        ),
        CoordinationPolyhedron(
            "P2", 1, "B", "O", (PeriodicSiteRef(2),), (1.0,),
            ((2.0, 0.0, 0.0),), 0.0, 0.0,
        ),
    )
    hierarchy = HierarchyReport(
        polyhedra=list(polyhedra),
        polyhedron_connections=[
            PolyhedronConnection(
                "P1", "P2", (PeriodicSiteRef(2),), "corner", False, (0, 0, 0)
            )
        ],
    )
    component = TopologyComponent(
        "TC1", ("P1", "P2"), 1, "chain", ((1, 0, 0),),
        ((1, 0, 0),), None, (("corner", 1),),
    )
    report = InorganicTopologyReport(
        (component,),
        (
            TopologyFamily(
                "TF1", ("TC1",), "chain", 1, ((1, 0, 0),), None,
                ("BO₁",), (("corner", 1),),
            ),
        ),
        frozenset({"P1", "P2"}), (), True,
    )
    structure = CrystalStructure("repeat-chain", UnitCell(10, 10, 10), sites, sites)
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        structure=structure,
        hierarchy=hierarchy,
        scene=SimpleNamespace(
            fractional_translations=((0, 0, 0), (1, 0, 0)),
            translations=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            bounds=((0.0, 2.0), (0.0, 1.0), (0.0, 1.0)),
        ),
        _document=SimpleNamespace(inorganic_topology=report),
        hidden_topology_family_ids=set(),
        plotter=plotter,
    )
    viewer._translations_for_site = MethodType(StructureViewer._translations_for_site, viewer)

    StructureViewer._draw_topology(viewer)

    names = [options["name"] for _mesh, options in plotter.meshes]
    assert len(names) == 6
    assert len(set(names)) == 6
    edge_starts = [
        mesh.points[0]
        for mesh, options in plotter.meshes
        if ":edge:" in options["name"]
    ]
    assert any(np.allclose(point, (1.0, 0.0, 0.0)) for point in edge_starts)
    assert any(np.allclose(point, (11.0, 0.0, 0.0)) for point in edge_starts)


def test_cell_frame_defaults_to_original_cell_and_grid_is_opt_in() -> None:
    structure = CrystalStructure(
        "cell-frame",
        UnitCell(10, 10, 10),
        [AtomSite("B1", "B", (0.0, 0.0, 0.0))],
        [AtomSite("B1", "B", (0.0, 0.0, 0.0))],
    )
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        structure=structure,
        scene=SimpleNamespace(
            translations=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            cell_edges=(
                (0, 1), (1, 2), (2, 3), (3, 0),
                (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7),
            ),
        ),
        plotter=plotter,
        render_style="publication",
        cell_line_width=1.8,
        show_cell_dimensions=False,
        show_periodic_cell_grid=False,
    )
    viewer._translations = MethodType(StructureViewer._translations, viewer)

    StructureViewer._draw_cell(viewer)
    assert len(plotter.meshes) == 12

    plotter.meshes.clear()
    viewer.show_periodic_cell_grid = True
    StructureViewer._draw_cell(viewer)
    assert len(plotter.meshes) == 20


def test_units_and_blocks_filter_integer_images_by_fractional_center_bounds(monkeypatch) -> None:
    monkeypatch.setattr(viewer_module, "build_surface_batch", lambda instances: tuple(instances))
    viewer = _polyhedron_viewer(None, show_edges=False)
    viewer.structure = CrystalStructure(
        "bounded-aggregate",
        UnitCell(10, 10, 10),
        [AtomSite("Si1", "Si", (0.1, 0.0, 0.0))],
        [AtomSite("Si1", "Si", (0.1, 0.0, 0.0))],
    )
    viewer.hierarchy.polyhedra = (viewer.hierarchy.polyhedra[0],)
    viewer.hierarchy.structural_units = (
        SimpleNamespace(id="U1", classification="island", polyhedron_ids=("P1",)),
    )
    viewer.hierarchy.blocks = (
        SimpleNamespace(id="RB1", classification="rigid", rigidity_score=1.0, polyhedron_ids=("P1",)),
    )
    viewer.scene = SimpleNamespace(
        atoms=(),
        fractional_translations=((0, 0, 0), (1, 0, 0)),
        translations=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
        bounds=((0.5, 1.5), (0.0, 1.0), (0.0, 1.0)),
    )
    viewer.hidden_block_ids = set()
    viewer._resolved_color_mode = lambda _default: "block"
    viewer._block_colors = lambda: {"RB1": "#397ed1"}
    viewer._translations_for_site = MethodType(StructureViewer._translations_for_site, viewer)
    viewer._aggregate_translations = MethodType(StructureViewer._aggregate_translations, viewer)

    StructureViewer._draw_structural_units(viewer)
    unit_instances = [instance for mesh, _options in viewer.plotter.meshes for instance in mesh]
    assert [instance.translation for instance in unit_instances] == [(10.0, 0.0, 0.0)]

    viewer.plotter.meshes.clear()
    StructureViewer._draw_rigid_blocks(viewer)
    block_instances = [instance for mesh, _options in viewer.plotter.meshes for instance in mesh]
    assert [instance.translation for instance in block_instances] == [(10.0, 0.0, 0.0)]


def test_bicolor_bonds_are_drawn_as_one_smooth_point_gradient(monkeypatch) -> None:
    atoms = (
        SimpleNamespace(
            site_index=0,
            site=AtomSite("B1", "B", (0.0, 0.0, 0.0)),
            cartesian=(0.0, 0.0, 0.0),
        ),
        SimpleNamespace(
            site_index=1,
            site=AtomSite("O1", "O", (0.0, 0.0, 0.0)),
            cartesian=(0.0, 0.0, 1.4),
        ),
    )
    captured = []
    monkeypatch.setattr(
        viewer_module,
        "build_gradient_cylinder_batch",
        lambda instances, _detail: captured.extend(instances) or "gradient-batch",
    )
    viewer = SimpleNamespace(
        scene=SimpleNamespace(atoms=atoms, bonds=(SimpleNamespace(first=0, second=1),)),
        hidden_bond_orbits=set(),
        atom_orbit_colors={"B1": "#112233", "O1": "#ddeeff"},
        bond_style="bicolor",
        bond_radius=0.05,
        plotter=_RecordingPlotter(),
    )

    StructureViewer._draw_bonds(viewer)

    assert len(captured) == 1
    assert captured[0].start_rgb != captured[0].end_rgb
    assert len(viewer.plotter.meshes) == 1
    assert viewer.plotter.meshes[0][1]["scalars"] == "bond_rgb"
    assert viewer.plotter.meshes[0][1]["preference"] == "point"


def test_atom_highlight_overrides_mixed_occupancy_and_clear_restores_sectors(monkeypatch) -> None:
    site = AtomSite(
        "T1",
        "Al/Si",
        (0.0, 0.0, 0.0),
        components=(SiteComponent("Al", 0.5), SiteComponent("Si", 0.4)),
    )
    atom = SimpleNamespace(site_index=3, site=site, cartesian=(1.0, 2.0, 3.0))
    sphere_calls: list[tuple[object, ...]] = []
    occupancy_calls: list[tuple[object, ...]] = []

    def build_spheres(instances, _detail):
        sphere_calls.append(tuple(instances))
        return ("sphere-batch", len(instances))

    def build_occupancies(instances, _detail):
        occupancy_calls.append(tuple(instances))
        return ("occupancy-batch", len(instances)) if instances else None

    monkeypatch.setattr(viewer_module, "build_sphere_batch", build_spheres)
    monkeypatch.setattr(viewer_module, "build_occupancy_sphere_batch", build_occupancies)
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        scene=SimpleNamespace(atoms=(atom,)),
        hidden_atom_indices=set(),
        split_mixed_occupancies=True,
        show_vacancy_sectors=True,
        atom_scale=1.0,
        comparison_highlight=ComparisonHighlight({}, {3: SUBSTITUTION_YELLOW}, set(), set()),
        plotter=plotter,
    )

    StructureViewer._draw_atoms(viewer)

    assert len(sphere_calls) == 1
    assert occupancy_calls == [()]
    assert plotter.meshes[0][1]["color"] == SUBSTITUTION_YELLOW

    sphere_calls.clear()
    occupancy_calls.clear()
    plotter.meshes.clear()
    viewer.comparison_highlight = None

    StructureViewer._draw_atoms(viewer)

    assert sphere_calls == []
    assert len(occupancy_calls) == 1
    assert len(occupancy_calls[0]) == 1
    sectors = occupancy_calls[0][0].sectors
    assert sectors[:2] == (
        (tuple(int(ELEMENT_COLORS["Al"][index : index + 2], 16) for index in (1, 3, 5)), 0.5),
        (tuple(int(ELEMENT_COLORS["Si"][index : index + 2], 16) for index in (1, 3, 5)), 0.4),
    )
    assert sectors[2][0] == tuple(
        int(VACANCY_COLOR[index : index + 2], 16) for index in (1, 3, 5)
    )
    assert np.isclose(sectors[2][1], 0.1)
    assert plotter.meshes[0][1]["scalars"] == "occupancy_rgb"


def test_manual_atom_colour_replaces_mixed_occupancy_sectors_on_the_scene(monkeypatch) -> None:
    site = AtomSite(
        "T1",
        "Al/Si",
        (0.0, 0.0, 0.0),
        components=(SiteComponent("Al", 0.5), SiteComponent("Si", 0.5)),
    )
    atom = SimpleNamespace(site_index=0, site=site, cartesian=(1.0, 2.0, 3.0))
    sphere_calls: list[tuple[object, ...]] = []
    occupancy_calls: list[tuple[object, ...]] = []

    def build_spheres(instances, _detail):
        sphere_calls.append(tuple(instances))
        return "sphere-batch"

    def build_occupancies(instances, _detail):
        occupancy_calls.append(tuple(instances))
        return "occupancy-batch" if instances else None

    monkeypatch.setattr(viewer_module, "build_sphere_batch", build_spheres)
    monkeypatch.setattr(viewer_module, "build_occupancy_sphere_batch", build_occupancies)
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        scene=SimpleNamespace(atoms=(atom,)),
        hidden_atom_indices=set(),
        split_mixed_occupancies=True,
        show_vacancy_sectors=True,
        atom_scale=1.0,
        atom_orbit_colors={"T1": "#123456"},
        comparison_highlight=None,
        plotter=plotter,
    )

    StructureViewer._draw_atoms(viewer)

    assert len(sphere_calls) == 1
    assert occupancy_calls == [()]
    assert plotter.meshes[0][1]["color"] == "#123456"


def test_unmatched_interstitial_draws_one_red_outline_batch_with_source_indices(monkeypatch) -> None:
    site = AtomSite(
        "T1",
        "Al/Si",
        (0.0, 0.0, 0.0),
        components=(SiteComponent("Al", 0.5), SiteComponent("Si", 0.4)),
    )
    atom = SimpleNamespace(site_index=3, site=site, cartesian=(1.0, 2.0, 3.0))
    sphere_calls: list[tuple[object, ...]] = []

    def build_spheres(instances, _detail):
        captured = tuple(instances)
        sphere_calls.append(captured)
        return ("sphere-batch", len(sphere_calls))

    monkeypatch.setattr(viewer_module, "build_sphere_batch", build_spheres)
    monkeypatch.setattr(
        viewer_module,
        "build_occupancy_sphere_batch",
        lambda instances, _detail: None,
    )
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        scene=SimpleNamespace(atoms=(atom,)),
        hidden_atom_indices=set(),
        split_mixed_occupancies=True,
        show_vacancy_sectors=True,
        atom_scale=1.0,
        comparison_highlight=ComparisonHighlight(
            {},
            {3: MUTED_COLOR},
            {"I3"},
            {"I3"},
        ),
        plotter=plotter,
    )

    StructureViewer._draw_atoms(viewer)

    red_calls = [
        (mesh, options)
        for mesh, options in plotter.meshes
        if options.get("color") == OUTLINE_RED
    ]
    assert len(red_calls) == 1
    assert red_calls[0][1]["style"] == "wireframe"
    assert len(sphere_calls) == 2
    assert sphere_calls[1][0].source_index == 0
    assert sphere_calls[1][0].radius > sphere_calls[0][0].radius


def test_atom_outline_batch_is_absent_when_interstitial_is_not_outlined(monkeypatch) -> None:
    atom = SimpleNamespace(
        site_index=3,
        site=AtomSite("Si1", "Si", (0.0, 0.0, 0.0)),
        cartesian=(1.0, 2.0, 3.0),
    )
    sphere_calls: list[tuple[object, ...]] = []

    def build_spheres(instances, _detail):
        sphere_calls.append(tuple(instances))
        return ("sphere-batch", len(sphere_calls))

    monkeypatch.setattr(viewer_module, "build_sphere_batch", build_spheres)
    monkeypatch.setattr(
        viewer_module,
        "build_occupancy_sphere_batch",
        lambda instances, _detail: None,
    )
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        scene=SimpleNamespace(atoms=(atom,)),
        hidden_atom_indices=set(),
        split_mixed_occupancies=True,
        show_vacancy_sectors=True,
        atom_scale=1.0,
        comparison_highlight=ComparisonHighlight({}, {3: MATCH_PALETTE[0]}, set(), set()),
        plotter=plotter,
    )

    StructureViewer._draw_atoms(viewer)

    assert len(sphere_calls) == 1


def test_lithium_atom_uses_an_element_colour_instead_of_unknown_grey(monkeypatch) -> None:
    atom = SimpleNamespace(
        site_index=0,
        site=AtomSite("Li1", "Li", (0.0, 0.0, 0.0)),
        cartesian=(0.0, 0.0, 0.0),
    )
    monkeypatch.setattr(
        viewer_module,
        "build_sphere_batch",
        lambda instances, _detail: ("sphere-batch", len(tuple(instances))),
    )
    monkeypatch.setattr(
        viewer_module,
        "build_occupancy_sphere_batch",
        lambda instances, _detail: None,
    )
    plotter = _RecordingPlotter()
    viewer = SimpleNamespace(
        scene=SimpleNamespace(atoms=(atom,)),
        hidden_atom_indices=set(),
        split_mixed_occupancies=True,
        show_vacancy_sectors=True,
        atom_scale=1.0,
        comparison_highlight=None,
        plotter=plotter,
    )

    StructureViewer._draw_atoms(viewer)

    assert plotter.meshes[0][1]["color"] != "#c7d0da"
    assert all(options.get("color") != OUTLINE_RED for _, options in plotter.meshes)


def _polyhedron_viewer(highlight: ComparisonHighlight | None, *, show_edges: bool = True):
    polyhedra = (
        SimpleNamespace(
            id="P1",
            center_index=0,
            center_element="Si",
            coordination_number=4,
            distortion=0.02,
            vertex_coordinates=((0.0, 0.0, 0.0),),
        ),
        SimpleNamespace(
            id="P2",
            center_index=1,
            center_element="Al",
            coordination_number=6,
            distortion=0.02,
            vertex_coordinates=((1.0, 0.0, 0.0),),
        ),
    )
    viewer = SimpleNamespace(
        hierarchy=SimpleNamespace(polyhedra=polyhedra),
        structure=SimpleNamespace(
            cartesian_positions=np.asarray(
                ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            )
        ),
        scene=SimpleNamespace(atoms=()),
        render_style="publication",
        radius_model="uniform",
        atom_scale=1.0,
        polyhedron_opacity=0.36,
        polyhedron_edge_radius=0.02,
        show_polyhedron_edges=show_edges,
        show_labels=False,
        show_centers=True,
        hidden_unit_ids=set(),
        comparison_highlight=highlight,
        plotter=_RecordingPlotter(),
        _block_colors=lambda: {},
        _polyhedron_block_map=lambda: {},
        _unit_colors=lambda: {"U1": "#397ed1"},
        _polyhedron_unit_map=lambda: {"P1": "U1", "P2": "U1"},
        _polyhedron_visible=lambda _polyhedron: True,
        _base_polyhedron_surface=lambda polyhedron: f"face:{polyhedron.id}",
        _base_edge_surface=lambda surface, radius, _detail: f"edge:{surface}:{radius:.3f}",
        _translations=lambda: (np.zeros(3),),
    )
    viewer._draw_polyhedron_centers = MethodType(
        StructureViewer._draw_polyhedron_centers,
        viewer,
    )
    viewer._draw_atoms = MethodType(StructureViewer._draw_atoms, viewer)
    return viewer


def _fake_surface_batch(instances):
    return tuple(instance.surface for instance in instances)


def _fake_sphere_batch(instances, _detail):
    return tuple(instances)


def test_polyhedron_muted_override_draws_separate_red_outline_batch(monkeypatch) -> None:
    monkeypatch.setattr(viewer_module, "build_surface_batch", _fake_surface_batch)
    viewer = _polyhedron_viewer(
        ComparisonHighlight(
            {"P1": MATCH_PALETTE[0]},
            {},
            {"P1"},
            {"P1"},
        )
    )

    StructureViewer._draw_polyhedra(viewer, color_mode="element")

    muted_surfaces = [
        mesh
        for mesh, options in viewer.plotter.meshes
        if options.get("color") == MUTED_COLOR
    ]
    red_outlines = [
        mesh
        for mesh, options in viewer.plotter.meshes
        if options.get("color") == OUTLINE_RED
    ]
    ordinary_edges_for_p1 = [
        mesh
        for mesh, options in viewer.plotter.meshes
        if options.get("color") not in {MUTED_COLOR, OUTLINE_RED}
        and any("edge:face:P1" in part for part in mesh)
    ]

    assert muted_surfaces == [("face:P1",)]
    assert len(red_outlines) == 1
    assert any("edge:face:P1" in part for part in red_outlines[0])
    assert len(ordinary_edges_for_p1) == 1


def test_structural_unit_keeps_partial_highlight_and_clear_restores_unit_color(monkeypatch) -> None:
    monkeypatch.setattr(viewer_module, "build_surface_batch", _fake_surface_batch)
    viewer = _polyhedron_viewer(
        ComparisonHighlight({"P1": MATCH_PALETTE[0]}, {}, set(), set()),
        show_edges=False,
    )
    viewer.hierarchy.structural_units = (
        SimpleNamespace(
            id="U1",
            classification="chain",
            polyhedron_ids=("P1", "P2"),
        ),
    )

    StructureViewer._draw_structural_units(viewer)

    surface_colors = {
        part: options["color"]
        for mesh, options in viewer.plotter.meshes
        for part in mesh
        if part.startswith("face:")
    }
    assert surface_colors == {"face:P1": MATCH_PALETTE[0], "face:P2": "#397ed1"}

    viewer.plotter.meshes.clear()
    viewer.comparison_highlight = None
    StructureViewer._draw_structural_units(viewer)

    restored_surface_calls = [
        (mesh, options["color"])
        for mesh, options in viewer.plotter.meshes
        if any(part.startswith("face:") for part in mesh)
    ]
    assert restored_surface_calls == [(('face:P1', 'face:P2'), "#397ed1")]


def test_interstitial_center_semantics_do_not_recolor_polyhedron_surfaces(monkeypatch) -> None:
    monkeypatch.setattr(viewer_module, "build_surface_batch", _fake_surface_batch)
    monkeypatch.setattr(viewer_module, "build_sphere_batch", _fake_sphere_batch)
    viewer = _polyhedron_viewer(
        ComparisonHighlight(
            {},
            {0: SUBSTITUTION_YELLOW, 1: SUBSTITUTION_YELLOW},
            {"I1"},
            {"I1"},
        ),
        show_edges=False,
    )

    StructureViewer._draw_polyhedra(viewer, color_mode="element")
    StructureViewer._draw_polyhedron_centers(viewer)

    face_colors = {
        part: options["color"]
        for mesh, options in viewer.plotter.meshes
        for part in mesh
        if isinstance(part, str) and part.startswith("face:")
    }
    assert set(face_colors) == {"face:P1", "face:P2"}
    assert set(face_colors.values()).isdisjoint(
        {SUBSTITUTION_YELLOW, MUTED_COLOR, OUTLINE_RED}
    )
    semantic_batches = {
        options["color"]: mesh
        for mesh, options in viewer.plotter.meshes
        if options.get("color") in {SUBSTITUTION_YELLOW, MUTED_COLOR, OUTLINE_RED}
    }
    assert semantic_batches[SUBSTITUTION_YELLOW][0].source_index == 0
    assert semantic_batches[MUTED_COLOR][0].source_index == 1
    assert semantic_batches[OUTLINE_RED][0].source_index == 1


def test_structural_units_render_only_semantically_highlighted_centers(monkeypatch) -> None:
    monkeypatch.setattr(viewer_module, "build_surface_batch", _fake_surface_batch)
    monkeypatch.setattr(viewer_module, "build_sphere_batch", _fake_sphere_batch)
    viewer = _polyhedron_viewer(
        ComparisonHighlight(
            {},
            {0: SUBSTITUTION_YELLOW, 1: MUTED_COLOR},
            {"I1"},
            {"I1"},
        ),
        show_edges=False,
    )
    viewer.hierarchy.structural_units = (
        SimpleNamespace(
            id="U1",
            classification="chain",
            polyhedron_ids=("P1", "P2"),
        ),
    )

    StructureViewer._draw_structural_units(viewer)

    surface_calls = [
        (mesh, options["color"])
        for mesh, options in viewer.plotter.meshes
        if any(isinstance(part, str) and part.startswith("face:") for part in mesh)
    ]
    assert surface_calls == [(('face:P1', 'face:P2'), "#397ed1")]
    semantic_colors = {
        options["color"]
        for mesh, options in viewer.plotter.meshes
        if mesh and not isinstance(mesh[0], str)
    }
    assert semantic_colors == {SUBSTITUTION_YELLOW, MUTED_COLOR, OUTLINE_RED}


def test_structural_units_render_highlighted_interstitial_without_recoloring_surfaces(
    monkeypatch,
) -> None:
    monkeypatch.setattr(viewer_module, "build_surface_batch", _fake_surface_batch)
    monkeypatch.setattr(viewer_module, "build_sphere_batch", _fake_sphere_batch)
    monkeypatch.setattr(
        viewer_module,
        "build_occupancy_sphere_batch",
        lambda instances, _detail: None,
    )
    viewer = _polyhedron_viewer(
        ComparisonHighlight(
            {},
            {3: MUTED_COLOR},
            {"I3"},
            {"I3"},
        ),
        show_edges=False,
    )
    viewer.hierarchy.structural_units = (
        SimpleNamespace(
            id="U1",
            classification="chain",
            polyhedron_ids=("P1", "P2"),
        ),
    )
    viewer.scene.atoms = (
        SimpleNamespace(site_index=0, site=AtomSite("Si1", "Si", (0, 0, 0)), cartesian=(0, 0, 0)),
        SimpleNamespace(site_index=1, site=AtomSite("Al1", "Al", (0, 0, 0)), cartesian=(1, 0, 0)),
        SimpleNamespace(site_index=3, site=AtomSite("Na1", "Na", (0, 0, 0)), cartesian=(2, 0, 0)),
    )
    viewer.hidden_atom_indices = {0, 1}
    viewer.split_mixed_occupancies = True
    viewer.show_vacancy_sectors = True
    viewer._draw_atoms = MethodType(StructureViewer._draw_atoms, viewer)
    viewer._polyhedron_visible = lambda _polyhedron: False

    StructureViewer._draw_structural_units(viewer)

    semantic = {
        options["color"]: mesh
        for mesh, options in viewer.plotter.meshes
        if options.get("color") in {MUTED_COLOR, OUTLINE_RED}
    }
    assert semantic[MUTED_COLOR][0].source_index == 2
    assert semantic[OUTLINE_RED][0].source_index == 2
    assert semantic[OUTLINE_RED][0].radius > semantic[MUTED_COLOR][0].radius


def test_structural_units_do_not_duplicate_highlighted_polyhedron_center(
    monkeypatch,
) -> None:
    monkeypatch.setattr(viewer_module, "build_surface_batch", _fake_surface_batch)
    monkeypatch.setattr(viewer_module, "build_sphere_batch", _fake_sphere_batch)
    monkeypatch.setattr(
        viewer_module,
        "build_occupancy_sphere_batch",
        lambda instances, _detail: None,
    )
    viewer = _polyhedron_viewer(
        ComparisonHighlight(
            {},
            {0: SUBSTITUTION_YELLOW, 3: MATCH_PALETTE[0]},
            set(),
            set(),
        ),
        show_edges=False,
    )
    viewer.hierarchy.structural_units = (
        SimpleNamespace(
            id="U1",
            classification="chain",
            polyhedron_ids=("P1", "P2"),
        ),
    )
    viewer.scene.atoms = (
        SimpleNamespace(site_index=0, site=AtomSite("Si1", "Si", (0, 0, 0)), cartesian=(0, 0, 0)),
        SimpleNamespace(site_index=3, site=AtomSite("Na1", "Na", (0, 0, 0)), cartesian=(2, 0, 0)),
    )
    viewer.hidden_atom_indices = set()
    viewer.split_mixed_occupancies = True
    viewer.show_vacancy_sectors = True
    viewer._draw_atoms = MethodType(StructureViewer._draw_atoms, viewer)

    StructureViewer._draw_structural_units(viewer)

    yellow_instances = [
        instance
        for mesh, options in viewer.plotter.meshes
        if options.get("color") == SUBSTITUTION_YELLOW
        for instance in mesh
    ]
    interstitial_instances = [
        instance
        for mesh, options in viewer.plotter.meshes
        if options.get("color") == MATCH_PALETTE[0]
        for instance in mesh
    ]
    assert len(yellow_instances) == 1
    assert len(interstitial_instances) == 1
