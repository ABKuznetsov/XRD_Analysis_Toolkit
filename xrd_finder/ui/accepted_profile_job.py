"""Owned accepted-profile jobs, serialized and coalesced per sample."""
from copy import deepcopy
from dataclasses import replace
import numpy as np
from xrd_finder.finder import FinderService


class AcceptedProfileQueue:
    def __init__(self, window):
        self.window = window
        self.pending = {}
        self.current = None
        self.serial = 0
        self.failures = {}
        self.service = FinderService()  # used only by this serialized worker

    def invalidate(self):
        self.serial += 1
        self.pending.clear()
        self.failures.clear()

    def waiting_for(self, pattern_id):
        return (pattern_id in self.pending or
                self.current is not None and self.current[2] == pattern_id)

    def request(self, pattern, key, inputs, *, preprocess_auto=False, le_bail=False, prepared_result=None):
        w = self.window
        job = (self.serial, id(w.project), pattern.id, key, deepcopy(inputs), bool(preprocess_auto), bool(le_bail), prepared_result)
        if self.failures.get(pattern.id) == key:
            return
        if self.current is not None and self.current[:4] == job[:4]:
            return
        self.pending[pattern.id] = job
        if self.current is None:
            self._start()

    def _start(self):
        if self.current is not None or not self.pending or getattr(self.window, '_preparation_close_confirmed', False):
            return
        visible = {pattern.id for pattern in self.window._patterns_to_display()}
        active = self.window._current_profile_pattern_id()
        pattern_id = min(self.pending, key=lambda pid: (pid != active, pid not in visible))
        job = self.pending.pop(pattern_id)
        self.current = job
        serial, project_id, pattern_id, key, inputs, preprocess_auto, le_bail, prepared_result = job
        w = self.window
        def current():
            if serial != self.serial or project_id != id(w.project):
                return False
            pattern = next((p for p in w.project.patterns if p.id == pattern_id), None)
            if pattern is None:
                return False
            candidates = w._profile_candidates_for_pattern(pattern)
            return bool(candidates) and w._finder_cache_key(pattern, candidates) == key
        def done(payload):
            result, prepared = payload
            if current() and result.position_refinement.get('requires_confirmation'):
                pattern = next(p for p in w.project.patterns if p.id == pattern_id)
                if pattern_id not in {p.id for p in w._patterns_to_display()}:
                    # Save an unapplied proposal; ask only when its scan is shown.
                    w._store_calculated_result(pattern, w._profile_candidates_for_pattern(pattern), result,
                                               snap_peak_positions=inputs.snap_peak_positions, pending=True)
                    self.current = None
                    self._start()
                    return

                def decided(accepted):
                    if not current() or accepted is None:
                        self.current = None
                        self._start()
                        return
                    if accepted:
                        result.position_refinement['requires_confirmation'] = False
                        result.position_refinement['user_decision'] = 'continue'
                        done((result, prepared))
                    else:
                        self.current = None
                        self.request(pattern, key, replace(inputs, allow_uncertain_zero=False),
                                     preprocess_auto=preprocess_auto, le_bail=le_bail)

                w._confirm_position_alignment(pattern, result, decided)
                return
            valid = current()
            self.current = None
            if valid:
                if result.position_refinement.get('position_rejected'):
                    result.position_refinement['user_decision'] = 'reject'
                self.failures.pop(pattern_id, None)
                w.match_profile_result_cache[key] = result
                w._trim_match_profile_result_cache()
                pattern = next(p for p in w.project.patterns if p.id == pattern_id)
                if prepared is not None:
                    raw = np.column_stack([inputs.observed_x, inputs.observed_y])
                    w._auto_scoring_cache[w._auto_scoring_cache_key(pattern, raw)] = prepared
                    w._trim_auto_scoring_cache()
                w._store_calculated_result(pattern, w._profile_candidates_for_pattern(pattern), result,
                                           snap_peak_positions=inputs.snap_peak_positions)
                w._record_pattern_zero_shift(pattern, result)
                if pattern_id in {item.id for item in w._patterns_to_display()}:
                    w._recalculate_match_profile(auto_zoom=w._should_autozoom_match_profile(),
                                                 refresh_pattern_id=pattern_id)
                if pattern_id == w._current_profile_pattern_id():
                    w._schedule_candidate_gain_ranking()
                w._show_le_bail_result_status(pattern, result)
            elif project_id == id(w.project):
                # Coalesce an in-place edit as well as ordinary control changes.
                w._recalculate_match_profile(active_only=True)
            self._start()
        def failed(message, details):
            valid = current()
            self.current = None
            if valid:
                self.failures[pattern_id] = key
                w._set_background_status(f'Profile calculation failed: {message or details}')
                if pattern_id == w._current_profile_pattern_id():
                    w._gain_set_status('Profile unavailable; correct the inputs and retry')
                    w.gain_job_controller.invalidate()
            self._start()
        def calculate():
            if prepared_result is not None:
                return prepared_result, None
            prepared = None
            working = inputs
            if preprocess_auto:
                from xrd_finder.ui.observed_pattern_actions import auto_preprocess_for_scoring
                prepared = auto_preprocess_for_scoring(np.asarray(inputs.observed_x), np.asarray(inputs.observed_y))
                working = replace(inputs, observed_x=prepared.x.tolist(), observed_y=prepared.y.tolist())
            result = self.service.run(working)
            if le_bail:
                from xrd_finder.services.le_bail import refine_accepted_le_bail
                result = refine_accepted_le_bail(working, result, cancelled=lambda:
                    serial != self.serial or project_id != id(w.project)
                    or getattr(w, '_preparation_close_confirmed', False))
            return result, prepared
        pattern = next((item for item in w.project.patterns if item.id == pattern_id), None)
        name = pattern.name if pattern is not None else pattern_id
        w._run_background_task('Accepted profile', f'Preparing {name} ({len(self.pending)} queued)...',
                               calculate, done, failed,
                               operation_name='match.profile.accepted')
