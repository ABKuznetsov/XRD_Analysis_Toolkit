"""Portable, validated calculation results; project files contain JSON only."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import hashlib
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path

import numpy as np

from xrd_finder.finder.models import (
    FinderCandidateFailure, FinderCandidateResult, FinderResult,
    ObservedPeak, PeakAssignment, PeakStatus,
)


RESULT_FORMAT_VERSION = 1
# Preserve the existing signature namespace across application-only releases.
# Scientific changes are guarded by CALCULATION_REVISION and dependency versions.
CALCULATION_CACHE_EPOCH = '1.7.2'
# Bump when changing the scientific calculation without an application release.
CALCULATION_REVISION = '2026-11-20-independent-position-lines-4'


@lru_cache(maxsize=256)
def _file_hash(path: str, modified: int, changed: int, size: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cif_content_signature(path) -> str | None:
    """Content, rather than a machine-specific path or XPFF extraction time."""
    if path is None:
        return None
    try:
        local = Path(path)
        stat = local.stat()
        return _file_hash(str(local.resolve()), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    except OSError:
        return None


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


@lru_cache(maxsize=1)
def _engine_identity() -> tuple:
    def dependency_version(name):
        try:
            return version(name)
        except PackageNotFoundError:
            # Frozen packages may omit dist-info while exposing __version__.
            return str(getattr(import_module(name), '__version__', 'unavailable'))
    return (CALCULATION_CACHE_EPOCH, CALCULATION_REVISION,
            tuple((name, dependency_version(name)) for name in ('cristma', 'numpy', 'scipy', 'pybaselines')))


def make_result_record(result: FinderResult, portable_key: tuple) -> dict:
    payload = asdict(result)
    return {'format': RESULT_FORMAT_VERSION,
            'signature': _digest((_engine_identity(), portable_key)),
            'result_sha256': _digest(payload), 'result': payload}


def crop_saved_result(result: FinderResult, pattern_x) -> FinderResult | None:
    """Restrict a validated saved fit to an exact subset of its sampled grid.

    No background, cell or profile is fitted again. The caller must validate
    the complete former input signature before migrating a range-only change.
    Never interpolate, extrapolate or alter the original saved result.
    """
    old_x = np.asarray(result.pattern_x, dtype=float)
    x = np.asarray(pattern_x, dtype=float)
    if len(x) < 2 or not np.all(np.isfinite(x)) or not np.all(np.diff(x) > 0.):
        return None
    indices = np.searchsorted(old_x, x)
    if np.any(indices >= len(old_x)) or not np.array_equal(old_x[indices], x):
        return None
    for candidate in result.candidates:
        if candidate.two_theta and not np.array_equal(candidate.two_theta, old_x):
            return None
    cropped = deepcopy(result)
    for name in ('pattern_x', 'pattern_y', 'background', 'calculated_total'):
        setattr(cropped, name, np.asarray(getattr(result, name))[indices].tolist())
    low, high = x[0], x[-1]
    cropped.observed_peaks = [peak for peak in cropped.observed_peaks if low <= peak.two_theta <= high]
    for candidate in cropped.candidates:
        for name in ('two_theta', 'profile', 'mass_profile'):
            values = getattr(candidate, name)
            if values:
                setattr(candidate, name, np.asarray(values)[indices].tolist())
        count = len(candidate.peak_two_theta)
        keep = [i for i, angle in enumerate(candidate.peak_two_theta) if low <= angle <= high]
        evidence_changed = (len(keep) != count
                            or len(cropped.observed_peaks) != len(result.observed_peaks))
        for name in ('peak_two_theta', 'peak_reference_two_theta', 'peak_intensity', 'peak_h', 'peak_k', 'peak_l'):
            values = getattr(candidate, name)
            if values:
                if len(values) != count:
                    return None
                setattr(candidate, name, [values[i] for i in keep])
        if evidence_changed:
            # Update only descriptive line counts using existing peaks; no
            # detection or scientific fit is launched for the retained trace.
            from xrd_finder.finder.matching import search_match_result
            from xrd_finder.services.calculated_pattern_service import HKLPeak
            if any(len(getattr(candidate, name)) != len(keep)
                   for name in ('peak_intensity', 'peak_h', 'peak_k', 'peak_l')):
                return None
            peaks = [HKLPeak(h,k,l,0.,angle,intensity) for angle,intensity,h,k,l in zip(
                candidate.peak_two_theta, candidate.peak_intensity,
                candidate.peak_h, candidate.peak_k, candidate.peak_l, strict=True)]
            matched = search_match_result(peaks, [peak.two_theta for peak in cropped.observed_peaks])
            for name in ('score', 'status', 'matched_peaks', 'total_peaks', 'mean_delta_two_theta'):
                setattr(candidate, name, getattr(matched, name))
            candidate.matched_reference_two_theta = [item.reference_two_theta for item in matched.matches]
            candidate.matched_observed_two_theta = [item.observed_two_theta for item in matched.matches]
            candidate.matched_delta_two_theta = [item.delta_two_theta for item in matched.matches]
    return cropped


def restore_result(record, portable_key: tuple) -> FinderResult | None:
    """Reject stale/incomplete payloads; never trust a saved Quant independently."""
    if not isinstance(record, dict) or record.get('format') != RESULT_FORMAT_VERSION:
        return None
    try:
        payload = record['result']
        if not isinstance(payload, dict) or not isinstance(payload.get('position_refinement', {}), dict):
            return None
        identity = _engine_identity()
        if record.get('signature') != _digest((identity, portable_key)):
            # Independently confirmed geometry remains reusable. Unvalidated
            # old fits must retry the independent-line/extended-cell rescue.
            previous = [
                (identity[0], revision, identity[2]) for revision in (
                    '2026-11-05-common-scan-zero-large-seed-2',
                    '2026-11-05-common-scan-zero-operator-decision-3',
                )
            ]
            if (payload.get('position_refinement', {}).get('zero_confirmed') is not True
                    or not any(record.get('signature') == _digest((old, portable_key)) for old in previous)):
                return None
        if record.get('result_sha256') != _digest(payload):
            return None
        # Live results are editable (for example, a zero-shift decision). They
        # must never share mutable data with the signed, portable cache record.
        values = deepcopy(payload)
        candidates = [FinderCandidateResult(**item) for item in values.pop('candidates')]
        observed = []
        for item in values.pop('observed_peaks', []):
            peak = dict(item)
            peak['assignments'] = [PeakAssignment(**{**assignment, 'hkl': tuple(assignment['hkl'])})
                                   for assignment in peak.get('assignments', [])]
            peak['status'] = PeakStatus(peak.get('status', 'unknown'))
            observed.append(ObservedPeak(**peak))
        failures = [FinderCandidateFailure(**item) for item in values.pop('candidate_failures', [])]
        result = FinderResult(**values, candidates=candidates, observed_peaks=observed,
                              candidate_failures=failures)
        size = len(result.pattern_x)
        arrays = [result.pattern_x, result.pattern_y, result.background, result.calculated_total]
        arrays.extend(candidate.profile for candidate in candidates)
        arrays.extend(candidate.mass_profile for candidate in candidates if candidate.mass_profile)
        if size < 2 or any(len(array) != size or not np.all(np.isfinite(array)) for array in arrays):
            return None
        if not np.all(np.diff(result.pattern_x) > 0.) or not np.isfinite(result.global_zero_shift):
            return None
        for peak in observed:
            if not np.all(np.isfinite([peak.two_theta, peak.intensity, peak.fwhm])):
                return None
            if any(len(assignment.hkl) != 3 for assignment in peak.assignments):
                return None
        if result.position_refinement.get('le_bail', {}).get('status') == 'applied':
            from xrd_finder.services.le_bail import refresh_le_bail_peak_evidence
            result = refresh_le_bail_peak_evidence(result)
        elif len(candidates) > 1 and any(c.quantity_percent is not None for c in candidates):
            # Keep saved curves/assignments without a full recalculation, but
            # old XPFF Quant must meet the current identifiability safeguard.
            from xrd_finder.finder.quantification import normalized_profile_error
            matrix = np.column_stack([c.mass_profile or c.profile for c in candidates])
            target = np.asarray(result.pattern_y) - np.asarray(result.background)
            weighted = matrix / np.sqrt(np.maximum(np.abs(target), 1.))[:, None]
            norms = np.linalg.norm(weighted, axis=0)
            error = (normalized_profile_error(weighted / norms) if np.all(norms > 0.) else
                     'A saved phase has no usable calculated intensity; individual mass fractions cannot be separated')
            if error:
                for candidate in candidates:
                    candidate.quantity_percent = None
                result.quantification_error = '; '.join(part for part in (result.quantification_error, error) if part)
        return result
    except (KeyError, TypeError, ValueError, OverflowError, np.linalg.LinAlgError):
        return None
