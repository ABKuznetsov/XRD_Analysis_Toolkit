"""Non-modal automatic selection of observed peaks for the existing search."""
from threading import Event

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMessageBox

from xrd_finder.services.observed_search_preparation import ObservedSearchInput
from xrd_finder.services.search_peak_detection import detect_search_peak_positions


class FindPeaksActionsMixin:
    def _cancel_find_peaks(self):
        cancel = getattr(self, '_find_peaks_cancel', None)
        if cancel is not None:
            cancel.set()
        shortcut = getattr(self, '_find_peaks_escape', None)
        if shortcut is not None:
            shortcut.setEnabled(False)

    def _find_peaks_from_menu(self):
        if getattr(self, '_find_peaks_busy', False):
            return
        pattern = self._active_pattern()
        if getattr(pattern, 'input_kind', '') == 'peak_list':
            self._select_manual_peaks()
            return
        context = self.observed_pattern_plot_context.get(getattr(pattern, 'id', None))
        if pattern is None or context is None:
            QMessageBox.information(self, 'Find peaks', 'Display an active XRD pattern first.')
            return
        x = np.asarray(context.get('display_x', []), dtype=float)
        y = np.asarray(context.get('display_y', []), dtype=float)
        if x.ndim != 1 or x.shape != y.shape or np.count_nonzero(np.isfinite(x) & np.isfinite(y)) < 5:
            QMessageBox.information(self, 'Find peaks', 'Not enough displayed XRD data to find peaks.')
            return
        try:
            scale = float(context.get('intensity_scale', 1.))
            if not np.isfinite(scale) or scale <= 0.:
                raise ValueError('Invalid display intensity scale.')
            y = (y-float(context.get('offset', 0.)))/scale
            profile = self._instrument_profile_for_pattern(pattern)
            zero = self._pattern_zero_shift_deg(pattern.id)
            removed = bool(pattern.processed_background_removed)
            inputs = ObservedSearchInput(np.column_stack([x, y]), not removed, removed,
                profile, global_zero_shift=zero)
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, 'Find peaks', str(exc))
            return
        self._cancel_peak_information(close_card=True)
        self._begin_peak_search()
        self._cancel_selected_peak_search()
        project = self.project
        selected = tuple(self._manual_search_peaks.get(pattern.id, []))
        profile_key = profile.calculation_key()
        cancel = self._find_peaks_cancel = Event()
        self._find_peaks_busy = True
        self.find_peaks_action.setEnabled(False)
        if not hasattr(self, '_find_peaks_escape'):
            self._find_peaks_escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            self._find_peaks_escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._find_peaks_escape.activated.connect(self._cancel_find_peaks)
        self._find_peaks_escape.setEnabled(True)

        def current():
            return (not cancel.is_set() and self.project is project
                and self._active_pattern() is pattern and self._search_mode == 'peaks'
                and self.observed_pattern_plot_context.get(pattern.id) is context
                and tuple(self._manual_search_peaks.get(pattern.id, [])) == selected
                and self._instrument_profile_for_pattern(pattern).calculation_key() == profile_key
                and self._pattern_zero_shift_deg(pattern.id) == zero)

        def release():
            self._find_peaks_busy = False
            self.find_peaks_action.setEnabled(True)
            self._find_peaks_escape.setEnabled(False)

        def done(positions):
            release()
            if not current():
                return
            merged = sorted(set(selected).union(float(p) for p in positions))
            self._manual_search_peaks[pattern.id] = merged
            self._redraw_selected_search_peaks()
            self._set_candidate_status_state('idle')
            self._set_candidate_batch_detail(
                f'Found {len(positions)} peaks | Selected {len(merged)} | Run Peak search')
            self._set_background_status(
                f'Found {len(positions)} peaks in {pattern.name}; search selection has {len(merged)} peaks.'
                if len(positions) else 'No usable peaks found; existing search marks were kept.')

        def failed(message, _details):
            release()
            if current():
                self._set_background_status('Find peaks failed; existing search marks were kept.')
                QMessageBox.warning(self, 'Find peaks', message)

        self._run_background_task('Find peaks', f'Finding peaks in {pattern.name}… (Esc cancels)',
            lambda: detect_search_peak_positions(inputs, cancelled=cancel.is_set), done, failed,
            operation_name='peaks.find')
