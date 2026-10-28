"""Pick and inspect a peak without modifying any scientific or project state."""
import numpy as np
from scipy.signal import find_peaks
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMessageBox

from xrd_finder.services.peak_characterization import characterize_peak, assignments_near_peak
from xrd_finder.ui.peak_matching import instrument_fwhm_at, radiation_satellites_at
from xrd_finder.ui.peak_information_dialog import PeakInformationDialog


class PeakInformationActionsMixin:
    def _toggle_peak_information(self):
        if not self.peak_information_action.isChecked():
            self._cancel_peak_information(close_card=True)
            return
        if getattr(self._active_pattern(), 'input_kind', '') == 'peak_list':
            self.peak_information_action.setChecked(False)
            QMessageBox.information(self, 'Peak information', 'A manual peak list contains positions and intensities, without measured widths or areas. Use Peaks → Add peak to inspect or edit the entries.')
            return
        cancel_find = getattr(self, '_cancel_find_peaks', None)
        if callable(cancel_find):
            cancel_find()
        if not self.observed_pattern_plot_context:
            self.peak_information_action.setChecked(False)
            QMessageBox.information(self, 'Peak information', 'Display an XRD pattern first.')
            return
        if not hasattr(self, '_peak_info_escape'):
            self._peak_info_escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            self._peak_info_escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._peak_info_escape.activated.connect(lambda: self._cancel_peak_information(close_card=True))
        self._peak_info_armed = True
        self._peak_info_escape.setEnabled(True)
        self.match_plot.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self._set_background_status('Click an experimental peak. Right-click or Esc cancels Peak information.')

    def _cancel_peak_information(self, *, close_card=False):
        self._peak_info_armed = False
        self._peak_info_serial = getattr(self, '_peak_info_serial', 0)+1
        self._peak_info_pending = None
        action = getattr(self, 'peak_information_action', None)
        if action is not None:
            action.setChecked(False)
        if hasattr(self, '_peak_info_escape'):
            self._peak_info_escape.setEnabled(False)
        if hasattr(self, 'match_plot'):
            self.match_plot.viewport().unsetCursor()
        dialog = getattr(self, '_peak_info_dialog', None)
        if close_card and dialog is not None:
            dialog.close()

    def _pick_peak_information(self, scene_position, button):
        if button == Qt.MouseButton.RightButton:
            self._cancel_peak_information(close_card=True)
            return
        if button != Qt.MouseButton.LeftButton:
            return
        view = self.match_plot.getViewBox()
        if not view.sceneBoundingRect().contains(scene_position):
            return
        clicked = view.mapSceneToView(scene_position)
        radius = abs(view.viewRange()[0][1]-view.viewRange()[0][0])*24./max(view.sceneBoundingRect().width(), 1.)
        visible = {getattr(c, '_xrd_pattern_id', None) for c in self.plot_layers.get('observed', []) if c.isVisible()}
        best = None
        patterns = {p.id: p for p in self.project.patterns}
        for pattern_id, context in self.observed_pattern_plot_context.items():
            if pattern_id not in visible or pattern_id not in patterns:
                continue
            x, y = np.asarray(context.get('display_x', [])), np.asarray(context.get('display_y', []))
            finite = np.isfinite(x) & np.isfinite(y)
            if finite.sum() < 3:
                continue
            shift = self._pattern_display_zero_shift_deg(pattern_id) if self.profile_states.get(pattern_id, {}).get('correct_zero', False) else 0.
            step = float(np.median(np.diff(x[finite])))
            indices = np.flatnonzero(finite & (abs(x-clicked.x()-shift) <= max(radius, step*4.)))
            for local in find_peaks(y[indices])[0] if len(indices) >= 3 else []:
                index = int(indices[local])
                point = view.mapViewToScene(QPointF(float(x[index])-shift, float(y[index])))
                distance = (point.x()-scene_position.x())**2+(point.y()-scene_position.y())**2
                if distance <= 18.**2 and (best is None or distance < best[0]):
                    best = distance, patterns[pattern_id], context, index, step
        if best is None:
            self._set_background_status('Click closer to an experimental maximum.')
            return
        _distance, pattern, context, index, step = best
        x = np.array(context['display_x'], dtype=float, copy=True)
        y = (np.asarray(context['display_y'], dtype=float)-float(context.get('offset', 0.)))/float(context.get('intensity_scale', 1.))
        profile = self._instrument_profile_for_pattern(pattern)
        seed = float(x[index])
        self._peak_info_serial = getattr(self, '_peak_info_serial', 0)+1
        self._peak_info_pending = dict(serial=self._peak_info_serial, project_id=id(self.project),
            pattern_id=pattern.id, name=pattern.name, context=context, x=x, y=np.array(y, copy=True),
            seed=seed, step=step, wavelength=float(profile.radiation.components[0].wavelength_angstrom),
            instrument_fwhm=instrument_fwhm_at(profile, seed), satellites=radiation_satellites_at(profile, seed))
        self._start_peak_information_job()

    def _start_peak_information_job(self):
        if getattr(self, '_peak_info_busy', False) or not getattr(self, '_peak_info_pending', None):
            return
        request, self._peak_info_pending = self._peak_info_pending, None
        self._peak_info_busy = True

        def current():
            return (getattr(self, '_peak_info_armed', False) and request['serial'] == self._peak_info_serial
                and request['project_id'] == id(self.project)
                and self.observed_pattern_plot_context.get(request['pattern_id']) is request['context'])

        def done(data):
            self._peak_info_busy = False
            if current():
                dialog = getattr(self, '_peak_info_dialog', None)
                if dialog is None:
                    dialog = self._peak_info_dialog = PeakInformationDialog(self)
                    dialog.finished.connect(lambda _result: self._cancel_peak_information())
                self._peak_info_selected = request
                dialog.set_data(data, request['pattern_id'], request['name'])
                self._refresh_peak_information_assignments(request['pattern_id'])
                dialog.show()
                dialog.raise_()
            self._start_peak_information_job()

        def failed(message, _details):
            self._peak_info_busy = False
            if current():
                self._set_background_status(f'Peak information: {message}')
            self._start_peak_information_job()

        self._run_background_task('Peak information', f"Measuring {request['name']} at {request['seed']:.4f}°…",
            lambda: characterize_peak(request['x'], request['y'], request['seed'],
                wavelength=request['wavelength'], instrument_fwhm=request['instrument_fwhm'],
                satellite_offsets_weights=request['satellites']), done, failed, operation_name='peak.information')

    def _refresh_peak_information_assignments(self, pattern_id):
        dialog = getattr(self, '_peak_info_dialog', None)
        selected = getattr(self, '_peak_info_selected', None)
        if dialog is None or selected is None or selected['pattern_id'] != pattern_id:
            return
        context = self.observed_pattern_plot_context.get(pattern_id, {})
        key = context.get('accepted_profile_result_key')
        result = self.match_profile_result_cache.get(key) if key is not None and context is selected['context'] else None
        assignments = assignments_near_peak(result.observed_peaks, selected['seed'], selected['step']) if result is not None else []
        dialog.set_assignments(assignments, result is not None, self.phase_colors)
