"""Per-sample Le Bail mode, separate from the saved instrument calibration."""
from xrd_finder.services.le_bail import LE_BAIL_POLICY


class LeBailActionsMixin:
    def _le_bail_enabled_for_pattern(self, pattern):
        return bool(pattern is not None and
                    self.profile_states.get(pattern.id, {}).get('le_bail_enabled', False))

    def _set_pattern_le_bail(self, pattern, enabled):
        enabled = bool(enabled)
        previous = self._le_bail_enabled_for_pattern(pattern)
        self.profile_states.setdefault(pattern.id, {})['le_bail_enabled'] = enabled
        if enabled != previous:
            # Existing cached structural and Le Bail results have different keys;
            # retain both so turning the enhancement off can restore Quant.
            queue = getattr(self, '_accepted_profile_queue', None)
            if queue is not None:
                queue.invalidate()
            self.gain_job_controller.invalidate()
            if pattern.id == self._current_profile_pattern_id():
                self.match_quantities.clear()
                for candidate in self.match_candidates:
                    candidate.pop('_QuantificationError', None)
                    candidate.pop('_LeBailMessage', None)
                self._update_match_table()

    def _le_bail_cache_suffix(self, pattern):
        return (('le_bail', LE_BAIL_POLICY),) if self._le_bail_enabled_for_pattern(pattern) else ()

    def _show_le_bail_result_status(self, pattern, result):
        note = result.position_refinement.get('le_bail', {})
        if pattern.id == self._current_profile_pattern_id() and note:
            self._set_background_status(note.get('message', 'Le Bail finished'))
