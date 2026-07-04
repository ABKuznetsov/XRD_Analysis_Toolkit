from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Layer:
    name: str
    visible: bool = True
    color: str = "#2f6fed"
    opacity: float = 1.0
