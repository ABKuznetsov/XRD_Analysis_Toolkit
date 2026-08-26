from __future__ import annotations

import hashlib
import math
import colorsys
from types import MappingProxyType
from collections.abc import Iterable, Mapping

from crystal_viewer.analysis.morphology import Hkl


FORM_PALETTE = (
    "#2678c8",
    "#3aa879",
    "#8f5ac8",
    "#dd8730",
    "#cc5798",
    "#159fba",
    "#d49a22",
    "#6269cf",
    "#d65745",
    "#6f9940",
    "#9b6b43",
    "#427e91",
    "#e06b75",
    "#00a88f",
    "#b66bd4",
    "#6f8edb",
    "#c47a00",
    "#7cae3d",
    "#d04f78",
    "#008fbe",
    "#a67550",
    "#7672b8",
    "#be633c",
    "#4b9b67",
)

_SIMPLE_FORMS = {
    (0, 0, 1): FORM_PALETTE[0],  # {100}
    (0, 1, 1): FORM_PALETTE[1],  # {110}
    (1, 1, 1): FORM_PALETTE[2],  # {111}
}


def form_signature(hkl: Hkl) -> Hkl:
    """Return a scale/sign-independent signature used only for visual identity."""
    divisor = math.gcd(math.gcd(abs(hkl[0]), abs(hkl[1])), abs(hkl[2])) or 1
    return tuple(sorted(abs(value) // divisor for value in hkl))  # type: ignore[return-value]


def family_color(hkl: Hkl) -> str:
    """Return a stable color for a simple crystallographic form."""
    signature = form_signature(hkl)
    if signature in _SIMPLE_FORMS:
        return _SIMPLE_FORMS[signature]
    token = f"{signature[0]},{signature[1]},{signature[2]}".encode("ascii")
    index = int.from_bytes(hashlib.blake2s(token, digest_size=2).digest(), "big")
    return FORM_PALETTE[index % len(FORM_PALETTE)]


def _generated_color(index: int) -> str:
    hue = ((index * 137.507764) % 360.0) / 360.0
    lightness = 0.46 if index % 2 == 0 else 0.62
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, 0.68)
    return "#{:02x}{:02x}{:02x}".format(
        round(red * 255),
        round(green * 255),
        round(blue * 255),
    )


def allocate_family_colors(families: Iterable[Hkl]) -> Mapping[Hkl, str]:
    """Allocate a deterministic, collision-free colour within one document."""
    ordered = sorted(set(tuple(int(value) for value in family) for family in families))
    allocated: dict[Hkl, str] = {}
    used: set[str] = set()
    for index, family in enumerate(ordered):
        if index < len(FORM_PALETTE):
            color = FORM_PALETTE[index]
        else:
            generated_index = index - len(FORM_PALETTE)
            color = _generated_color(generated_index)
            while color in used:
                generated_index += len(ordered) + 1
                color = _generated_color(generated_index)
        allocated[family] = color
        used.add(color)
    return MappingProxyType(allocated)


def rgb_tuple(color: str) -> tuple[int, int, int]:
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


__all__ = [
    "FORM_PALETTE",
    "allocate_family_colors",
    "family_color",
    "form_signature",
    "rgb_tuple",
]
