from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Mapping

from crystal_viewer.analysis.morphology import Hkl
from crystal_viewer.analysis.morphology_geometry import MorphologyModel
from crystal_viewer.analysis.morphology_state import FORMAT_VERSION, MorphologyEditState
from crystal_viewer.analysis.surface_markings import SurfaceMarkingKind
from crystal_viewer.analysis.twin_state import twin_spec_to_dict


def _hkl_text(hkl: tuple[int, int, int]) -> str:
    return " ".join(str(value) for value in hkl)


def _origin(state: MorphologyEditState | None, hkl: Hkl) -> str:
    if state is None:
        return "BFDH"
    if any(item.user_added and item.hkl == hkl for item in state.overrides):
        return "user-added"
    if hkl in state.primary_families:
        return "primary 80%"
    return "additional BFDH"


def _law_text(state: MorphologyEditState | None) -> str:
    if state is None or state.twin is None:
        return ""
    law = state.twin.law
    if law.plane_hkl is not None:
        return f"reflection ({_hkl_text(law.plane_hkl)})"
    if law.axis_uvw is not None:
        return f"twofold [{_hkl_text(law.axis_uvw)}]"
    return "matrix U; h'=U h"


def export_morphology_csv(
    path: str | Path,
    model: MorphologyModel,
    *,
    reference_model: MorphologyModel | None = None,
    state: MorphologyEditState | None = None,
    color_by_family: Mapping[Hkl, str] | None = None,
    aggregate=None,
) -> None:
    reference = reference_model or model
    colors = color_by_family or {}
    fieldnames = (
        "hkl", "plane_hkl", "domain_id", "d_hkl_angstrom", "allowed_order",
        "d_effective_angstrom", "bfdh_rho0", "current_rho", "enabled",
        "reference_area_relative", "reference_fraction", "area_relative",
        "area_fraction", "current_fraction", "origin", "color", "state",
        "twin_kind", "twin_law", "twin_provenance", "composition_plane",
        "marking_kind", "marking_provenance", "method", "warning",
    )
    plane_by_family = {plane.family.hkl: plane for plane in model.planes}
    descriptors: list[tuple[str, Hkl, Hkl]] = []
    if aggregate is None:
        descriptors.extend(("", plane.family.hkl, plane.family.hkl) for plane in model.planes)
    else:
        descriptors.extend(
            (facet.domain_id, facet.family_hkl, facet.display_hkl)
            for facet in sorted(
                aggregate.external_facets,
                key=lambda item: (item.domain_id, item.family_hkl, item.display_hkl),
            )
        )
        manifested = {family for _domain, family, _plane in descriptors}
        descriptors.extend(
            ("", plane.family.hkl, plane.family.hkl)
            for plane in model.planes
            if plane.family.hkl not in manifested
        )
    twin = None if state is None else state.twin
    composition = "" if twin is None else _hkl_text(twin.resolved_composition_plane_hkl)
    warnings = list(model.warnings)
    if aggregate is not None:
        warnings.extend(aggregate.warnings)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for domain_id, family_hkl, plane_hkl in descriptors:
            plane = plane_by_family[family_hkl]
            markings = (
                () if state is None
                else tuple(item for item in state.markings if item.target_family == family_hkl)
            )
            for marking in markings or (None,):
                writer.writerow(
                    {
                        "hkl": _hkl_text(family_hkl),
                        "plane_hkl": _hkl_text(plane_hkl),
                        "domain_id": domain_id,
                        "d_hkl_angstrom": f"{plane.family.d_hkl:.12g}",
                        "allowed_order": plane.family.allowed_order,
                        "d_effective_angstrom": f"{plane.family.d_effective:.12g}",
                        "bfdh_rho0": f"{plane.rho0:.12g}",
                        "current_rho": f"{plane.rho:.12g}",
                        "enabled": str(plane.enabled).lower(),
                        "reference_area_relative": f"{reference.area_by_family.get(family_hkl, 0.0):.12g}",
                        "reference_fraction": f"{reference.fraction_by_family.get(family_hkl, 0.0):.12g}",
                        "area_relative": f"{model.area_by_family.get(family_hkl, 0.0):.12g}",
                        "area_fraction": f"{model.fraction_by_family.get(family_hkl, 0.0):.12g}",
                        "current_fraction": f"{model.fraction_by_family.get(family_hkl, 0.0):.12g}",
                        "origin": _origin(state, family_hkl),
                        "color": colors.get(family_hkl, ""),
                        "state": "manual" if plane.manual else "BFDH",
                        "twin_kind": "" if twin is None else twin.kind.value,
                        "twin_law": _law_text(state),
                        "twin_provenance": "" if twin is None else twin.law.provenance.value,
                        "composition_plane": composition,
                        "marking_kind": "" if marking is None else marking.kind.value,
                        "marking_provenance": (
                            "" if marking is None else
                            "manual" if marking.kind is SurfaceMarkingKind.INDUCTION else
                            "derived-polysynthetic"
                        ),
                        "method": "BFDH geometric morphology prediction",
                        "warning": "; ".join(
                            item for item in (plane.family.warning, *warnings) if item
                        ),
                    }
                )


def _state_payload(state: MorphologyEditState) -> dict:
    return {
        "max_index": state.max_index,
        "selection_policy": {
            "kind": state.selection_policy.kind,
            "target": state.selection_policy.target,
            "revision": state.selection_policy.revision,
        },
        "primary_families": [list(hkl) for hkl in state.primary_families],
        "primary_initialized": state.primary_initialized,
        "overrides": [
            {
                "hkl": list(item.hkl), "rho": item.rho,
                "enabled": item.enabled, "user_added": item.user_added,
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


def export_morphology_json(
    path: str | Path,
    model: MorphologyModel,
    *,
    state: MorphologyEditState | None = None,
    reference_model: MorphologyModel | None = None,
    color_by_family: Mapping[Hkl, str] | None = None,
    aggregate=None,
) -> None:
    resolved_state = state or MorphologyEditState()
    reference = reference_model or model
    payload = {
        "format_version": FORMAT_VERSION,
        "state": _state_payload(resolved_state),
        "calculation": {
            "method": "BFDH geometric morphology prediction",
            "thermodynamic_equilibrium": False,
            "relative_volume": model.volume,
            "reference_fraction_by_family": {
                _hkl_text(hkl): value
                for hkl, value in sorted(reference.fraction_by_family.items())
            },
            "current_fraction_by_family": {
                _hkl_text(hkl): value
                for hkl, value in sorted(model.fraction_by_family.items())
            },
            "colors": {
                _hkl_text(hkl): color
                for hkl, color in sorted((color_by_family or {}).items())
            },
            "orientations": (
                [] if aggregate is None else [
                    {
                        "domain_id": domain.domain_id,
                        "orientation_state": domain.orientation_state,
                        "matrix_cartesian": [list(row) for row in domain.orientation],
                        "translation_cartesian": list(domain.translation),
                    }
                    for domain in aggregate.domains
                ]
            ),
            "warnings": list(model.warnings) + (
                [] if aggregate is None else list(aggregate.warnings)
            ),
        },
    }
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


__all__ = ["export_morphology_csv", "export_morphology_json"]
