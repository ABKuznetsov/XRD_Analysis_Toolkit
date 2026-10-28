"""Owned accepted-profile jobs, serialized and coalesced per sample."""
from copy import deepcopy
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

    def request(self, pattern, key, inputs):
        w = self.window
        job = (self.serial, id(w.project), pattern.id, key, deepcopy(inputs))
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
        pattern_id = next(iter(self.pending))
        job = self.pending.pop(pattern_id)
        self.current = job
        serial, project_id, pattern_id, key, inputs = job
        w = self.window
        def current():
            if serial != self.serial or project_id != id(w.project):
                return False
            pattern = next((p for p in w.project.patterns if p.id == pattern_id), None)
            if pattern is None:
                return False
            candidates = w._profile_candidates_for_pattern(pattern)
            return bool(candidates) and w._finder_cache_key(pattern, candidates) == key
        def done(result):
            valid = current()
            self.current = None
            if valid:
                self.failures.pop(pattern_id, None)
                w.match_profile_result_cache[key] = result
                w._trim_match_profile_result_cache()
                pattern = next(p for p in w.project.patterns if p.id == pattern_id)
                w._record_pattern_zero_shift(pattern, result)
                w._recalculate_match_profile(auto_zoom=w._should_autozoom_match_profile(),
                                             refresh_pattern_id=pattern_id)
                w._schedule_candidate_gain_ranking()
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
                w._gain_set_status('Profile unavailable; correct the inputs and retry')
                w.gain_job_controller.invalidate()
            self._start()
        w._run_background_task('Accepted profile', 'Calculating accepted physical profile...',
                               lambda: self.service.run(inputs), done, failed,
                               operation_name='match.profile.accepted')
