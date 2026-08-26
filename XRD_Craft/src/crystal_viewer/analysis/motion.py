from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class BlockMotion:
    rotation_degrees: float
    translation: float
    distortion_percent: float
    rmsd: float
    rotation_matrix: np.ndarray
    translation_vector: np.ndarray


def compare_block_coordinates(reference: np.ndarray, target: np.ndarray) -> BlockMotion:
    """Compare matched block atoms with the Kabsch rigid-body decomposition."""
    first = np.asarray(reference, dtype=float)
    second = np.asarray(target, dtype=float)
    if first.shape != second.shape or first.ndim != 2 or first.shape[1] != 3 or len(first) < 3:
        raise ValueError("Matched coordinate arrays must have shape (N, 3), N >= 3.")
    center_first = first.mean(axis=0)
    center_second = second.mean(axis=0)
    first_centered = first - center_first
    second_centered = second - center_second
    covariance = first_centered.T @ second_centered
    left, _singular, right_t = np.linalg.svd(covariance)
    correction = np.eye(3)
    correction[-1, -1] = np.sign(np.linalg.det(right_t.T @ left.T))
    rotation = right_t.T @ correction @ left.T
    # Row-vector convention: target ≈ reference @ rotation.T + translation.
    translation_vector = center_second - center_first @ rotation.T
    aligned = first_centered @ rotation.T
    residual = second_centered - aligned
    rmsd = float(np.sqrt(np.mean(np.sum(residual**2, axis=1))))
    reference_scale = float(np.sqrt(np.mean(np.sum(first_centered**2, axis=1))))
    distortion = 100.0 * rmsd / reference_scale if reference_scale else 0.0
    cosine = float(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0))
    return BlockMotion(
        rotation_degrees=float(np.degrees(np.arccos(cosine))),
        translation=float(np.linalg.norm(translation_vector)),
        distortion_percent=distortion,
        rmsd=rmsd,
        rotation_matrix=rotation,
        translation_vector=translation_vector,
    )
