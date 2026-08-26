from __future__ import annotations

import json

import pytest

from crystal_viewer.knowledge.model import (
    InterpretationChanges,
    KnowledgePreset,
    MotifFingerprint,
    PeriodicBondChange,
)
from crystal_viewer.knowledge.store import KnowledgeStore, PresetConflictError


def _preset(*, preset_id: str = "preset-ring", scope: str = "reusable") -> KnowledgePreset:
    fingerprint = (
        MotifFingerprint(
            algorithm="periodic-domain-fingerprint-v1",
            periodic_rank=0,
            nodes=(("n0", ("B",), 3), ("n1", ("B",), 3), ("n2", ("B",), 3)),
            edges=(("n0", "n1", "corner", (0, 0, 0)),),
        )
        if scope == "reusable"
        else None
    )
    return KnowledgePreset(
        schema_version=1,
        id=preset_id,
        scope=scope,
        source_identity="a" * 64,
        analysis_method="structural-analysis-v1",
        fingerprint=fingerprint,
        changes=InterpretationChanges(
            name="трёхчленное кольцо B₃O₆",
            vocabulary="borate",
            member_polyhedron_ids=("P1", "P2", "P3"),
            role_overrides=((7, "structural"),),
            bond_additions=(PeriodicBondChange(7, 8, (1, 0, 0), 1.476),),
        ),
        created_at="2026-08-21T00:00:00Z",
        modified_at="2026-08-21T00:00:00Z",
        note="confirmed from diffraction refinement",
    )


def test_store_round_trip_is_atomic_and_contains_no_source_path(tmp_path):
    store = KnowledgeStore(tmp_path / "Sci" / "craft" / "presets")
    preset = _preset()

    store.save(preset)
    loaded, warnings = store.load_all()

    assert loaded == (preset,)
    assert warnings == ()
    target = store.root / "reusable" / "preset-ring.json"
    payload = target.read_text(encoding="utf-8")
    assert str(tmp_path) not in payload
    assert not tuple(target.parent.glob("*.tmp"))
    assert json.loads(payload)["changes"]["name"] == "трёхчленное кольцо B₃O₆"


def test_local_and_reusable_presets_are_kept_in_separate_directories(tmp_path):
    store = KnowledgeStore(tmp_path / "presets")

    store.save(_preset(preset_id="local-one", scope="local"))
    store.save(_preset(preset_id="shared-one", scope="reusable"))

    assert (store.root / "local" / "local-one.json").is_file()
    assert (store.root / "reusable" / "shared-one.json").is_file()


def test_corrupt_and_unsupported_presets_are_skipped_individually(tmp_path):
    store = KnowledgeStore(tmp_path / "presets")
    store.save(_preset())
    local = store.root / "local"
    local.mkdir(parents=True, exist_ok=True)
    (local / "broken.json").write_text("{", encoding="utf-8")
    (local / "future.json").write_text(
        json.dumps({"schema_version": 999, "id": "future"}), encoding="utf-8"
    )

    loaded, warnings = store.load_all()

    assert loaded == (_preset(),)
    assert {warning.code for warning in warnings} == {
        "invalid-preset",
        "unsupported-schema",
    }
    assert all(warning.path.name in {"broken.json", "future.json"} for warning in warnings)


def test_export_import_round_trip_and_conflict_are_safe(tmp_path):
    source = KnowledgeStore(tmp_path / "source" / "presets")
    target = KnowledgeStore(tmp_path / "target" / "presets")
    preset = _preset()
    source.save(preset)

    bundle = source.export_preset(preset.id, tmp_path / "ring.cbpreset")
    imported = target.import_preset(bundle)

    assert imported == preset
    with pytest.raises(PresetConflictError):
        target.import_preset(bundle)


def test_delete_removes_only_requested_preset(tmp_path):
    store = KnowledgeStore(tmp_path / "presets")
    store.save(_preset(preset_id="first"))
    store.save(_preset(preset_id="second"))

    assert store.delete("first") is True
    loaded, warnings = store.load_all()

    assert warnings == ()
    assert tuple(item.id for item in loaded) == ("second",)
    assert store.delete("missing") is False
