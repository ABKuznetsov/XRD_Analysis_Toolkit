"""Capture on Qt, parse/refine on a worker, apply only to the same scan."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import numpy as np
from xrd_finder.finder.profile_calculator import array_fingerprint
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.native_cif_session import native_cif_session
from xrd_finder.ui.gain_job import capture_gain_job


def acceptance_key(window, inputs, path):
    pattern = window._active_pattern()
    observed = inputs.observed
    return (id(window.project), getattr(pattern, 'id', None),
            None if observed is None else (array_fingerprint(observed[:,0]), array_fingerprint(observed[:,1])),
            inputs.instrument_profile.calculation_key(), inputs.scoring_source,
            inputs.background_removed, inputs.wavelength, inputs.include_kalpha2,
            None if inputs.background is None else (
                array_fingerprint(inputs.background[:,0]), array_fingerprint(inputs.background[:,1])),
            json.dumps([asdict(s) for s in inputs.project_structures], sort_keys=True, default=str),
            tuple(window._candidate_key(c) for c in inputs.candidates),
            tuple(sorted(inputs.zero_shifts.items())), tuple(sorted(inputs.cell_scales.items())),
            hashlib.sha256(Path(path).read_bytes()).digest())


@native_cif_session
def prepare_acceptance(inputs, candidate, path, evidence):
    _phase, structure = create_phase_from_cif(path)
    if inputs.cache_root and candidate.get('Source') in {'COD','MP','USER','CCDC','OQMD','AFLOW'}:
        from xrd_finder.services.local_phase_cache import LocalPhaseCache
        LocalPhaseCache(inputs.cache_root).ensure_reference_range(
            candidate['Source'], candidate.get('Entry',''),
            wavelength=inputs.instrument_profile.radiation.components[0].wavelength_angstrom)
    if evidence is None and inputs.candidates:
        from xrd_finder.services.gain_calculation import GainComputation
        from xrd_finder.ui.gain_scoring import GainStage, build_gain_indexed_evidence
        computation = GainComputation(inputs, lambda: False)
        context = computation._candidate_gain_context()
        if context is not None:
            stage = GainStage(computation._gain_stage_for_context(context))
            context['gain_stage'] = str(stage)
            records = computation._gain_stage_records(context, str(stage), limit=90)
            peaks = computation._candidate_aligned_gain_peaks_cached(candidate, context)
            # Peak-search contexts already align indexed lines and do not
            # contain the residual profile required by the legacy path.
            if 'peak_search' not in context:
                peaks, _profile, _gain, _snr = computation._candidate_profile_with_cell_refinement(candidate, peaks, context)
            evidence = build_gain_indexed_evidence(peaks=peaks, records=records, stage=stage,
                base_fwhm=float(context.get('fwhm', .18) or .18))
    preprocessing = None
    if inputs.preprocess_auto and inputs.observed is not None and len(inputs.observed):
        from xrd_finder.services.preprocessing_service import auto_preprocess_for_scoring
        preprocessing = auto_preprocess_for_scoring(inputs.observed[:,0], inputs.observed[:,1])
    return structure, evidence, preprocessing


def queue_candidate_acceptance(window, candidate, *, show_errors, prepared_evidence=None):
    from copy import deepcopy
    from PySide6.QtWidgets import QMessageBox
    key = window._candidate_key(candidate)
    pending = getattr(window, '_pending_acceptances', set())
    if key in pending:
        return True
    path = window._candidate_cif_path(candidate)
    _identity, inputs = capture_gain_job(window)
    identity = acceptance_key(window, inputs, path)
    prepared = prepared_evidence
    candidate = deepcopy(candidate)
    pending.add(key)
    window._pending_acceptances = pending
    def done(result):
        pending.discard(key)
        _identity, current = capture_gain_job(window)
        if identity != acceptance_key(window, current, path):
            window._set_background_status('Scan changed; phase acceptance discarded')
            return
        structure, evidence, preprocessing = result
        if preprocessing is not None:
            pattern = window._active_pattern()
            window._auto_scoring_cache[window._auto_scoring_cache_key(pattern, inputs.observed)] = preprocessing
            window._trim_auto_scoring_cache()
        if evidence is not None and evidence.indexed_matches:
            window._candidate_gain_indexed_evidence[key] = evidence
        window._add_candidate_to_match_list(candidate, show_errors, _prepared_structure=structure)
    def failed(message, details):
        pending.discard(key)
        if show_errors:
            QMessageBox.warning(window, 'Working set failed', message or details)
    window._run_background_task('Accept phase', 'Preparing accepted phase...',
        lambda: prepare_acceptance(inputs, candidate, path, prepared), done, failed,
        operation_name='match.accept.prepare')
    return True
