from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


_NUMERIC_RE = re.compile(
    r"^(?P<mantissa>[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"(?:\((?P<su>\d+)\))?(?:[eE](?P<exponent>[+-]?\d+))?$"
)


class MissingState(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class MeasuredValue:
    """A CIF numeric token with its reported standard uncertainty intact."""

    raw: str
    value: float | None
    su: float | None = None
    unit: str = ""
    source_name: str = ""
    state: MissingState = MissingState.PRESENT

    @property
    def state_token(self) -> str:
        return {
            MissingState.PRESENT: self.raw,
            MissingState.MISSING: ".",
            MissingState.UNKNOWN: "?",
            MissingState.ABSENT: "",
        }[self.state]

    def formatted(self) -> str:
        return self.raw if self.state is MissingState.PRESENT else self.state_token


def parse_cif_number(
    token: str | None,
    *,
    unit: str = "",
    source_name: str = "",
) -> MeasuredValue:
    """Parse one CIF number without discarding its raw token or ESD.

    CIF standard uncertainties are integers applying to the least-significant
    digits of the mantissa. For example, ``1.234(5)e2`` means ``123.4 ± 0.5``.
    The CIF missing (``.``), unknown (``?``), and absent states remain distinct.
    """

    if token is None:
        return MeasuredValue(
            raw="",
            value=None,
            unit=unit,
            source_name=source_name,
            state=MissingState.ABSENT,
        )

    raw = str(token).strip()
    if raw == ".":
        return MeasuredValue(
            raw=raw,
            value=None,
            unit=unit,
            source_name=source_name,
            state=MissingState.MISSING,
        )
    if raw == "?":
        return MeasuredValue(
            raw=raw,
            value=None,
            unit=unit,
            source_name=source_name,
            state=MissingState.UNKNOWN,
        )

    match = _NUMERIC_RE.fullmatch(raw)
    if match is None:
        raise ValueError(f"Not a valid CIF numeric token: {raw!r}")

    mantissa = match.group("mantissa")
    exponent = int(match.group("exponent") or 0)
    su_digits = match.group("su")
    decimal_places = len(mantissa.partition(".")[2]) if "." in mantissa else 0
    su = None
    if su_digits is not None:
        su = int(su_digits) * 10.0 ** (exponent - decimal_places)

    return MeasuredValue(
        raw=raw,
        value=float(f"{mantissa}e{exponent}"),
        su=su,
        unit=unit,
        source_name=source_name,
    )
