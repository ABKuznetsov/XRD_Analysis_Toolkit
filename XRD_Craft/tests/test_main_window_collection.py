from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.analysis.organic.pipeline import iter_analyze_organic
from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult
from crystal_viewer.analysis.progressive_analysis import AnalysisSnapshot, AnalysisStage
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.core.progressive_load import LoadStage, StructureLoadUpdate
from crystal_viewer.ui import main_window as main_module
from crystal_viewer.ui.main_window import MainWindow
from crystal_viewer.ui.viewer import CrystalInteractor


def _structure(name: str) -> CrystalStructure:
    sites = [
        AtomSite("Si1", "Si", (0.5, 0.5, 0.5)),
        AtomSite("O1", "O", (0.66, 0.5, 0.5)),
        AtomSite("O2", "O", (0.34, 0.5, 0.5)),
        AtomSite("O3", "O", (0.5, 0.66, 0.5)),
        AtomSite("O4", "O", (0.5, 0.5, 0.66)),
    ]
    return CrystalStructure(
        name=name,
        cell=UnitCell(10.0, 10.0, 10.0),
        asymmetric_sites=sites,
        sites=sites,
    )


def test_registering_two_structures_keeps_both_and_activates_latest() -> None:
    state = SimpleNamespace(
        collection=StructureCollection(),
        active_document_id=None,
        structure=None,
        hierarchy=None,
    )
    structures = (_structure("one"), _structure("two"))

    for structure in structures:
        hierarchy = HierarchyAnalyzer().analyze(structure)
        MainWindow._register_document(state, structure, hierarchy)

    assert len(state.collection.documents) == 2
    assert state.structure is structures[1]
    assert state.active_document_id in state.collection.documents
    assert state.collection.documents[state.active_document_id].hierarchy is state.hierarchy


def test_drop_event_loads_every_cif_and_ignores_other_files() -> None:
    loaded = []
    accepted = []
    urls = [
        SimpleNamespace(toLocalFile=lambda: "/tmp/first.cif"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/notes.txt"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/second.CIF"),
    ]
    event = SimpleNamespace(
        mimeData=lambda: SimpleNamespace(urls=lambda: urls),
        acceptProposedAction=lambda: accepted.append(True),
    )
    state = SimpleNamespace(load_path=loaded.append)

    MainWindow.dropEvent(state, event)

    assert loaded == ["/tmp/first.cif", "/tmp/second.CIF"]
    assert accepted == [True]


