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
        state = self.profile_states.get(pattern.id, {}) if pattern is not None else {}
        suffix = (('le_bail', LE_BAIL_POLICY),) if self._le_bail_enabled_for_pattern(pattern) else ()
        if suffix and state.get('le_bail_applied_iterations'):
            suffix += (('manual_le_bail', state['le_bail_applied_iterations']),)
        if state.get('le_bail_fixed_zero') is not None:
            suffix += (('fixed_refined_zero', state['le_bail_fixed_zero']),)
        return suffix

    def _set_sample_refinement_iterations(self, value):
        pattern = self._active_pattern()
        if pattern is not None:
            self.profile_states.setdefault(pattern.id, {})['le_bail_iterations'] = int(value)
            self.project.touch()
            self.project_changed.emit()

    def _sample_fixed_geometry_zero(self, pattern, candidates, sample_cells):
        import math
        state = self.profile_states.get(pattern.id, {})
        zero = state.get('le_bail_fixed_zero')
        saved = state.get('sample_cell_overrides', {})
        if (zero is None or not math.isfinite(float(zero)) or len(sample_cells) != len(candidates)
                or not candidates or any(saved.get(self._candidate_key(c), {}).get('origin') not in {'le_bail','reference'} for c in candidates)):
            return None
        return float(zero)

    def _resume_sample_le_bail_result(self, pattern, candidates, current):
        import numpy as np
        from xrd_finder.io.finder_result_cache import restore_result
        state = self.profile_states.get(pattern.id, {})
        record, key = state.get('le_bail_refinement_result'), state.get('le_bail_refinement_key')
        if not record or not key or state.get('le_bail_instrument_key') != self._instrument_profile_for_pattern(pattern).calculation_key():
            return current
        previous = restore_result(record, key)
        if previous is None or previous.position_refinement.get('le_bail', {}).get('status') != 'applied':
            return current
        cells = self._sample_cell_structure_overrides(pattern, candidates)
        if len(cells) != len(candidates) or previous.global_zero_shift != current.global_zero_shift:
            return current
        if any(not np.array_equal(getattr(previous,n),getattr(current,n)) for n in ('pattern_x','pattern_y','background')):
            return current
        fitted = {c.entry_id:c for c in previous.candidates}
        for candidate in candidates:
            key = self._candidate_key(candidate)
            if key not in fitted or key not in cells:
                return current
            if any(float(fitted[key].estimated_cell.get(n,float('nan'))) != float(getattr(cells[key].cell,n))
                   for n in ('a','b','c','alpha','beta','gamma')):
                return current
        return previous

    def _reset_sample_to_reference(self):
        from dataclasses import asdict
        from xrd_finder.io.cif_loader import create_phase_from_cif
        from xrd_finder.io.finder_result_cache import cif_content_signature
        from PySide6.QtWidgets import QMessageBox
        pattern = self._active_pattern()
        if pattern is None or getattr(self, '_sample_le_bail_running_pattern', None) is not None:
            return
        candidates = self._profile_candidates_for_pattern(pattern)
        if not candidates:
            return
        reference = {}
        try:
            for candidate in candidates:
                path = self._candidate_local_cif_path(candidate)
                if path is None:
                    raise ValueError('Every accepted phase needs a local reference CIF.')
                _phase, structure = create_phase_from_cif(path)
                reference[self._candidate_key(candidate)] = dict(cell=asdict(structure.cell),
                    cif_sha256=cif_content_signature(path), origin='reference')
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.information(self, 'Reset to reference', str(exc))
            return
        result, _ = self._finder_result_for_pattern(pattern, candidates, cache_only=True)
        state = self.profile_states.setdefault(pattern.id, {})
        zero = result.global_zero_shift if result is not None else state.get('le_bail_fixed_zero', 0.)
        self._set_pattern_le_bail(pattern, False)
        for key in list(state):
            if key.startswith('le_bail_') and key != 'le_bail_iterations':
                state.pop(key)
        state['sample_cell_overrides'] = reference
        state['le_bail_fixed_zero'] = float(zero)
        state['le_bail_attempt'] = {'status':'reference', 'message':'Reference CIF cells restored; sample zero correction retained.'}
        self._save_active_profile_state()
        self._invalidate_match_profile_cache(pattern.id)
        self.project.touch()
        self.project_changed.emit()
        self._recalculate_match_profile(auto_zoom=False, active_only=True)
        self._update_compound_card_sample()

    def _refine_active_sample_profile(self):
        from copy import deepcopy
        from xrd_finder.finder.models import FinderInput, FinderCandidateInput
        from xrd_finder.services.le_bail import refine_accepted_le_bail
        from PySide6.QtWidgets import QMessageBox
        pattern = self._active_pattern()
        if pattern is None:
            return
        running_pattern = getattr(self, '_sample_le_bail_running_pattern', None)
        if running_pattern is not None and running_pattern != pattern.id:
            QMessageBox.information(self, 'Le Bail', 'Another sample is being refined. Finish or cancel that refinement first.')
            return
        if running_pattern is not None:
            self._sample_le_bail_serial = getattr(self, '_sample_le_bail_serial', 0)+1
            self._set_background_status('Cancelling Le Bail; previous result retained')
            return
        candidates = self._profile_candidates_for_pattern(pattern)
        result, _ = self._finder_result_for_pattern(pattern, candidates, cache_only=True)
        if result is None or result.position_refinement.get('requires_confirmation') or result.position_refinement.get('position_rejected'):
            QMessageBox.information(self, 'Le Bail', 'Calculate and accept the current phase alignment first.')
            return
        if result.position_refinement.get('le_bail', {}).get('status') != 'applied':
            result = self._resume_sample_le_bail_result(pattern, candidates, result)
        phases = []
        for candidate in candidates:
            path = self._candidate_local_cif_path(candidate)
            if path is None or not path.is_file():
                QMessageBox.information(self, 'Le Bail', 'Every accepted phase needs a local CIF structure.')
                return
            phases.append(FinderCandidateInput(cif_path=str(path), entry_id=self._candidate_key(candidate),
                name=self._phase_legend_label(candidate), formula=candidate.get('Formula',''), source=candidate.get('Source','')))
        iterations = self.compound_card.le_bail_iterations.value()
        wave, ka2 = self._legacy_radiation_for_pattern(pattern)
        inputs = FinderInput(pattern_path=pattern.source_path, candidates=phases, wavelength=wave,
            include_kalpha2=ka2, instrument_profile=self._instrument_profile_for_pattern(pattern))
        project_id = id(self.project)
        original_key = self._finder_cache_key(pattern, candidates)
        serial = self._sample_le_bail_serial = getattr(self, '_sample_le_bail_serial', 0)+1
        self._sample_le_bail_running_pattern = pattern.id
        self._update_compound_card_sample()
        def cancelled():
            return (serial != self._sample_le_bail_serial or project_id != id(self.project)
                    or getattr(self, '_preparation_close_confirmed', False))
        def finish(refined):
            self._sample_le_bail_running_pattern = None
            if project_id != id(self.project):
                self._update_compound_card_sample()
                return
            current = self._profile_candidates_for_pattern(pattern)
            if self._finder_cache_key(pattern, current) != original_key:
                self._update_compound_card_sample()
                return
            note = refined.position_refinement.get('le_bail', {})
            state = self.profile_states.setdefault(pattern.id, {})
            state['le_bail_attempt'] = deepcopy(note)
            if not cancelled() and note.get('status') == 'applied':
                self._set_pattern_le_bail(pattern, True)
                state['le_bail_applied_iterations'] = iterations
                cache_key = self._finder_cache_key(pattern, current)
                self.match_profile_result_cache[cache_key] = refined
                self._store_calculated_result(pattern, current, refined)
                self._trim_match_profile_result_cache()
                self.project.touch()
                self.project_changed.emit()
                self._recalculate_match_profile(auto_zoom=False, active_only=True)
            self._update_compound_card_sample()
            self._show_le_bail_result_status(pattern, refined)
        def failed(message, details):
            self._sample_le_bail_running_pattern = None
            if project_id == id(self.project):
                self.profile_states.setdefault(pattern.id, {})['le_bail_attempt'] = {'message': 'Le Bail failed: '+str(message or details)}
                self._update_compound_card_sample()
        self._run_background_task('Le Bail', f'Le Bail: up to {iterations} iterations; click refinement again to cancel',
            lambda: refine_accepted_le_bail(inputs, deepcopy(result), max_cycles=iterations,
                timeout_seconds=max(60., iterations*6.), cancelled=cancelled), finish, failed,
            operation_name='sample.le_bail')

    def _adopt_sample_le_bail_cells(self, pattern, candidates, result):
        from copy import deepcopy
        from dataclasses import asdict
        from xrd_finder.core.structure import CellParameters
        from xrd_finder.finder.cell_parameter_estimator import FastCellParameterEstimator
        from xrd_finder.io.finder_result_cache import cif_content_signature
        if result.position_refinement.get('le_bail', {}).get('status') != 'applied':
            return False
        fitted = {item.entry_id: item for item in result.candidates}
        updates = {}
        for candidate in candidates:
            key = self._candidate_key(candidate)
            item = fitted.get(key)
            if item is None:
                return False
            try:
                cell = CellParameters(**{name:item.estimated_cell[name] for name in ('a','b','c','alpha','beta','gamma')})
            except (KeyError, TypeError):
                return False
            signature = cif_content_signature(self._candidate_local_cif_path(candidate))
            if not signature or not FastCellParameterEstimator._valid_cell(cell):
                return False
            updates[key] = dict(cell=asdict(cell), cif_sha256=signature, origin='le_bail')
        state = self.profile_states.setdefault(pattern.id, {})
        state['le_bail_refinement_result'] = deepcopy(state.get('calculated_result'))
        state['le_bail_refinement_key'] = self._finder_cache_key(pattern, candidates, portable=True)
        state['le_bail_instrument_key'] = self._instrument_profile_for_pattern(pattern).calculation_key()
        state.setdefault('sample_cell_overrides', {}).update(updates)
        state['le_bail_fixed_zero'] = float(result.global_zero_shift)
        return True

    def _show_le_bail_result_status(self, pattern, result):
        note = result.position_refinement.get('le_bail', {})
        if pattern.id == self._current_profile_pattern_id() and note:
            self._set_background_status(note.get('message', 'Le Bail finished'))
