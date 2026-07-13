from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import numpy as np

from xrd_finder.services.xrd_signal_decomposition import XrdDecompositionSettings


DECOMPOSITION_PROFILES = (
    XrdDecompositionSettings(16.0, 5.0, 4.5, 6.0, 4.5),
    XrdDecompositionSettings(12.0, 7.0, 3.5, 5.0, 3.8),
    XrdDecompositionSettings(9.0, 8.0, 2.8, 4.0, 3.0),
    XrdDecompositionSettings(7.0, 10.0, 2.0, 3.2, 2.4),
)

FEATURE_NAMES = (
    "log_point_count",
    "step",
    "noise_ratio",
    "peak_density",
    "median_peak_width_deg",
    "broad_peak_fraction",
    "narrow_peak_fraction",
    "baseline_slope_ratio",
    "baseline_curvature_ratio",
    "amorphous_hump_ratio",
    "oversmooth_risk",
)

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "models" / "xrd_auto_selector_v1.npz"


def select_decomposition_settings(features, model_path: Path | None = None) -> tuple[XrdDecompositionSettings, float]:
    path = model_path or DEFAULT_MODEL_PATH
    if not path.exists():
        return DECOMPOSITION_PROFILES[1], 0.0
    try:
        with np.load(path, allow_pickle=False) as model:
            vector = feature_vector(features)
            mean = np.asarray(model["mean"], dtype=float)
            std = np.asarray(model["std"], dtype=float)
            weights = np.asarray(model["weights"], dtype=float)
            logits = np.append((vector - mean) / std, 1.0) @ weights
        probabilities = _softmax(logits)
        index = int(np.argmax(probabilities))
        confidence = float(probabilities[index])
        if index >= len(DECOMPOSITION_PROFILES) or confidence < 0.42:
            return DECOMPOSITION_PROFILES[1], confidence
        return DECOMPOSITION_PROFILES[index], confidence
    except Exception:
        return DECOMPOSITION_PROFILES[1], 0.0


def feature_vector(features) -> np.ndarray:
    return np.asarray(
        [
            np.log1p(float(features.point_count)),
            float(features.step),
            float(features.noise_ratio),
            float(features.peak_density),
            float(features.median_peak_width_deg),
            float(features.broad_peak_fraction),
            float(features.narrow_peak_fraction),
            float(features.baseline_slope_ratio),
            float(features.baseline_curvature_ratio),
            float(features.amorphous_hump_ratio),
            float(features.oversmooth_risk),
        ],
        dtype=float,
    )


def profile_matrix() -> np.ndarray:
    return np.asarray(
        [[float(getattr(profile, field.name)) for field in fields(profile)] for profile in DECOMPOSITION_PROFILES],
        dtype=float,
    )


def _softmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    shifted = values - float(np.max(values))
    exponent = np.exp(np.clip(shifted, -40.0, 40.0))
    return exponent / max(float(np.sum(exponent)), 1.0e-12)
