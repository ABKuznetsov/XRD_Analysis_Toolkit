from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class PhaseWidthModel:
    median_sample_fwhm: float
    robust_spread: float
    line_count: int
    intercept: float | None = None
    slope: float | None = None

    @property
    def uses_angle_dependence(self) -> bool:
        return self.intercept is not None and self.slope is not None

    def predict_sample_fwhm(self, two_theta: float) -> float:
        if not self.uses_angle_dependence:
            return max(float(self.median_sample_fwhm), 0.0)
        theta = np.deg2rad(float(two_theta) * 0.5)
        cosine = max(float(np.cos(theta)), 0.08)
        width = (float(self.intercept) + float(self.slope) * float(np.sin(theta))) / cosine
        lower = max(float(self.median_sample_fwhm) * 0.35, 0.005)
        upper = max(float(self.median_sample_fwhm) * 3.0, lower)
        return float(np.clip(width, lower, upper))


def fit_phase_width_model(records: Iterable[object]) -> PhaseWidthModel | None:
    usable = []
    for record in records:
        sample_width = getattr(record, "fwhm_sample", None)
        if sample_width is None or bool(getattr(record, "instrument_limited", False)):
            continue
        width = float(sample_width)
        position = float(getattr(record, "two_theta", 0.0) or 0.0)
        fit_quality = float(getattr(record, "fit_quality", 0.0) or 0.0)
        asymmetry = float(getattr(record, "asymmetry", 0.0) or 0.0)
        if not np.isfinite(width) or width <= 0.0 or not np.isfinite(position):
            continue
        if fit_quality > 0.0 and fit_quality < 0.35:
            continue
        if asymmetry > 0.45:
            continue
        usable.append((position, width))
    if len(usable) < 2:
        return None

    positions = np.asarray([item[0] for item in usable], dtype=float)
    widths = np.asarray([item[1] for item in usable], dtype=float)
    median = float(np.nanmedian(widths))
    spread = max(1.4826 * float(np.nanmedian(np.abs(widths - median))), median * 0.08, 0.005)
    if len(widths) < 4 or float(np.ptp(positions)) < 12.0:
        return PhaseWidthModel(median, spread, len(widths))

    theta = np.deg2rad(positions * 0.5)
    design = np.column_stack([np.ones_like(theta), np.sin(theta)])
    dependent = widths * np.cos(theta)
    weights = np.ones_like(dependent)
    coefficients = None
    for _iteration in range(4):
        root = np.sqrt(np.clip(weights, 0.05, 1.0))
        coefficients, *_unused = np.linalg.lstsq(
            design * root[:, None],
            dependent * root,
            rcond=None,
        )
        predicted = design @ coefficients
        residual = dependent - predicted
        scale = max(1.4826 * float(np.nanmedian(np.abs(residual - np.nanmedian(residual)))), 1.0e-4)
        weights = np.minimum(1.0, (2.5 * scale) / np.maximum(np.abs(residual), 1.0e-12))
    if coefficients is None:
        return PhaseWidthModel(median, spread, len(widths))
    intercept = max(float(coefficients[0]), 0.0)
    slope = float(coefficients[1])
    model = PhaseWidthModel(median, spread, len(widths), intercept, slope)
    predictions = np.asarray([model.predict_sample_fwhm(value) for value in positions], dtype=float)
    model_error = float(np.nanmedian(np.abs(widths - predictions)))
    if not np.isfinite(model_error) or model_error > max(spread * 1.8, median * 0.35):
        return PhaseWidthModel(median, spread, len(widths))
    return model


def match_clean_phase_records(
    peaks: Sequence[object],
    records: Sequence[object],
    *,
    tolerance: float,
) -> list[object]:
    strong = sorted(
        (
            peak
            for peak in peaks
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
        ),
        key=lambda peak: float(getattr(peak, "two_theta", 0.0) or 0.0),
    )
    clean_positions = []
    isolation = max(float(tolerance) * 1.4, 0.28)
    for index, peak in enumerate(strong):
        position = float(getattr(peak, "two_theta", 0.0) or 0.0)
        left_gap = position - float(getattr(strong[index - 1], "two_theta", -1.0e9)) if index else float("inf")
        right_gap = float(getattr(strong[index + 1], "two_theta", 1.0e9)) - position if index + 1 < len(strong) else float("inf")
        if min(left_gap, right_gap) >= isolation:
            clean_positions.append(position)
    available = set(range(len(records)))
    matched = []
    for position in clean_positions:
        best = min(
            available,
            key=lambda index: abs(float(getattr(records[index], "two_theta", 0.0)) - position),
            default=None,
        )
        if best is None:
            continue
        if abs(float(getattr(records[best], "two_theta", 0.0)) - position) > float(tolerance):
            continue
        available.remove(best)
        matched.append(records[best])
    return matched


def width_difference_corroboration(observed_sample_fwhm: float, expected_sample_fwhm: float, spread: float) -> float:
    observed = max(float(observed_sample_fwhm), 1.0e-6)
    expected = max(float(expected_sample_fwhm), 1.0e-6)
    uncertainty = max(float(spread), expected * 0.12, 0.005)
    difference = abs(observed - expected)
    return float(np.clip((difference - uncertainty) / max(expected * 0.75, uncertainty * 2.0), 0.0, 1.0))


__all__ = [
    "PhaseWidthModel",
    "fit_phase_width_model",
    "match_clean_phase_records",
    "width_difference_corroboration",
]
