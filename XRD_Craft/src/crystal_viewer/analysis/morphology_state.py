from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

from crystal_viewer.analysis.morphology import (
    Hkl,
    MillerFamily,
    MorphologyPlane,
    equivalent_hkls,
    first_allowed_order,
    interplanar_spacing,
    reduce_hkl,
    resolve_symmetry_operations,
)
from crystal_viewer.core.model import CrystalStructure
from crystal_viewer.analysis.twin_state import (
    TwinAggregateSpec,
    twin_spec_from_dict,
    twin_spec_to_dict,
)
from crystal_viewer.analysis.surface_markings import SurfaceMarking, SurfaceMarkingKind

FORMAT_VERSION = 2


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    kind: str = "area_coverage"
    target: float = 0.80
    revision: int = 1

    def __post_init__(self) -> None:
        if self.kind != "area_coverage":
            raise ValueError("Unsupported morphology selection policy.")
        if not math.isfinite(float(self.target)) or not 0.0 < float(self.target) <= 1.0:
            raise ValueError("Selection-policy target must be finite and in (0, 1].")
        if int(self.revision) != 1:
            raise ValueError("Unsupported morphology selection-policy revision.")


@dataclass(frozen=True, slots=True)
class PlaneOverride:
    hkl: Hkl
    rho: float | None = None
    enabled: bool | None = None
    user_added: bool = False


