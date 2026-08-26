from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.analysis.structure_profile import (
    ProfileDecision,
    RequestedProfile,
    ResolvedProfile,
)
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _organic_structure() -> CrystalStructure:
    sites = [
        AtomSite("C1", "C", (0.20, 0.50, 0.50)),
        AtomSite("C2", "C", (0.35, 0.50, 0.50)),
        AtomSite("O1", "O", (0.50, 0.50, 0.50)),
    ]
    return CrystalStructure(
        "organic",
        UnitCell(10.0, 10.0, 10.0),
        sites,
        sites,
        source_path=Path("/tmp/organic.cif"),
    )


def _cell_host():
    events: list[int] = []
    host = SimpleNamespace(
        _schedule_scene_rebuild=lambda *_args: None,
        _visualization_changed=lambda *_args: None,
        _profile_requested_changed=events.append,
    )
    host._cell_body = MainWindow._cell_inspector(host)
    return host, events


def test_cell_panel_offers_auto_inorganic_and_organic_profiles() -> None:
    _application()
    host, events = _cell_host()

    assert [
        host.compound_type_combo.itemData(index)
        for index in range(host.compound_type_combo.count())
    ] == [
        RequestedProfile.AUTO.value,
        RequestedProfile.INORGANIC.value,
        RequestedProfile.ORGANIC_METAL_ORGANIC.value,
    ]
    assert host.compound_type_result.text() == "Detected: not analyzed"

    host.compound_type_combo.setCurrentIndex(2)

    assert events == [2]


def test_cell_panel_shows_resolved_type_confidence_and_evidence() -> None:
    _application()
    host, _events = _cell_host()
    structure = _organic_structure()
    document = StructureDocument.from_structure(
        structure,
        HierarchyAnalyzer().analyze(structure),
    )
    document.requested_profile = RequestedProfile.ORGANIC_METAL_ORGANIC
    document.profile_decision = ProfileDecision(
        ResolvedProfile.RETICULAR,
        0.45,
        ("metal-linker periodic rank 1",),
        ("some bonds remain unresolved",),
    )
    collection = StructureCollection()
    collection.add(document)
    host.structure = structure
    host.collection = collection
    host.active_document_id = document.id

    MainWindow._fill_cell(host)

    assert host.compound_type_combo.currentData() == RequestedProfile.ORGANIC_METAL_ORGANIC.value
    assert host.compound_type_result.text() == "Detected: MOF / reticular · low confidence"
    assert "metal-linker periodic rank 1" in host.compound_type_result.toolTip()
    assert "some bonds remain unresolved" in host.compound_type_result.toolTip()


def test_profile_change_clears_old_branch_and_queues_background_reanalysis() -> None:
    _application()
    host, _events = _cell_host()
    structure = _organic_structure()
    document = StructureDocument.from_structure(
        structure,
        HierarchyAnalyzer().analyze(structure),
    )
    document.profile_decision = ProfileDecision(
        ResolvedProfile.INORGANIC,
        0.45,
        ("ambiguous automatic fallback",),
    )
    collection = StructureCollection()
    collection.add(document)
    requests = []
    messages = []
    refreshed = []
    rebuilt = []
    host.collection = collection
    host.active_document_id = document.id
    host.structure = structure
    host.hierarchy = document.hierarchy
    host.current_path = structure.source_path
    host._structure_load_generation = 3
    host._structure_load_document_ids = {}
    host._structure_load_requests = SimpleNamespace(
        request=lambda signature, work: requests.append((signature, work))
    )
    host._refresh_loading_models = refreshed.append
    host._rebuild_scene = lambda **kwargs: rebuilt.append(kwargs)
    host.statusBar = lambda: SimpleNamespace(showMessage=messages.append)
    host.compound_type_combo.setCurrentIndex(2)

    MainWindow._profile_requested_changed(host, 2)

    assert document.requested_profile is RequestedProfile.ORGANIC_METAL_ORGANIC
    assert document.analysis_stage == "parsed"
    assert document.profile_decision is None
    assert not document.hierarchy.polyhedra
    assert len(requests) == 1
    assert requests[0][0][2] == RequestedProfile.ORGANIC_METAL_ORGANIC.value
    assert refreshed == [document]
    assert rebuilt == [{"reset_camera": False}]
    assert messages[-1] == "Reanalyzing as organic / metal-organic…"

    updates = []
    requests[0][1](updates.append)

    assert updates
    assert updates[-1].organic_bundle is not None
    assert updates[-1].organic_bundle.report.profile.resolved is ResolvedProfile.MOLECULAR
