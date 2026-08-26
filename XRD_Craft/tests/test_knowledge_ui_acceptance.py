from __future__ import annotations

from types import SimpleNamespace

from crystal_viewer.knowledge.model import InterpretationChanges
from crystal_viewer.knowledge.resolve import set_manual_changes
from crystal_viewer.ui.main_window import MainWindow


class _Panel:
    def __init__(self):
        self.resolved = None

    def set_resolved(self, value):
        self.resolved = value


class _Tabs:
    def __init__(self):
        self.current = None

    def indexOf(self, _widget):
        return 4

    def setCurrentIndex(self, index):
        self.current = index


def test_selected_interpretation_opens_resolved_card():
    domain = SimpleNamespace(id="D1", polyhedron_ids=("P1",), classification="island")
    document = SimpleNamespace(
        hierarchy=SimpleNamespace(structural_domains=(domain,)),
        structural_analysis=SimpleNamespace(nomenclature=()),
        knowledge_state=None,
    )
    set_manual_changes(document, "D1", InterpretationChanges(name="known motif"))
    state = SimpleNamespace(
        active_document_id="doc",
        collection=SimpleNamespace(documents={"doc": document}),
        interpretation_panel=_Panel(),
        inspector_tabs=_Tabs(),
        _selected_interpretation_domain_id=None,
    )

    MainWindow._show_interpretation(state, "D1")

    assert state.interpretation_panel.resolved.name == "known motif"
    assert state.interpretation_panel.resolved.provenance == "manual"
    assert state.inspector_tabs.current == 4
