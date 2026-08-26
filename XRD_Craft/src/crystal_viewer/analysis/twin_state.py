from __future__ import annotations

import math
import operator
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from crystal_viewer.analysis.morphology import Hkl, reduce_hkl
from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode, TwinProvenance


class TwinAggregateKind(str, Enum):
    CONTACT = "contact"
    PENETRATION = "penetration"
    POLYSYNTHETIC = "polysynthetic"


@dataclass(frozen=True, slots=True)
class TwinAggregateSpec:
    kind: TwinAggregateKind
    law: TwinLaw
    composition_plane_hkl: Hkl | None = None
    composition_offset: float = 0.0
    second_translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    lamella_count: int = 8
    lamella_ratio: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", TwinAggregateKind(self.kind))
        if not isinstance(self.law, TwinLaw):
            raise TypeError("Twin aggregate law must be a TwinLaw.")

        if self.composition_plane_hkl is not None:
            object.__setattr__(
                self,
                "composition_plane_hkl",
                reduce_hkl(self.composition_plane_hkl),
            )
        elif not (
            self.kind is TwinAggregateKind.CONTACT
            and self.law.mode is TwinLawMode.REFLECTION
            and self.law.plane_hkl is not None
        ):
            raise ValueError("A physical composition plane is required for this twin aggregate.")

        offset = float(self.composition_offset)
        if not math.isfinite(offset):
            raise ValueError("Composition-plane offset must be finite.")
        object.__setattr__(self, "composition_offset", offset)

        try:
            translation = tuple(float(value) for value in self.second_translation)
        except (TypeError, ValueError) as error:
            raise ValueError("Second-domain translation must contain three finite values.") from error
        if len(translation) != 3 or not all(math.isfinite(value) for value in translation):
            raise ValueError("Second-domain translation must contain three finite values.")
        object.__setattr__(self, "second_translation", translation)

        if isinstance(self.lamella_count, bool):
            raise ValueError("Lamella count must be an integer of at least two.")
        try:
            count = operator.index(self.lamella_count)
        except TypeError as error:
            raise ValueError("Lamella count must be an integer of at least two.") from error
        if count < 2:
            raise ValueError("Lamella count must be an integer of at least two.")
        object.__setattr__(self, "lamella_count", count)

        ratio = float(self.lamella_ratio)
        if not math.isfinite(ratio) or not 0.0 < ratio < 1.0:
            raise ValueError("Lamella ratio must be finite and strictly between zero and one.")
        object.__setattr__(self, "lamella_ratio", ratio)

    @property
    def resolved_composition_plane_hkl(self) -> Hkl:
        if self.composition_plane_hkl is not None:
            return self.composition_plane_hkl
        if self.law.mode is TwinLawMode.REFLECTION and self.law.plane_hkl is not None:
            return self.law.plane_hkl
        raise ValueError("A physical composition plane is not defined.")


def twin_spec_to_dict(spec: TwinAggregateSpec) -> dict[str, Any]:
    law = spec.law
    return {
        "kind": spec.kind.value,
        "law": {
            "mode": law.mode.value,
            "plane_hkl": None if law.plane_hkl is None else list(law.plane_hkl),
            "axis_uvw": None if law.axis_uvw is None else list(law.axis_uvw),
            "reciprocal_matrix": (
                None
                if law.reciprocal_matrix is None
                else [list(row) for row in law.reciprocal_matrix]
            ),
            "provenance": law.provenance.value,
        },
        "composition_plane_hkl": (
            None
            if spec.composition_plane_hkl is None
            else list(spec.composition_plane_hkl)
        ),
        "composition_offset": spec.composition_offset,
        "second_translation": list(spec.second_translation),
        "lamella_count": spec.lamella_count,
        "lamella_ratio": spec.lamella_ratio,
    }


def twin_spec_from_dict(raw: Mapping[str, Any]) -> TwinAggregateSpec:
    if not isinstance(raw, Mapping):
        raise TypeError("Saved twin aggregate must be an object.")
    law_raw = raw.get("law")
    if not isinstance(law_raw, Mapping):
        raise TypeError("Saved twin law must be an object.")
    mode = TwinLawMode(law_raw.get("mode"))
    law = TwinLaw(
        mode,
        plane_hkl=law_raw.get("plane_hkl"),
        axis_uvw=law_raw.get("axis_uvw"),
        reciprocal_matrix=law_raw.get("reciprocal_matrix"),
        provenance=TwinProvenance(law_raw.get("provenance", TwinProvenance.MANUAL.value)),
    )
    return TwinAggregateSpec(
        TwinAggregateKind(raw.get("kind")),
        law,
        composition_plane_hkl=raw.get("composition_plane_hkl"),
        composition_offset=raw.get("composition_offset", 0.0),
        second_translation=raw.get("second_translation", (0.0, 0.0, 0.0)),
        lamella_count=raw.get("lamella_count", 8),
        lamella_ratio=raw.get("lamella_ratio", 0.5),
    )


__all__ = [
    "TwinAggregateKind",
    "TwinAggregateSpec",
    "twin_spec_from_dict",
    "twin_spec_to_dict",
]