@dataclass(frozen=True, slots=True)
class MorphologyEditState:
    max_index: int = 3
    overrides: tuple[PlaneOverride, ...] = ()
    selection_policy: SelectionPolicy = SelectionPolicy()
    primary_families: tuple[Hkl, ...] = ()
    primary_initialized: bool = False
    twin: TwinAggregateSpec | None = None
    markings: tuple[SurfaceMarking, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= int(self.max_index) <= 12:
            raise ValueError("max_index must be between 1 and 12.")
        if self.twin is not None and not isinstance(self.twin, TwinAggregateSpec):
            raise TypeError("Morphology twin must be a TwinAggregateSpec or None.")
        if any(not isinstance(item, SurfaceMarking) for item in self.markings):
            raise TypeError("Morphology markings must be SurfaceMarking values.")
        marking_keys = tuple((item.target_family, item.kind) for item in self.markings)
        if len(set(marking_keys)) != len(marking_keys):
            raise ValueError("Morphology markings must be unique by family and kind.")
        if any(item.kind is SurfaceMarkingKind.TWIN for item in self.markings) and (
            self.twin is None or self.twin.kind.value != "polysynthetic"
        ):
            raise ValueError("Twin striation requires a polysynthetic twin aggregate.")
        normalized = tuple(reduce_hkl(value) for value in self.primary_families)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Primary morphology families must be unique.")
        object.__setattr__(self, "primary_families", normalized)

    def override_for(self, hkl) -> PlaneOverride | None:
        target = reduce_hkl(hkl)
        return next((item for item in self.overrides if item.hkl == target), None)

    def _replace_override(self, override: PlaneOverride) -> MorphologyEditState:
        retained = [item for item in self.overrides if item.hkl != override.hkl]
        retained.append(override)
        return replace(self, overrides=tuple(sorted(retained, key=lambda item: item.hkl)))

    def with_distance(self, hkl, rho: float) -> MorphologyEditState:
        value = float(rho)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("Centre-to-plane distance must be finite and positive.")
        target = reduce_hkl(hkl)
        current = self.override_for(target) or PlaneOverride(target)
        return self._replace_override(replace(current, rho=value))

    def with_enabled(self, hkl, enabled: bool) -> MorphologyEditState:
        target = reduce_hkl(hkl)
        current = self.override_for(target) or PlaneOverride(target)
        return self._replace_override(replace(current, enabled=bool(enabled)))

    def reset_family(self, hkl) -> MorphologyEditState:
        target = reduce_hkl(hkl)
        return replace(self, overrides=tuple(item for item in self.overrides if item.hkl != target))

    def reset_all(self) -> MorphologyEditState:
        return replace(self, overrides=())

    def reset_primary(self) -> MorphologyEditState:
        retained: list[PlaneOverride] = []
        for item in self.overrides:
            if item.user_added:
                retained.append(replace(item, enabled=False))
            elif item.rho is not None:
                retained.append(replace(item, enabled=None))
        return replace(self, overrides=tuple(retained), primary_initialized=True)

    def with_added_family(self, hkl, rho: float | None = None) -> MorphologyEditState:
        target = reduce_hkl(hkl)
        if rho is not None and (not math.isfinite(float(rho)) or float(rho) <= 0.0):
            raise ValueError("Centre-to-plane distance must be finite and positive.")
        return self._replace_override(
            PlaneOverride(target, None if rho is None else float(rho), True, True)
        )

    def remove_added_family(self, hkl, equivalents=()) -> MorphologyEditState:
        target = reduce_hkl(hkl)
        targets = {target, *(reduce_hkl(value) for value in equivalents)}
        removable = {
            item.hkl for item in self.overrides if item.user_added and item.hkl in targets
        }
        if not removable:
            raise ValueError("Only a user-added family can be removed.")
        return replace(
            self,
            overrides=tuple(item for item in self.overrides if item.hkl not in removable),
            markings=tuple(item for item in self.markings if item.target_family not in targets),
        )

    def with_marking(self, marking: SurfaceMarking) -> MorphologyEditState:
        if not isinstance(marking, SurfaceMarking):
            raise TypeError("Morphology marking must be a SurfaceMarking.")
        retained = tuple(
            item for item in self.markings
            if (item.target_family, item.kind) != (marking.target_family, marking.kind)
        )
        return replace(self, markings=retained + (marking,))

    def remove_marking(self, hkl, kind: SurfaceMarkingKind) -> MorphologyEditState:
        target = reduce_hkl(hkl)
        marking_kind = SurfaceMarkingKind(kind)
        return replace(
            self,
            markings=tuple(
                item for item in self.markings
                if (item.target_family, item.kind) != (target, marking_kind)
            ),
        )


@dataclass(frozen=True, slots=True)
class LoadedMorphologyState:
    state: MorphologyEditState
    compatible: bool
    message: str = ""


def initialize_primary_selection(state: MorphologyEditState, selection) -> MorphologyEditState:
    if state.primary_initialized:
        return state
    return replace(
        state,
        selection_policy=SelectionPolicy(target=0.80),
        primary_families=tuple(selection.active_families),
        primary_initialized=True,
    )


def apply_edit_state(
    structure: CrystalStructure,
    base_planes: tuple[MorphologyPlane, ...],
    state: MorphologyEditState,
) -> tuple[MorphologyPlane, ...]:
    result: list[MorphologyPlane] = []
    consumed: set[Hkl] = set()
    for plane in base_planes:
        override = next(
            (
                item
                for item in state.overrides
                if item.hkl == plane.family.hkl or item.hkl in plane.family.equivalents
            ),
            None,
        )
        default_enabled = (
            plane.family.hkl in state.primary_families
            if state.primary_initialized
            else plane.enabled
        )
        if override is None:
            result.append(replace(plane, enabled=default_enabled))
            continue
        consumed.add(override.hkl)
        rho = plane.rho0 if override.rho is None else override.rho
        enabled = default_enabled if override.enabled is None else override.enabled
        result.append(
            replace(
                plane,
                rho=rho,
                enabled=enabled,
                manual=override.rho is not None or override.enabled is not None,
            )
        )
    if base_planes:
        reference_raw = 1.0 / base_planes[0].family.d_effective
        scale = reference_raw / base_planes[0].rho0
    else:
        scale = 1.0
    symmetry = resolve_symmetry_operations(structure)
    for override in state.overrides:
        if override.hkl in consumed or not override.user_added:
            continue
        equivalents = equivalent_hkls(override.hkl, symmetry.operations)
        equivalent_overrides = {
            item.hkl for item in state.overrides if item.user_added and item.hkl in equivalents
        }
        if consumed.intersection(equivalent_overrides):
            continue
        consumed.update(equivalent_overrides)
        representative = min(equivalents)
        order = first_allowed_order(representative, symmetry.operations)
        if order is None:
            raise ValueError(f"No allowed reflection order was found for {override.hkl}.")
        spacing = interplanar_spacing(structure.cell, representative)
        family = MillerFamily(
            representative,
            equivalents,
            spacing,
            order,
            spacing / order,
            symmetry.provenance,
            symmetry.warning,
        )
        rho0 = (1.0 / family.d_effective) / scale
        result.append(
            MorphologyPlane(
                family,
                rho0,
                rho0 if override.rho is None else override.rho,
                enabled=False if override.enabled is None else override.enabled,
                manual=True,
            )
        )
    result.sort(key=lambda plane: (plane.rho0, plane.family.hkl))
    return tuple(result)


def source_identity(structure: CrystalStructure) -> str:
    path = structure.source_path
    if path is not None and Path(path).is_file():
        payload = Path(path).read_bytes()
    else:
        payload = repr(
            (
                structure.cell,
                tuple(structure.asymmetric_sites),
                tuple(structure.symmetry_operations),
                structure.space_group,
            )
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def save_morphology_state(
    path: str | Path,
    structure: CrystalStructure,
    state: MorphologyEditState,
) -> None:
    payload = {
        "format_version": FORMAT_VERSION,
        "method": "BFDH geometric morphology prediction",
        "source_identity": source_identity(structure),
        "source_name": structure.name,
        "cell": {
            "a": structure.cell.a,
            "b": structure.cell.b,
            "c": structure.cell.c,
            "alpha": structure.cell.alpha,
            "beta": structure.cell.beta,
            "gamma": structure.cell.gamma,
        },
        "space_group": structure.space_group,
        "max_index": state.max_index,
        "selection_policy": {
            "kind": state.selection_policy.kind,
            "target": state.selection_policy.target,
            "revision": state.selection_policy.revision,
        },
        "primary_families": [list(hkl) for hkl in state.primary_families],
        "primary_initialized": state.primary_initialized,
        "parameters": {
            "geometry_tolerance": 1e-8,
            "max_index": state.max_index,
            "max_reflection_order": 12,
            "systematic_absence_tolerance": 1e-8,
        },
        "warnings": [
            warning
            for warning in (resolve_symmetry_operations(structure).warning,)
            if warning
        ],
        "overrides": [
            {
                "hkl": list(item.hkl),
                "rho": item.rho,
                "enabled": item.enabled,
                "user_added": item.user_added,
            }
            for item in state.overrides
        ],
        "twin": None if state.twin is None else twin_spec_to_dict(state.twin),
        "markings": [
            {
                "target_family": list(item.target_family),
                "kind": item.kind.value,
                "density": item.density,
                "line_width": item.line_width,
            }
            for item in state.markings
        ],
    }
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_morphology_state(
    path: str | Path,
    structure: CrystalStructure,
) -> LoadedMorphologyState:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    format_version = payload.get("format_version")
    if format_version not in (1, FORMAT_VERSION):
        raise ValueError("Unsupported morphology-state format version.")
    overrides = []
    for raw in payload.get("overrides", ()):
        rho = raw.get("rho")
        if rho is not None and (not math.isfinite(float(rho)) or float(rho) <= 0.0):
            raise ValueError("Saved morphology contains an invalid distance.")
        if format_version == 1:
            enabled = bool(raw.get("enabled", True))
        else:
            raw_enabled = raw.get("enabled")
            enabled = None if raw_enabled is None else bool(raw_enabled)
        overrides.append(
            PlaneOverride(
                reduce_hkl(raw["hkl"]),
                None if rho is None else float(rho),
                enabled,
                bool(raw.get("user_added", False)),
            )
        )
    if format_version == 1:
        policy = SelectionPolicy()
        primary_families: tuple[Hkl, ...] = ()
        primary_initialized = False
    else:
        raw_policy = payload.get("selection_policy", {})
        policy = SelectionPolicy(
            str(raw_policy.get("kind", "area_coverage")),
            float(raw_policy.get("target", 0.80)),
            int(raw_policy.get("revision", 1)),
        )
        primary_families = tuple(
            reduce_hkl(value) for value in payload.get("primary_families", ())
        )
        primary_initialized = bool(payload.get("primary_initialized", False))
    state = MorphologyEditState(
        max_index=int(payload.get("max_index", 3)),
        overrides=tuple(overrides),
        selection_policy=policy,
        primary_families=primary_families,
        primary_initialized=primary_initialized,
        twin=(
            None
            if format_version == 1 or payload.get("twin") is None
            else twin_spec_from_dict(payload["twin"])
        ),
        markings=(
            ()
            if format_version == 1
            else tuple(
                SurfaceMarking(
                    raw["target_family"],
                    SurfaceMarkingKind(raw["kind"]),
                    raw.get("density", 6),
                    raw.get("line_width", 1.5),
                )
                for raw in payload.get("markings", ())
            )
        ),
    )
    compatible = payload.get("source_identity") == source_identity(structure)
    message = "" if compatible else "Saved morphology source does not match the active CIF source."
    return LoadedMorphologyState(state, compatible, message)


__all__ = [
    "LoadedMorphologyState",
    "MorphologyEditState",
    "PlaneOverride",
    "SelectionPolicy",
    "apply_edit_state",
    "initialize_primary_selection",
    "load_morphology_state",
    "save_morphology_state",
    "source_identity",
]
