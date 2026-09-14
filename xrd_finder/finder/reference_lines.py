from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math


def _float_value(record: Mapping[str, object], key: str, default: float = 0.0) -> float:
    try:
        return float(record.get(key, default) or default)
    except (TypeError, ValueError):
        return float(default)


def _int_value(record: Mapping[str, object], key: str, default: int = 0) -> int:
    try:
        return int(record.get(key, default) or default)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True, slots=True)
class ReferenceLine:
    d: float
    two_theta: float
    intensity: float
    normalized_intensity: float
    raw_intensity: float
    h: int = 0
    k: int = 0
    l: int = 0
    multiplicity: int = 1

    @property
    def hkl(self) -> tuple[int, int, int]:
        return (self.h, self.k, self.l)


@dataclass(frozen=True, slots=True)
class ReferenceLineSet:
    source: str
    entry_id: str
    derived_version: int
    provenance: str
    lines: tuple[ReferenceLine, ...]

    @classmethod
    def from_records(
        cls,
        *,
        source: str,
        entry_id: str,
        derived_version: int,
        provenance: str,
        records: Iterable[Mapping[str, object]],
    ) -> ReferenceLineSet:
        lines = []
        for record in records:
            d = _float_value(record, "d")
            two_theta = _float_value(record, "two_theta")
            intensity = max(_float_value(record, "intensity"), 0.0)
            if not (math.isfinite(d) and d > 0.0 and math.isfinite(two_theta)):
                continue
            lines.append(
                ReferenceLine(
                    d=d,
                    two_theta=two_theta,
                    intensity=intensity,
                    normalized_intensity=max(_float_value(record, "norm_intensity"), 0.0),
                    raw_intensity=max(_float_value(record, "raw_intensity"), 0.0),
                    h=_int_value(record, "h"),
                    k=_int_value(record, "k"),
                    l=_int_value(record, "l"),
                    multiplicity=max(_int_value(record, "multiplicity", 1), 1),
                )
            )
        lines.sort(key=lambda line: (line.two_theta, line.h, line.k, line.l))
        return cls(
            source=str(source or "").upper(),
            entry_id=str(entry_id or ""),
            derived_version=int(derived_version),
            provenance=str(provenance or ""),
            lines=tuple(lines),
        )

    @property
    def fingerprint(self) -> tuple[object, ...]:
        return (
            self.source,
            self.entry_id,
            self.derived_version,
            self.provenance,
            tuple(
                (
                    round(line.d, 7),
                    round(line.two_theta, 5),
                    round(line.intensity, 4),
                    round(line.normalized_intensity, 6),
                    round(line.raw_intensity, 4),
                    line.h,
                    line.k,
                    line.l,
                    line.multiplicity,
                )
                for line in self.lines
            ),
        )
