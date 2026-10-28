"""Experimental nested profile fit with conditional mass-normalized columns."""
from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

from xrd_finder.finder.gain_evidence import GainEvidence, evaluate_gain_evidence


@dataclass(frozen=True, slots=True)
class JointProfileResult:
    scales_after: np.ndarray
    model_before: np.ndarray
    model_after: np.ndarray
    target_reduction_percent: float
    rank_after: int


@dataclass(frozen=True, slots=True)
class JointMassResult:
    joint: JointProfileResult
    evidence: GainEvidence
    mass_percent: float | None
    gain_percent: float


def _readonly(value):
    result = np.array(value, dtype=float, copy=True)
    result.flags.writeable = False
    return result


def evaluate_mass_profiles(*, x, target, accepted_profiles, candidate_profile, weights,
                           peak_positions, selected_peak_positions, fwhm) -> JointMassResult:
    """Refit amplitudes only; physical columns must be native profile / (Mcell V).

    Gain is weighted squared-error reduction relative to target energy, not mass
    or identification probability. Existing reflection gates remain heuristic.
    """
    grid, y, fit_weights = (np.asarray(value, dtype=float) for value in (x, target, weights))
    if (grid.ndim != 1 or len(grid) < 5 or y.shape != grid.shape
            or fit_weights.shape != grid.shape or np.any(np.diff(grid) <= 0.)
            or not all(np.all(np.isfinite(v)) for v in (grid, y, fit_weights))
            or np.any(fit_weights < 0.) or not np.any(fit_weights > 0.)):
        raise ValueError('Joint profile inputs require a finite increasing grid and valid weights')
    profiles = [np.asarray(p, dtype=float) for p in [*accepted_profiles, candidate_profile]]
    if any(p.shape != grid.shape or not np.all(np.isfinite(p)) or np.any(p < 0.) for p in profiles):
        raise ValueError('Mass profiles must be finite, nonnegative and match the grid')
    dx = np.diff(grid)
    quadrature = np.r_[dx[0]/2., (dx[:-1]+dx[1:])/2., dx[-1]/2.]
    root_weights = np.sqrt(quadrature*fit_weights)
    design = np.column_stack(profiles)
    weighted = design*root_weights[:, None]
    norms = np.linalg.norm(weighted, axis=0)
    active = norms > 0.
    normalized = np.zeros_like(weighted)
    normalized[:, active] = weighted[:, active]/norms[active]
    target_scale = float(np.max(np.abs(y))) or 1.
    rhs = (y/target_scale)*root_weights

    def fit(count):
        indices = np.flatnonzero(active[:count])
        scales, rank = np.zeros(count), 0
        if len(indices):
            matrix = normalized[:, indices]
            amplitudes, _ = nnls(matrix, rhs)
            scales[indices] = amplitudes*target_scale/norms[indices]
            rank = int(np.linalg.matrix_rank(matrix))
        model = design[:, :count] @ scales
        difference = (y-model)*root_weights
        return scales, model, float(np.dot(difference, difference)), rank

    _, before, error_before, _ = fit(len(profiles)-1)
    scales, after, error_after, rank = fit(len(profiles))
    target_energy = float(np.dot(y*root_weights, y*root_weights))
    improvement = max(0., error_before-error_after)
    # Suppress only numerical roundoff, not weak physical contributions.
    if improvement <= np.finfo(float).eps*max(error_before, target_energy):
        improvement = 0.
    gain = 100.*improvement/target_energy if target_energy > 0. else 0.
    candidate_curve = design[:, -1]*scales[-1]
    positions = np.asarray(peak_positions, dtype=float)
    evidence = evaluate_gain_evidence(x=grid, target=y, model_before=before, model_after=after,
        candidate_curve=candidate_curve, peak_positions=positions,
        peak_amplitudes=np.interp(positions, grid, candidate_curve, left=0., right=0.),
        selected_peak_positions=np.asarray(selected_peak_positions, dtype=float),
        fwhm=fwhm, stage='direct')
    full_rank = rank == len(profiles)
    total = float(np.sum(scales))
    mass = 100.*float(scales[-1])/total if full_rank and total > 0. else None
    joint = JointProfileResult(_readonly(scales), _readonly(before), _readonly(after), gain, rank)
    return JointMassResult(joint, evidence, mass, gain if full_rank and evidence.accepted else 0.)