def test_drop_event_also_loads_xpff_projects() -> None:
    loaded = []
    accepted = []
    urls = [
        SimpleNamespace(toLocalFile=lambda: "/tmp/project.XPFF"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/notes.txt"),
    ]
    event = SimpleNamespace(
        mimeData=lambda: SimpleNamespace(urls=lambda: urls),
        acceptProposedAction=lambda: accepted.append(True),
    )
    state = SimpleNamespace(load_path=loaded.append)

    MainWindow.dropEvent(state, event)

    assert loaded == ["/tmp/project.XPFF"]
    assert accepted == [True]


def test_drop_event_loads_supported_crystal_and_molecular_formats() -> None:
    loaded = []
    accepted = []
    urls = [
        SimpleNamespace(toLocalFile=lambda: "/tmp/model.res"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/POSCAR"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/model.pdb"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/model.xyz"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/notes.txt"),
    ]
    event = SimpleNamespace(
        mimeData=lambda: SimpleNamespace(urls=lambda: urls),
        acceptProposedAction=lambda: accepted.append(True),
    )
    state = SimpleNamespace(load_path=loaded.append)

    MainWindow.dropEvent(state, event)

    assert loaded == [
        "/tmp/model.res",
        "/tmp/POSCAR",
        "/tmp/model.pdb",
        "/tmp/model.xyz",
    ]
    assert accepted == [True]


def test_vtk_canvas_routes_cif_drop_to_application_loader() -> None:
    emitted = []
    accepted = []
    urls = [
        SimpleNamespace(toLocalFile=lambda: "/tmp/first.cif"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/notes.txt"),
        SimpleNamespace(toLocalFile=lambda: "/tmp/second.CIF"),
    ]
    event = SimpleNamespace(
        mimeData=lambda: SimpleNamespace(urls=lambda: urls),
        acceptProposedAction=lambda: accepted.append(True),
    )
    interactor = SimpleNamespace(
        cif_files_dropped=SimpleNamespace(emit=emitted.append),
    )

    CrystalInteractor.dropEvent(interactor, event)

    assert emitted == [("/tmp/first.cif", "/tmp/second.CIF")]
    assert accepted == [True]


def test_forwarded_canvas_paths_load_every_cif() -> None:
    loaded = []
    state = SimpleNamespace(load_path=loaded.append)

    MainWindow._load_dropped_cifs(state, ("/tmp/first.cif", "/tmp/second.CIF"))

    assert loaded == ["/tmp/first.cif", "/tmp/second.CIF"]


def test_load_path_queues_xpff_without_parsing_on_the_gui_thread(monkeypatch) -> None:
    requests = []
    messages = []
    monkeypatch.setattr(
        main_module,
        "iter_load_updates",
        lambda _path: (_ for _ in ()).throw(AssertionError("parsed synchronously")),
    )
    state = SimpleNamespace(
        _structure_load_requests=SimpleNamespace(
            request=lambda signature, work: requests.append((signature, work))
        ),
        _structure_load_generation=0,
        _structure_load_document_ids={},
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
        series_report=object(),
        current_path=None,
    )

    MainWindow.load_path(state, "/tmp/finder-project.XPFF")

    assert len(requests) == 1
    assert Path(requests[0][0][-1]).name == "finder-project.XPFF"
    assert state.series_report is None
    assert state.current_path.name == "finder-project.XPFF"
    assert messages[-1] == "Reading finder-project.XPFF…"


def test_parsed_progress_installs_an_atom_only_document_before_analysis() -> None:
    structure = _structure("preview")
    source = Path("/tmp/preview.cif")
    signature = (1, str(source))
    rebuilt = []
    refreshed = []
    messages = []
    state = SimpleNamespace(
        _accept_structure_load_results=True,
        _active_structure_load_signature=signature,
        _structure_load_document_ids={},
        collection=StructureCollection(),
        active_document_id=None,
        structure=None,
        hierarchy=None,
        series_report=None,
        _rebuild_scene=lambda **values: rebuilt.append(values),
        _refresh_loading_models=lambda document: refreshed.append(document),
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
    )
    update = StructureLoadUpdate(
        LoadStage.PARSED,
        source,
        0,
        1,
        structure,
    )

    MainWindow._structure_load_progress(state, signature, update)

    document = state.collection.documents[state.active_document_id]
    assert document.analysis_stage == "parsed"
    assert document.periodic_bonds is None
    assert document.structure is structure
    assert rebuilt == [{"reset_camera": True}]
    assert refreshed == [document]
    assert messages[-1].endswith("Atoms ready · calculating bonds…")


def test_final_topology_update_does_not_redraw_an_unchanged_structure_scene() -> None:
    structure = _structure("progressive")
    source = Path("/tmp/progressive.cif")
    signature = (1, str(source))
    document = StructureDocument.from_preview(structure)
    collection = StructureCollection()
    collection.add(document)
    hierarchy = HierarchyAnalyzer().analyze(structure)
    bonds = PeriodicBondResult((), True)
    rebuilt = []
    refreshed = []
    state = SimpleNamespace(
        _accept_structure_load_results=True,
        _active_structure_load_signature=signature,
        _structure_load_document_ids={(signature, 0): document.id},
        collection=collection,
        active_document_id=document.id,
        structure=structure,
        hierarchy=document.hierarchy,
        _rebuild_scene=lambda **values: rebuilt.append(values),
        _refresh_loading_models=lambda value: refreshed.append(("loading", value)),
        _refresh_models=lambda: refreshed.append(("final", document)),
        comparison_mode_stack=SimpleNamespace(currentWidget=lambda: object()),
        morphology_workspace=object(),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )
    units = AnalysisSnapshot(
        AnalysisStage.UNITS,
        bonds,
        hierarchy=hierarchy,
    )
    topology = AnalysisSnapshot(
        AnalysisStage.TOPOLOGY,
        bonds,
        hierarchy=hierarchy,
    )

    MainWindow._structure_load_progress(
        state,
        signature,
        StructureLoadUpdate(LoadStage.UNITS, source, 0, 1, structure, units),
    )
    MainWindow._structure_load_progress(
        state,
        signature,
        StructureLoadUpdate(LoadStage.TOPOLOGY, source, 0, 1, structure, topology),
    )

    assert rebuilt == [{"reset_camera": False}]
    assert [kind for kind, _value in refreshed] == ["loading", "final"]


def test_organic_progress_installs_stages_and_only_redraws_when_bonds_arrive() -> None:
    sites = [
        AtomSite("C1", "C", (0.10, 0.50, 0.50)),
        AtomSite("C2", "C", (0.24, 0.50, 0.50)),
        AtomSite("O1", "O", (0.38, 0.50, 0.50)),
    ]
    structure = CrystalStructure("organic", UnitCell(10, 10, 10), sites, sites)
    source = Path("/tmp/organic.cif")
    signature = (1, str(source))
    document = StructureDocument.from_preview(structure)
    collection = StructureCollection()
    collection.add(document)
    rebuilt = []
    refreshed = []
    messages = []
    state = SimpleNamespace(
        _accept_structure_load_results=True,
        _active_structure_load_signature=signature,
        _structure_load_document_ids={(signature, 0): document.id},
        collection=collection,
        active_document_id=document.id,
        structure=structure,
        hierarchy=document.hierarchy,
        _rebuild_scene=lambda **values: rebuilt.append(values),
        _refresh_loading_models=lambda value: refreshed.append(value.analysis_stage),
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
    )

    for bundle in iter_analyze_organic(structure):
        MainWindow._structure_load_progress(
            state,
            signature,
            StructureLoadUpdate(
                LoadStage(bundle.stage.value), source, 0, 1, structure,
                organic_bundle=bundle,
            ),
        )

    assert document.analysis_stage == "packing"
    assert document.organic_analysis is not None
    assert document.organic_analysis.contacts is not None
    assert rebuilt == [{"reset_camera": False}]
    assert refreshed == ["bonds/profile", "components", "contacts", "packing"]
    assert messages[-1].endswith("Packing analysis ready")


def test_scene_rebuild_installs_the_active_document_in_the_viewer() -> None:
    structure = _structure("topology-source")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    document = StructureDocument.from_structure(structure, hierarchy)
    collection = StructureCollection()
    collection.add(document)

    class RecordingViewer:
        def __init__(self) -> None:
            self._document = None
            self.scene = None

        def set_data(self, _structure, scene, _hierarchy, reset_camera=True) -> None:
            self.scene = scene

        def set_document(
            self, active_document, reset_camera=True, scene=None
        ) -> None:
            self._document = active_document
            self.scene = scene

        def apply_visual_state(self, _state, redraw=True) -> None:
            pass

    viewer = RecordingViewer()
    state = SimpleNamespace(
        structure=structure,
        hierarchy=hierarchy,
        collection=collection,
        active_document_id=document.id,
        viewer=viewer,
        repeat_spins=tuple(SimpleNamespace(value=lambda: 1) for _ in range(3)),
        bond_tolerance=SimpleNamespace(value=lambda: 1.18),
        boundary_atoms_check=SimpleNamespace(isChecked=lambda: True),
    )

    MainWindow._rebuild_scene(state, reset_camera=True)

    assert viewer._document is document
    assert viewer.scene is document.scene_data()


def test_scene_rebuild_uses_fractional_minimum_and_maximum_cell_bounds() -> None:
    structure = _structure("bounded-source")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    document = StructureDocument.from_structure(structure, hierarchy)
    collection = StructureCollection()
    collection.add(document)

    class RecordingViewer:
        def set_document(self, _document, reset_camera=True, scene=None) -> None:
            self.scene = scene

    state = SimpleNamespace(
        structure=structure,
        hierarchy=hierarchy,
        collection=collection,
        active_document_id=document.id,
        viewer=RecordingViewer(),
        cell_min_spins=tuple(
            SimpleNamespace(value=lambda value=value: value)
            for value in (-0.1, 0.0, 0.2)
        ),
        cell_max_spins=tuple(
            SimpleNamespace(value=lambda value=value: value)
            for value in (1.1, 0.8, 1.0)
        ),
        bond_tolerance=SimpleNamespace(value=lambda: 1.18),
        boundary_atoms_check=SimpleNamespace(isChecked=lambda: True),
    )

    MainWindow._rebuild_scene(state)

    assert state.viewer.scene.bounds == ((-0.1, 1.1), (0.0, 0.8), (0.2, 1.0))


def test_hide_selected_uses_a_polyhedron_picked_in_the_3d_view() -> None:
    structure = _structure("picked-source")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    document = StructureDocument.from_structure(structure, hierarchy)
    polyhedron_id = hierarchy.polyhedra[0].id
    collection = StructureCollection()
    collection.add(document)
    hidden: list[tuple[str, str, bool]] = []
    redrawn: list[bool] = []
    messages: list[str] = []
    state = SimpleNamespace(
        _selected_payloads=lambda: [],
        _picked_polyhedron_id=polyhedron_id,
        collection=collection,
        active_document_id=document.id,
        viewer=SimpleNamespace(
            hide_object=lambda kind, identifier, redraw: hidden.append(
                (kind, identifier, redraw)
            ),
            redraw=lambda reset_camera: redrawn.append(reset_camera),
        ),
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
    )

    MainWindow._hide_selected(state)

    assert hidden == [("polyhedron", polyhedron_id, False)]
    assert document.visual.hidden_polyhedron_ids == {polyhedron_id}
    assert redrawn == [False]


def test_hide_selected_uses_any_typed_object_picked_in_edit_mode() -> None:
    structure = _structure("typed-picked-source")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    document = StructureDocument.from_structure(structure, hierarchy)
    collection = StructureCollection()
    collection.add(document)
    hidden: list[tuple[str, object, bool]] = []
    state = SimpleNamespace(
        _selected_payloads=lambda: [],
        _picked_polyhedron_id=None,
        _picked_scene_object=("bond", ("B", "O")),
        collection=collection,
        active_document_id=document.id,
        viewer=SimpleNamespace(
            hide_object=lambda kind, identifier, redraw: hidden.append(
                (kind, identifier, redraw)
            ),
            redraw=lambda reset_camera: None,
        ),
        sites_panel=SimpleNamespace(set_document=lambda _document: None),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )

    MainWindow._hide_selected(state)

    assert hidden == [("bond", ("B", "O"), False)]
    assert document.visual.hidden_bond_families == {("B", "O")}
    assert state._picked_scene_object is None


def test_scene_pick_takes_priority_over_an_old_tree_selection() -> None:
    structure = _structure("picked-priority")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    document = StructureDocument.from_structure(structure, hierarchy)
    collection = StructureCollection()
    collection.add(document)
    hidden: list[tuple[str, object, bool]] = []
    state = SimpleNamespace(
        _selected_payloads=lambda: [("unit", "old-tree-unit", None)],
        _picked_polyhedron_id=None,
        _picked_scene_object=("bond", ("B", "O")),
        collection=collection,
        active_document_id=document.id,
        viewer=SimpleNamespace(
            hide_object=lambda kind, identifier, redraw: hidden.append((kind, identifier, redraw)),
            redraw=lambda reset_camera: None,
        ),
        sites_panel=SimpleNamespace(set_document=lambda _document: None),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )

    MainWindow._hide_selected(state)

    assert hidden == [("bond", ("B", "O"), False)]


def test_escape_clears_the_main_window_scene_selection() -> None:
    state = SimpleNamespace(_picked_scene_object=("atom", 3), _picked_polyhedron_id="P1")

    MainWindow._scene_selection_cleared(state)

    assert state._picked_scene_object is None
    assert state._picked_polyhedron_id is None


def test_scene_pick_updates_the_default_type_to_the_table_it_selected() -> None:
    selected: list[tuple[str, object]] = []
    state = SimpleNamespace(
        _picked_scene_object=None,
        viewer=SimpleNamespace(edit_default_kind="atom"),
        sites_panel=SimpleNamespace(select_object=lambda kind, object_id: selected.append((kind, object_id))),
        object_tree=SimpleNamespace(clearSelection=lambda: None),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )

    MainWindow._scene_object_picked(state, "bond", ("B", "O"))

    assert selected == [("bond", ("B", "O"))]
    assert state.viewer.edit_default_kind == "bond"


def test_isolate_picked_object_updates_document_and_left_table_state() -> None:
    structure = _structure("isolate-sync")
    hierarchy = HierarchyAnalyzer().analyze(structure)
    document = StructureDocument.from_structure(structure, hierarchy)
    collection = StructureCollection()
    collection.add(document)
    refreshed: list[StructureDocument] = []
    viewer = SimpleNamespace(
        hidden_atom_indices=set(),
        hidden_bond_orbits=set(),
        hidden_bond_families=set(),
        hidden_polyhedron_ids=set(),
        hidden_unit_ids=set(),
        hidden_block_ids=set(),
        hidden_connector_ids=set(),
        hidden_topology_family_ids=set(),
        shown_unit_ids={"SU1"},
        shown_block_ids={"RB1"},
    )

    def isolate(kind: str, object_id: object) -> None:
        assert (kind, object_id) == ("bond", ("B", "O"))
        viewer.hidden_bond_families = {("Li", "O")}

    viewer.isolate_object = isolate
    state = SimpleNamespace(
        _selected_payloads=lambda: [("unit", "old", None)],
        _picked_scene_object=("bond", ("B", "O")),
        collection=collection,
        active_document_id=document.id,
        viewer=viewer,
        sites_panel=SimpleNamespace(set_document=refreshed.append),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )

    MainWindow._isolate_selected(state)

    assert document.visual.hidden_bond_families == {("Li", "O")}
    assert document.visual.shown_unit_ids == {"SU1"}
    assert document.visual.shown_block_ids == {"RB1"}
    assert refreshed == [document]


def test_scene_rebuild_rejects_a_non_increasing_cell_interval_without_crashing() -> None:
    messages: list[str] = []
    state = SimpleNamespace(
        structure=_structure("invalid-ui-bounds"),
        cell_min_spins=tuple(
            SimpleNamespace(value=lambda value=value: value)
            for value in (0.0, 0.8, 0.0)
        ),
        cell_max_spins=tuple(
            SimpleNamespace(value=lambda value=value: value)
            for value in (1.0, 0.8, 1.0)
        ),
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
    )

    MainWindow._rebuild_scene(state)

    assert messages == ["Cell bounds require Min < Max for every axis"]
