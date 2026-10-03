from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class PairedInterval:
    mean_difference: float
    low: float
    high: float
    iterations: int


def paired_bootstrap(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    seed: int = 5036,
    iterations: int = 5000,
) -> PairedInterval:
    left = np.asarray(baseline, dtype=float)
    right = np.asarray(candidate, dtype=float)
    if left.shape != right.shape or left.ndim != 1 or not len(left):
        raise ValueError("Paired bootstrap inputs must be equally sized non-empty vectors.")
    differences = right - left
    rng = np.random.default_rng(int(seed))
    sample_count = max(1, int(iterations))
    means = np.empty(sample_count, dtype=float)
    for start in range(0, sample_count, 512):
        stop = min(start + 512, sample_count)
        indices = rng.integers(0, len(differences), size=(stop - start, len(differences)))
        means[start:stop] = differences[indices].mean(axis=1)
    return PairedInterval(
        mean_difference=float(np.mean(differences)),
        low=float(np.percentile(means, 2.5)),
        high=float(np.percentile(means, 97.5)),
        iterations=sample_count,
    )


__all__ = ["PairedInterval", "paired_bootstrap"]
