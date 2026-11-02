"""Portable, validated calculation results; project files contain JSON only."""
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
import hashlib
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path

import numpy as np

from xrd_finder import __version__
from xrd_finder.finder.models import (
    FinderCandidateFailure, FinderCandidateResult, FinderResult,
    ObservedPeak, PeakAssignment, PeakStatus,
)


RESULT_FORMAT_VERSION = 1
# Bump when changing the scientific calculation without an application release.
CALCULATION_REVISION = '2026-11-01-common-scan-zero-1'


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
    return (__version__, CALCULATION_REVISION,
            tuple((name, dependency_version(name)) for name in ('cristma', 'numpy', 'scipy', 'pybaselines')))


def make_result_record(result: FinderResult, portable_key: tuple) -> dict:
    payload = asdict(result)
    return {'format': RESULT_FORMAT_VERSION,
            'signature': _digest((_engine_identity(), portable_key)),
            'result_sha256': _digest(payload), 'result': payload}


def restore_result(record, portable_key: tuple) -> FinderResult | None:
    """Reject stale/incomplete payloads; never trust a saved Quant independently."""
    if not isinstance(record, dict) or record.get('format') != RESULT_FORMAT_VERSION:
        return None
    try:
        if record.get('signature') != _digest((_engine_identity(), portable_key)):
            return None
        payload = record['result']
        if record.get('result_sha256') != _digest(payload):
            return None
        values = dict(payload)
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
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
