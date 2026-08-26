from __future__ import annotations

import json

import pytest

from crystal_viewer.analysis.morphology_state import (
    MorphologyEditState,
    load_morphology_state,
    save_morphology_state,
    source_identity,
)
from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode, TwinProvenance
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec


def _reflection() -> TwinLaw:
    return TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(2, 0, 0))


@pytest.mark.parametrize(
    "changes",
    (
        {"composition_plane_hkl": (0, 0, 0)},
        {"composition_offset": float("inf")},
        {"second_translation": (0.0, float("nan"), 0.0)},
        {"second_translation": (0.0, 0.0)},
        {"lamella_count": 1},
        {"lamella_count": 2.5},
        {"lamella_ratio": 0.0},
        {"lamella_ratio": 1.0},
    ),
)
def test_twin_aggregate_rejects_invalid_geometry(changes) -> None:
    values = {
        "kind": TwinAggregateKind.POLYSYNTHETIC,
        "law": _reflection(),
        "composition_plane_hkl": (1, 1, 0),
        "composition_offset": 0.0,
        "second_translation": (0.0, 0.0, 0.0),
        "lamella_count": 8,
        "lamella_ratio": 0.5,
    }
    values.update(changes)

    with pytest.raises((TypeError, ValueError)):
        TwinAggregateSpec(**values)


def test_contact_can_explicitly_use_reflection_k1_as_composition_plane() -> None:
    spec = TwinAggregateSpec(TwinAggregateKind.CONTACT, _reflection())

    assert spec.composition_plane_hkl is None
    assert spec.resolved_composition_plane_hkl == (1, 0, 0)


def test_morphology_state_accepts_only_a_validated_twin_spec() -> None:
    with pytest.raises(TypeError, match="TwinAggregateSpec"):
        MorphologyEditState(twin="contact")


def test_missing_composition_plane_requires_contact_reflection_k1() -> None:
    with pytest.raises(ValueError, match="composition plane"):
        TwinAggregateSpec(
            TwinAggregateKind.CONTACT,
            TwinLaw(TwinLawMode.TWOFOLD, axis_uvw=(0, 0, 1)),
        )
    with pytest.raises(ValueError, match="composition plane"):
        TwinAggregateSpec(TwinAggregateKind.POLYSYNTHETIC, _reflection())


@pytest.mark.parametrize(
    ("kind", "law"),
    (
        (
            TwinAggregateKind.CONTACT,
            TwinLaw(
                TwinLawMode.REFLECTION,
                plane_hkl=(-2, 1, 0),
                provenance=TwinProvenance.CIF,
            ),
        ),
        (
            TwinAggregateKind.PENETRATION,
            TwinLaw(TwinLawMode.TWOFOLD, axis_uvw=(-1, 2, 3)),
        ),
        (
            TwinAggregateKind.POLYSYNTHETIC,
            TwinLaw(
                TwinLawMode.MATRIX,
                reciprocal_matrix=((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            ),
        ),
    ),
)
def test_every_twin_kind_and_law_round_trips_exactly(
    tmp_path,
    body_centered_document,
    kind,
    law,
) -> None:
    structure = body_centered_document.structure
    spec = TwinAggregateSpec(
        kind,
        law,
        composition_plane_hkl=(-2, 2, 0),
        composition_offset=-0.125,
        second_translation=(0.5, -1.25, 2.0),
        lamella_count=6,
        lamella_ratio=0.375,
    )
    state = MorphologyEditState(twin=spec)
    path = tmp_path / f"{kind.value}-{law.mode.value}.morphology.json"

    save_morphology_state(path, structure, state)
    loaded = load_morphology_state(path, structure)

    assert loaded.state == state
    assert loaded.state.twin == spec
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["twin"]["law"]["mode"] == law.mode.value
    assert payload["twin"]["law"]["provenance"] == law.provenance.value
    assert payload["twin"]["composition_plane_hkl"] == [-1, 1, 0]
    if law.reciprocal_matrix is not None:
        assert payload["twin"]["law"]["reciprocal_matrix"] == [
            list(row) for row in law.reciprocal_matrix
        ]


def test_version_one_loads_without_a_twin(tmp_path, body_centered_document) -> None:
    structure = body_centered_document.structure
    path = tmp_path / "legacy.morphology.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "source_identity": source_identity(structure),
                "max_index": 3,
                "overrides": [],
            }
        ),
        encoding="utf-8",
    )

    assert load_morphology_state(path, structure).state.twin is None


@pytest.mark.parametrize(
    "twin_patch",
    (
        {"kind": "unknown"},
        {"law": {"mode": "unknown"}},
        {"law": {"mode": "matrix", "reciprocal_matrix": [[1.0, 0.0], [0.0, 1.0]]}},
        {"law": {"mode": "matrix", "reciprocal_matrix": [[1.0, 0.0, 0.0], [0.0, float("inf"), 0.0], [0.0, 0.0, 1.0]]}},
    ),
)
def test_malformed_saved_twin_is_rejected(
    tmp_path,
    body_centered_document,
    twin_patch,
) -> None:
    structure = body_centered_document.structure
    path = tmp_path / "bad.morphology.json"
    twin = {
        "kind": "contact",
        "law": {"mode": "reflection", "plane_hkl": [1, 0, 0], "provenance": "manual"},
        "composition_plane_hkl": None,
        "composition_offset": 0.0,
        "second_translation": [0.0, 0.0, 0.0],
        "lamella_count": 8,
        "lamella_ratio": 0.5,
    }
    for key, value in twin_patch.items():
        twin[key] = value
    path.write_text(
        json.dumps(
            {
                "format_version": 2,
                "source_identity": source_identity(structure),
                "max_index": 3,
                "twin": twin,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError)):
        load_morphology_state(path, structure)
