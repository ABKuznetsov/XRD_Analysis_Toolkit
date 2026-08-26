from __future__ import annotations

from pathlib import Path
import json

import pytest

from crystal_viewer.analysis.morphology import build_bfdh_planes
from crystal_viewer.analysis.morphology_state import (
    MorphologyEditState,
    SelectionPolicy,
    apply_edit_state,
    initialize_primary_selection,
    load_morphology_state,
    save_morphology_state,
    source_identity,
)
from crystal_viewer.analysis.morphology_selection import select_primary_forms
from crystal_viewer.analysis.surface_markings import SurfaceMarking, SurfaceMarkingKind
from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec
from crystal_viewer.core.cif import load_cif

ROOT = Path(__file__).resolve().parents[1]


def _structure():
    return load_cif(ROOT / "tests" / "data" / "morphology" / "body_centered.cif")


def test_edit_state_changes_and_resets_one_complete_family() -> None:
    structure = _structure()
    base = build_bfdh_planes(structure, max_index=1)
    target = base[0]
    state = MorphologyEditState(max_index=1).with_distance(target.family.hkl, target.rho0 * 1.5)

    edited = apply_edit_state(structure, base, state)
    changed = next(plane for plane in edited if plane.family.hkl == target.family.hkl)

    assert changed.rho == pytest.approx(target.rho0 * 1.5)
    assert changed.manual
    assert changed.family.equivalents == target.family.equivalents
    assert base[0].rho == base[0].rho0
    assert apply_edit_state(structure, base, state.reset_family(target.family.hkl)) == base


def test_edit_state_validates_distance_and_tracks_enabled_state() -> None:
    state = MorphologyEditState(max_index=3)
    with pytest.raises(ValueError):
        state.with_distance((1, 0, 0), 0.0)
    with pytest.raises(ValueError):
        state.with_distance((1, 0, 0), float("inf"))

    changed = state.with_enabled((1, 0, 0), False)
    assert changed.override_for((1, 0, 0)).enabled is False


def test_user_added_family_is_calculated_with_symmetry_and_can_be_removed() -> None:
    structure = _structure()
    base = build_bfdh_planes(structure, max_index=1)
    state = MorphologyEditState(max_index=1).with_added_family((2, 1, 0))

    planes = apply_edit_state(structure, base, state)
    added = next(plane for plane in planes if (2, 1, 0) in plane.family.equivalents)

    assert added.manual
    assert added.rho > 0.0
    assert state.override_for((2, 1, 0)).user_added
    assert state.remove_added_family((2, 1, 0)).overrides == ()
    with pytest.raises(ValueError):
        MorphologyEditState().remove_added_family((1, 0, 0))


def test_symmetry_equivalent_user_additions_produce_one_family() -> None:
    structure = _structure()
    base = build_bfdh_planes(structure, max_index=1)
    state = (
        MorphologyEditState(max_index=1)
        .with_added_family((2, 1, 0))
        .with_added_family((-2, -1, 0))
    )

    planes = apply_edit_state(structure, base, state)
    matching = [plane for plane in planes if (2, 1, 0) in plane.family.equivalents]

    assert len(matching) == 1
    assert state.remove_added_family(
        (2, 1, 0), matching[0].family.equivalents
    ).overrides == ()


def test_morphology_json_round_trip_and_source_mismatch(tmp_path) -> None:
    structure = _structure()
    state = MorphologyEditState(max_index=4).with_distance((1, 0, 0), 1.75).with_enabled((0, 1, 0), False)
    path = tmp_path / "shape.morphology.json"

    save_morphology_state(path, structure, state)
    loaded = load_morphology_state(path, structure)

    assert loaded.compatible
    assert loaded.state == state
    other = load_cif(ROOT / "tests" / "data" / "morphology" / "primitive_cubic.cif")
    mismatch = load_morphology_state(path, other)
    assert not mismatch.compatible
    assert "source" in mismatch.message.lower()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["parameters"] == {
        "geometry_tolerance": 1e-8,
        "max_index": 4,
        "max_reflection_order": 12,
        "systematic_absence_tolerance": 1e-8,
    }
    assert isinstance(payload["warnings"], list)


def test_primary_selection_initializes_once_and_distance_edit_does_not_enable_extra_family() -> None:
    structure = _structure()
    base = build_bfdh_planes(structure, max_index=3)
    selection = select_primary_forms(structure.cell, base)
    state = initialize_primary_selection(MorphologyEditState(), selection)
    extra = next(
        plane.family.hkl
        for plane in base
        if plane.family.hkl not in selection.active_families
    )

    initial = apply_edit_state(structure, base, state)
    assert {plane.family.hkl for plane in initial if plane.enabled} == set(
        selection.active_families
    )

    distance_only = state.with_distance(extra, 2.0)
    edited = apply_edit_state(structure, base, distance_only)
    assert next(plane for plane in edited if plane.family.hkl == extra).enabled is False

    enabled = distance_only.with_enabled(extra, True)
    assert initialize_primary_selection(enabled, selection) == enabled
    assert next(
        plane for plane in apply_edit_state(structure, base, enabled)
        if plane.family.hkl == extra
    ).enabled is True
    reset = enabled.reset_primary()
    reset_extra = next(
        plane for plane in apply_edit_state(structure, base, reset)
        if plane.family.hkl == extra
    )
    assert reset_extra.enabled is False
    assert reset_extra.rho == pytest.approx(2.0)


def test_version_one_state_loads_without_automatic_primary_selection(tmp_path) -> None:
    structure = _structure()
    path = tmp_path / "legacy.morphology.json"
    payload = {
        "format_version": 1,
        "source_identity": source_identity(structure),
        "max_index": 3,
        "overrides": [
            {"hkl": [1, 0, 0], "rho": 1.25, "enabled": False, "user_added": False}
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_morphology_state(path, structure)

    assert loaded.state.selection_policy == SelectionPolicy()
    assert loaded.state.primary_initialized is False
    assert loaded.state.primary_families == ()
    assert loaded.state.override_for((1, 0, 0)).enabled is False
    assert loaded.state.markings == ()


def test_markings_are_unique_and_twin_striation_requires_polysynthetic_geometry() -> None:
    induction = SurfaceMarking((1, 0, 0), SurfaceMarkingKind.INDUCTION)
    twin_marking = SurfaceMarking((1, 0, 0), SurfaceMarkingKind.TWIN)
    with pytest.raises(ValueError, match="unique"):
        MorphologyEditState(markings=(induction, induction))
    with pytest.raises(ValueError, match="polysynthetic"):
        MorphologyEditState(markings=(twin_marking,))

    twin = TwinAggregateSpec(
        TwinAggregateKind.POLYSYNTHETIC,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
        composition_plane_hkl=(1, 0, 0),
    )
    assert MorphologyEditState(twin=twin, markings=(twin_marking,)).markings == (twin_marking,)


def test_marking_helpers_and_version_two_round_trip(tmp_path) -> None:
    structure = _structure()
    induction = SurfaceMarking((2, 1, 0), SurfaceMarkingKind.INDUCTION, 7, 2.25)
    state = MorphologyEditState().with_added_family((2, 1, 0)).with_marking(induction)
    path = tmp_path / "marking.morphology.json"

    save_morphology_state(path, structure, state)
    loaded = load_morphology_state(path, structure).state

    assert loaded == state
    assert loaded.remove_marking((2, 1, 0), SurfaceMarkingKind.INDUCTION).markings == ()
    assert state.remove_added_family((2, 1, 0)).markings == ()
