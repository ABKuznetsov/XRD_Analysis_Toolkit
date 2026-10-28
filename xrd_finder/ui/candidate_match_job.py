"""Serialize/coalesce ordinary and arriving-card Match outside the UI."""
from copy import deepcopy
from threading import Event
from xrd_finder.services.auto_search_ranker import create_local_reference_peak_loader, rank_candidate_rows
from xrd_finder.services.observed_search_preparation import prepare_observed_search
from xrd_finder.services.reference_preparation import prepare_reference_rows
from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.ui.observed_search_job import capture_observed_search, apply_observed_search_result


class CandidateMatchQueue:
    def __init__(self, window):
        self.window = window
        self.pending = None
        self.running = False
        self.cancel = Event()

    def invalidate(self):
        self.cancel.set()
        self.pending = None

    def request(self, rows):
        w = self.window
        capture = capture_observed_search(w)
        if capture is None:
            return
        self.cancel.set()
        self.pending = (deepcopy(rows), capture, w._candidate_rank_token,
                        str(w.local_phase_cache.root), str(getattr(w.match_pdf2, 'root', '') or ''),
                        w._active_wavelength())
        if not self.running:
            self._start()

    def _start(self):
        if self.pending is None or getattr(self.window, '_preparation_close_confirmed', False):
            return
        rows, capture, token, root, pdf2, wavelength = self.pending
        self.pending = None
        self.running = True
        cancel = self.cancel = Event()
        profile = capture.inputs.instrument_profile
        def compute(progress):
            observed = prepare_observed_search(capture.inputs, cancelled=cancel.is_set)
            scan_range = (float(observed.x.min()), float(observed.x.max()))
            prepare_reference_rows(LocalPhaseCache(root), rows,
                wavelength=profile.radiation.components[0].wavelength_angstrom,
                progress=progress, cancelled=cancel.is_set)
            with create_local_reference_peak_loader(root, pdf2 or None, wavelength,
                    instrument_profile=profile, prepared_only=True, match_only=True,
                    two_theta_range=scan_range) as loader:
                ranked = rank_candidate_rows(rows, observed.records, wavelength=wavelength,
                    two_theta_range=scan_range,
                    reference_peak_loader=loader, progress=progress, cancelled=cancel.is_set)
            return observed, ranked
        w = self.window
        def current():
            now = capture_observed_search(w)
            return (not cancel.is_set() and not w.match_candidates
                    and token == w._candidate_rank_token and now is not None and now.identity == capture.identity)
        def done(result):
            self.running = False
            if current():
                observed, ranked = result
                apply_observed_search_result(w, capture, observed)
                w._set_candidate_rows(ranked.rows, skip_rank=True)
                w._auto_search_ranked_rows = deepcopy(ranked.rows)
                w._auto_search_scored_keys = set(ranked.scored_keys)
                if hasattr(w.candidate_table, 'set_match_diagnostics'):
                    w.candidate_table.set_match_diagnostics(ranked.failures, ranked.unavailable_keys)
                w._set_background_status(ranked.diagnostic_summary)
            self._start()
        def failed(message, details):
            self.running = False
            if current():
                w._set_background_status(f'Match failed: {message or details}')
            self._start()
        w._run_background_task('Match', 'Preparing candidate Match...', compute, done, failed,
            with_progress=True, operation_name='match.rank.loaded')
