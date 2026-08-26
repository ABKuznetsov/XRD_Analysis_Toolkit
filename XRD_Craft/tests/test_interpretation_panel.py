from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget

from crystal_viewer.knowledge.matching import MatchEvidence, PresetProposal
from crystal_viewer.knowledge.model import InterpretationChanges
from crystal_viewer.knowledge.resolve import ResolvedInterpretation
from crystal_viewer.ui.interpretation_panel import InterpretationPanel


def _application():
    return QApplication.instance() or QApplication([])


def _proposal():
    return PresetProposal(
        "ring-preset",
        "three-membered borate ring",
        0.94,
        MatchEvidence(1.0, 0.9, 0.95, ((0, 0),), "topology and chemistry matched"),
        InterpretationChanges(name="three-membered borate ring"),
    )


def test_panel_shows_one_high_confidence_proposal_as_selectable_text():
    _application()
    panel = InterpretationPanel()

    panel.set_proposal(_proposal())

    assert panel.status_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert panel.apply_button.isVisibleTo(panel)
    assert panel.dismiss_button.isVisibleTo(panel)
    assert panel.findChildren(QListWidget) == []
    assert "three-membered borate ring" in panel.status_label.text()


def test_no_reliable_result_has_no_apply_action_or_alternative_list():
    _application()
    panel = InterpretationPanel()

    panel.set_no_reliable_suggestion()

    assert "could not be identified reliably" in panel.status_label.text().lower()
    assert not panel.apply_button.isVisibleTo(panel)
    assert panel.findChildren(QListWidget) == []


def test_apply_and_dismiss_emit_only_the_displayed_preset_id():
    _application()
    panel = InterpretationPanel()
    applied = []
    dismissed = []
    panel.apply_requested.connect(applied.append)
    panel.dismiss_requested.connect(dismissed.append)
    panel.set_proposal(_proposal())

    panel.apply_button.click()
    panel.dismiss_button.click()

    assert applied == ["ring-preset"]
    assert dismissed == ["ring-preset"]


def test_read_only_viewer_never_offers_to_confirm_bond_changes():
    _application()
    panel = InterpretationPanel()
    resolved = ResolvedInterpretation(
        domain_id="domain-1",
        name="candidate motif",
        vocabulary="generic",
        member_polyhedron_ids=("P1",),
        role_overrides=(),
        pending_bond_changes=(object(),),
        provenance="user preset",
    )

    panel.set_resolved(resolved)

    assert not panel.confirm_bonds_button.isVisibleTo(panel)
