from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from xrd_finder.io.xy_loader import load_xy
from xrd_finder.services.preprocessing_service import estimate_background
from xrd_finder.services.rruff_service import RruffEntry, RruffService


@dataclass(slots=True)
class XrdTrainingRecord:
    source: str
    entry_id: str
    name: str
    formula: str
    x: np.ndarray
    raw_y: np.ndarray
    background_y: np.ndarray
    corrected_y: np.ndarray
    peak_mask: np.ndarray

    @property
    def background_mask(self) -> np.ndarray:
        return ~self.peak_mask


@dataclass(slots=True)
class TrainingDatasetOptions:
    x_min: float = 5.0
    x_max: float = 90.0
    points: int = 4096
    background_method: str = "auto"
    peak_half_width_deg: float = 0.08

    def grid(self) -> np.ndarray:
        return np.linspace(float(self.x_min), float(self.x_max), int(self.points), dtype=float)


class RruffTrainingDataset:
    def __init__(self, rruff: RruffService, options: TrainingDatasetOptions | None = None) -> None:
        self.rruff = rruff
        self.options = options or TrainingDatasetOptions()

    def records(self, limit: int | None = None) -> list[XrdTrainingRecord]:
        return list(self.iter_records(limit=limit))

    def iter_records(self, limit: int | None = None) -> Iterator[XrdTrainingRecord]:
        for entry in self.rruff.iter_entries(limit=limit):
            record = self.record_from_entry(entry)
            if record is not None:
                yield record

    def record_from_entry(self, entry: RruffEntry) -> XrdTrainingRecord | None:
        path = Path(entry.path)
        if not path.exists():
            return None
        try:
            data = load_xy(path)
        except Exception:
            return None
        return record_from_xy(
            data,
            source="RRUFF",
            entry_id=entry.rruff_id,
            name=entry.name,
            formula=entry.formula,
            options=self.options,
        )

    def _peak_mask(self, x: np.ndarray, corrected_y: np.ndarray) -> np.ndarray:
        return peak_mask_from_corrected_curve(x, corrected_y, self.options.peak_half_width_deg)


class FileTrainingDataset:
    def __init__(
        self,
        root: str | Path,
        options: TrainingDatasetOptions | None = None,
        suffixes: tuple[str, ...] = (".txt", ".xy", ".dat", ".csv", ".asc", ".raw", ".mdi"),
    ) -> None:
        self.root = Path(root)
        self.options = options or TrainingDatasetOptions()
        self.suffixes = tuple(suffix.lower() for suffix in suffixes)

    def iter_records(self, limit: int | None = None) -> Iterator[XrdTrainingRecord]:
        count = 0
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self.suffixes:
                continue
            record = self.record_from_path(path)
            if record is None:
                continue
            yield record
            count += 1
            if limit is not None and count >= limit:
                break

    def record_from_path(self, path: Path) -> XrdTrainingRecord | None:
        try:
            data = load_xy(path)
        except Exception:
            return None
        return record_from_xy(
            data,
            source="REAL",
            entry_id=str(path.relative_to(self.root)) if path.is_relative_to(self.root) else path.name,
            name=path.stem,
            formula="",
            options=self.options,
        )


def record_from_xy(
    data: np.ndarray,
    *,
    source: str,
    entry_id: str,
    name: str,
    formula: str,
    options: TrainingDatasetOptions,
) -> XrdTrainingRecord | None:
    if data.shape[1] < 2 or len(data) < 16:
        return None
    x = np.asarray(data[:, 0], dtype=float)
    y = np.asarray(data[:, 1], dtype=float)
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if len(x) < 16:
        return None
    grid = options.grid()
    mask = (grid >= float(np.nanmin(x))) & (grid <= float(np.nanmax(x)))
    if int(np.count_nonzero(mask)) < 16:
        return None
    raw_y = np.zeros_like(grid)
    raw_y[mask] = np.interp(grid[mask], x, y)
    background_y = np.zeros_like(grid)
    background_y[mask] = estimate_background(
        grid[mask],
        raw_y[mask],
        method=options.background_method,
    )
    corrected_y = np.maximum(raw_y - background_y, 0.0)
    peak_mask = peak_mask_from_corrected_curve(grid, corrected_y, options.peak_half_width_deg)
    return XrdTrainingRecord(
        source=source,
        entry_id=entry_id,
        name=name,
        formula=formula,
        x=grid,
        raw_y=raw_y,
        background_y=background_y,
        corrected_y=corrected_y,
        peak_mask=peak_mask,
    )


def peak_mask_from_corrected_curve(x: np.ndarray, corrected_y: np.ndarray, peak_half_width_deg: float) -> np.ndarray:
    peaks = _observed_peak_positions(x, corrected_y)
    mask = np.zeros_like(corrected_y, dtype=bool)
    if len(peaks) == 0:
        return mask
    half_width = max(float(peak_half_width_deg), 0.0)
    for peak_x in peaks:
        mask |= np.abs(x - float(peak_x)) <= half_width
    return mask


def _observed_peak_positions(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    if len(y) < 5 or float(np.nanmax(y)) <= 0:
        return np.array([], dtype=float)
    step = _median_step(x)
    noise = _robust_noise(y)
    p95 = float(np.nanpercentile(y, 95))
    prominence = max(noise * 4.0, p95 * 0.03, 1.0)
    indices, _properties = find_peaks(
        y,
        prominence=prominence,
        distance=max(3, int(round(0.11 / max(step, 1.0e-6)))),
        width=(1, max(5, int(round(1.4 / max(step, 1.0e-6))))),
    )
    if len(indices) > 120:
        keep = np.argsort(y[indices])[-120:]
        indices = indices[keep]
    return np.sort(np.asarray(x, dtype=float)[indices])


def _median_step(x: np.ndarray) -> float:
    diffs = np.diff(np.asarray(x, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    return float(np.nanmedian(diffs)) if len(diffs) else 0.03


def _robust_noise(y: np.ndarray) -> float:
    values = np.asarray(y, dtype=float)
    finite = values[np.isfinite(values)]
    if len(finite) < 3:
        return 1.0
    diffs = np.diff(finite)
    mad = float(np.nanmedian(np.abs(diffs - np.nanmedian(diffs)))) if len(diffs) else 0.0
    if mad > 0:
        return max(1.4826 * mad / np.sqrt(2.0), 1.0)
    mad = float(np.nanmedian(np.abs(finite - np.nanmedian(finite))))
    return max(1.4826 * mad, 1.0)
