from __future__ import annotations

import math
from pathlib import Path
import re
import shlex

from xrd_finder.services.calculated_pattern_service import HKLPeak


_D_TAGS = ("_pd_peak_d_spacing", "_refln_d_spacing")
_TWO_THETA_TAGS = ("_pd_peak_2theta", "_pd_peak_2theta_scan")
_INTENSITY_TAGS = (
    "_pd_peak_intensity",
    "_pd_peak_intensity_total",
    "_refln_intensity_meas",
    "_refln_f_squared_meas",
)


def extract_cif_powder_peaks(
    source: str | Path,
    *,
    wavelength: float,
    intensity_min: float = 0.5,
) -> list[HKLPeak]:
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8", errors="replace")
    else:
        source_text = str(source)
        if "\n" not in source_text and "\r" not in source_text and Path(source_text).exists():
            text = Path(source_text).read_text(encoding="utf-8", errors="replace")
        else:
            text = source_text
    loops = _cif_loops(text)
    measurement_wavelength = _scalar_float(text, "_diffrn_radiation_wavelength")
    if measurement_wavelength is None:
        measurement_wavelength = _scalar_float(text, "_cell_measurement_wavelength")
    measurement_wavelength = float(measurement_wavelength or wavelength)
    rows = []
    for tags, values in loops:
        tag_index = {tag.casefold(): index for index, tag in enumerate(tags)}
        d_tag = _first_present(tag_index, _D_TAGS)
        two_theta_tag = _first_present(tag_index, _TWO_THETA_TAGS)
        intensity_tag = _first_present(tag_index, _INTENSITY_TAGS)
        if intensity_tag is None or (d_tag is None and two_theta_tag is None):
            continue
        for row in values:
            intensity = _number(row[tag_index[intensity_tag]])
            d_spacing = _number(row[tag_index[d_tag]]) if d_tag is not None else None
            source_two_theta = _number(row[tag_index[two_theta_tag]]) if two_theta_tag is not None else None
            if d_spacing is None and source_two_theta is not None:
                d_spacing = _d_from_two_theta(source_two_theta, measurement_wavelength)
            if intensity is None or intensity <= 0.0 or d_spacing is None or d_spacing <= 0.0:
                continue
            two_theta = _two_theta_from_d(d_spacing, wavelength)
            if two_theta is None:
                continue
            rows.append(
                (
                    d_spacing,
                    two_theta,
                    intensity,
                    _integer_from_row(row, tag_index, "_refln_index_h"),
                    _integer_from_row(row, tag_index, "_refln_index_k"),
                    _integer_from_row(row, tag_index, "_refln_index_l"),
                )
            )
        if rows:
            break
    if not rows:
        return []
    maximum = max(item[2] for item in rows)
    peaks = []
    for d_spacing, two_theta, raw_intensity, h, k, l in rows:
        intensity = 100.0 * raw_intensity / max(maximum, 1.0e-12)
        if intensity < float(intensity_min):
            continue
        peaks.append(
            HKLPeak(
                h=h,
                k=k,
                l=l,
                d=float(d_spacing),
                two_theta=float(two_theta),
                intensity=float(intensity),
                multiplicity=1,
                f2=0.0,
                lp=1.0,
                raw_intensity=float(raw_intensity),
            )
        )
    return sorted(peaks, key=lambda peak: peak.two_theta)


def _cif_loops(text: str) -> list[tuple[list[str], list[list[str]]]]:
    lines = text.splitlines()
    loops = []
    index = 0
    while index < len(lines):
        if lines[index].strip().casefold() != "loop_":
            index += 1
            continue
        index += 1
        tags = []
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or stripped.startswith("#"):
                index += 1
                continue
            if not stripped.startswith("_"):
                break
            tags.append(stripped.split()[0])
            index += 1
        tokens = []
        while index < len(lines):
            stripped = lines[index].strip()
            lowered = stripped.casefold()
            if lowered == "loop_" or lowered.startswith("data_") or stripped.startswith("_"):
                break
            if stripped and not stripped.startswith("#"):
                try:
                    tokens.extend(shlex.split(stripped, comments=True, posix=True))
                except ValueError:
                    tokens.extend(stripped.split())
            index += 1
        if tags:
            width = len(tags)
            rows = [tokens[start : start + width] for start in range(0, len(tokens), width)]
            rows = [row for row in rows if len(row) == width]
            loops.append((tags, rows))
    return loops


def _first_present(index: dict[str, int], names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name.casefold() in index), None)


def _number(value: object) -> float | None:
    text = str(value or "").strip().strip("'").strip('"')
    text = re.sub(r"(?<=\d)\([0-9]+\)$", "", text)
    if not text or text in {".", "?"}:
        return None
    try:
        result = float(text.replace(",", "."))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _scalar_float(text: str, tag: str) -> float | None:
    match = re.search(rf"(?im)^\s*{re.escape(tag)}\s+([^\s#]+)", text)
    return _number(match.group(1)) if match else None


def _integer_from_row(row: list[str], index: dict[str, int], tag: str) -> int:
    position = index.get(tag.casefold())
    value = _number(row[position]) if position is not None else None
    return int(round(value)) if value is not None else 0


def _two_theta_from_d(d_spacing: float, wavelength: float) -> float | None:
    argument = float(wavelength) / (2.0 * float(d_spacing))
    if not 0.0 < argument < 1.0:
        return None
    return 2.0 * math.degrees(math.asin(argument))


def _d_from_two_theta(two_theta: float, wavelength: float) -> float | None:
    sine = math.sin(math.radians(float(two_theta) * 0.5))
    return float(wavelength) / (2.0 * sine) if sine > 0.0 else None


__all__ = ["extract_cif_powder_peaks"]
