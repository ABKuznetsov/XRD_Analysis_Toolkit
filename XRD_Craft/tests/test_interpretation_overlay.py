from __future__ import annotations

from types import SimpleNamespace

import pytest

from crystal_viewer.knowledge.model import (
    InterpretationChanges,
    KnowledgePreset,
    MotifFingerprint,
    PeriodicBondChange,
)
from crystal_viewer.knowledge.resolve import (
    accept_preset,
    confirm_bond_changes,
    remove_overlay,
    resolve_interpretation,
    set_manual_changes,
)


def _document():
    domain = SimpleNamespace(
        id="D1",
        polyhedron_ids=("P10", "P20", "P30"),
        classification="ring",
    )
    automatic_name = SimpleNamespace(
        domain_id="D1",
        descriptor="automatic borate ring",
        vocabulary="borate",
    )
    return SimpleNamespace(
        hierarchy=SimpleNamespace(structural_domains=(domain,)),
        structural_analysis=SimpleNamespace(nomenclature=(automatic_name,)),
        knowledge_state=None,
        content_identity=lambda: "exact-document-sha",
    )


def _preset(*, scope="reusable", source="another-document"):
    return KnowledgePreset(
        1,
        f"{scope}-preset",
        scope,
        source,
        "structural-analysis-v1",
        (
            MotifFingerprint(
                "periodic-domain-fingerprint-v1",
                0,
                (("node", 3),),
                (),
                "topology",
            )
            if scope == "reusable"
            else None
        ),
        InterpretationChanges(
            name="confirmed scientific name",
            vocabulary="user-library",
            member_polyhedron_ids=("SOURCE-P1",),
            role_overrides=((42, "interstitial"),),
            bond_additions=(PeriodicBondChange(1, 2, (0, 0, 0), 1.5),),
        ),
        "2026-08-21T00:00:00Z",
        "2026-08-21T00:00:00Z",
    )


def test_reusable_overlay_maps_whole_domain_but_drops_site_specific_changes():
    document = _document()

    accept_preset(document, _preset(), domain_id="D1")
    resolved = resolve_interpretation(document, "D1")

    assert resolved.name == "confirmed scientific name"
    assert resolved.member_polyhedron_ids == ("P10", "P20", "P30")
    assert resolved.role_overrides == ()
    assert resolved.pending_bond_changes == ()
    assert resolved.provenance == "user preset"


def test_local_preset_requires_exact_document_identity():
    document = _document()

    with pytest.raises(ValueError, match="different structure snapshot"):
        accept_preset(document, _preset(scope="local", source="wrong"), domain_id="D1")


def test_manual_changes_take_precedence_and_removal_restores_automatic_result():
    document = _document()
    accept_preset(document, _preset(), domain_id="D1")
    set_manual_changes(
        document,
        "D1",
        InterpretationChanges(name="my interpretation", vocabulary="personal"),
    )

    manual = resolve_interpretation(document, "D1")
    assert manual.name == "my interpretation"
    assert manual.provenance == "manual"

    remove_overlay(document)
    automatic = resolve_interpretation(document, "D1")
    assert automatic.name == "automatic borate ring"
    assert automatic.vocabulary == "borate"
    assert automatic.provenance == "automatic"


def test_local_preset_retains_site_changes_as_pending_confirmation():
    document = _document()
    preset = _preset(scope="local", source="exact-document-sha")

    accept_preset(document, preset, domain_id="D1")
    resolved = resolve_interpretation(document, "D1")

    assert resolved.role_overrides == ((42, "interstitial"),)
    assert resolved.pending_bond_changes == preset.changes.bond_additions


def test_confirm_bond_changes_recomputes_then_clears_pending_changes():
    document = _document()
    document.structure = SimpleNamespace(sites=(object(), object(), object()))
    document.structural_analysis.settings = SimpleNamespace(
        bond_settings=SimpleNamespace(
            confirmed_additions=(),
            confirmed_removals=(),
        )
    )
    document.periodic_graph = "old graph"
    document.inorganic_topology = "old topology"
    document.descriptor_cache = {("old",): object()}
    document.comparison_cache = {("old",): object()}
    document.scene_cache = {("old",): object()}
    accept_preset(
        document,
        _preset(scope="local", source="exact-document-sha"),
        domain_id="D1",
    )
    captured = []

    def recompute(_document, additions, removals):
        captured.append((additions, removals))
        return "new analysis", "new hierarchy", "new graph", "new topology"

    confirm_bond_changes(document, recompute=recompute)

    assert captured == [(((1, 2, (0, 0, 0)),), ())]
    assert document.structural_analysis == "new analysis"
    assert document.hierarchy == "new hierarchy"
    assert document.periodic_graph == "new graph"
    assert document.inorganic_topology == "new topology"
    assert document.descriptor_cache == {}
    assert document.comparison_cache == {}
    assert document.scene_cache == {}


def test_failed_bond_recompute_keeps_previous_snapshot_and_pending_changes():
    document = _document()
    document.structure = SimpleNamespace(sites=(object(), object(), object()))
    accept_preset(
        document,
        _preset(scope="local", source="exact-document-sha"),
        domain_id="D1",
    )
    old_analysis = document.structural_analysis
    old_hierarchy = document.hierarchy

    with pytest.raises(RuntimeError, match="calculation failed"):
        confirm_bond_changes(
            document,
            recompute=lambda *_args: (_ for _ in ()).throw(RuntimeError("calculation failed")),
        )

    assert document.structural_analysis is old_analysis
    assert document.hierarchy is old_hierarchy
    assert resolve_interpretation(document, "D1").pending_bond_changes
