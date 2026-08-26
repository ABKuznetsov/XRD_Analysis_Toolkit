from __future__ import annotations

from dataclasses import replace

from crystal_viewer.knowledge.matching import best_preset_proposal
from crystal_viewer.knowledge.model import (
    InterpretationChanges,
    KnowledgePreset,
    MotifFingerprint,
)


def _fingerprint(
    *,
    element="B",
    geometry=(10000, 10000, 10000),
    topology="ring-topology",
    rank=0,
):
    nodes = tuple(
        (
            "node",
            3,
            ((element, 1_000_000),),
            (("O", 1_000_000),),
            geometry,
            100,
            200,
            (3,),
        )
        for _index in range(3)
    )
    edges = tuple(
        ("V|cn=3|rings=3", "V|cn=3|rings=3", "corner", (0, 0, 0), 1)
        for _index in range(3)
    )
    return MotifFingerprint(
        "periodic-domain-fingerprint-v1",
        rank,
        nodes,
        edges,
        topology,
    )


def _preset(identifier, fingerprint, name=None):
    return KnowledgePreset(
        1,
        identifier,
        "reusable",
        "source",
        "structural-analysis-v1",
        fingerprint,
        InterpretationChanges(name=name or identifier),
        "2026-08-21T00:00:00Z",
        "2026-08-21T00:00:00Z",
    )


def test_only_one_clear_best_match_is_returned():
    target = _fingerprint()
    strong = _preset("strong", target, "borate ring")
    weak = _preset(
        "weak",
        _fingerprint(element="Xe", geometry=(7000, 10000, 13000)),
    )

    proposal = best_preset_proposal(target, (weak, strong))

    assert proposal is not None
    assert proposal.preset_id == "strong"
    assert proposal.name == "borate ring"
    assert proposal.confidence == 1.0


def test_near_tied_matches_are_suppressed_instead_of_listing_alternatives():
    target = _fingerprint()
    first = _preset("first", target)
    second = _preset("second", target)

    assert best_preset_proposal(target, (first, second)) is None


def test_incompatible_periodic_topology_is_rejected_before_chemistry():
    target = _fingerprint(rank=2, topology="layer")
    incompatible = _preset("ring", _fingerprint(rank=0, topology="ring"))

    assert best_preset_proposal(target, (incompatible,)) is None


def test_chemically_compatible_substitution_can_reuse_the_same_topology():
    lithium = _fingerprint(element="Li")
    sodium_rule = _preset("alkali-motif", _fingerprint(element="Na"))

    proposal = best_preset_proposal(lithium, (sodium_rule,))

    assert proposal is not None
    assert proposal.confidence >= 0.85
    assert proposal.evidence.chemistry_score < 1.0
    assert proposal.evidence.chemistry_score > 0.5


def test_result_is_deterministic_under_preset_order_reversal():
    target = _fingerprint()
    strong = _preset("strong", target)
    weak = _preset("weak", _fingerprint(element="Xe"))

    first = best_preset_proposal(target, (strong, weak))
    second = best_preset_proposal(target, (weak, strong))

    assert first == second


def test_malformed_nonfinite_geometry_is_rejected_without_crashing():
    target = _fingerprint()
    malformed = _preset(
        "malformed",
        replace(_fingerprint(), nodes=(
            ("node", 3, (("B", 1_000_000),), (("O", 1_000_000),), (float("nan"),), 0, 0, ()),
        )),
    )

    assert best_preset_proposal(target, (malformed,)) is None
