"""A separate peak-list workspace; sampled measurements are never fabricated."""
import math
from PySide6.QtCore import QSignalBlocker, QPointF, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMessageBox
from xrd_finder.core.pattern import Pattern
from xrd_finder.ui.manual_peak_editor import ManualPeakEditor


class ManualPeakActionsMixin:
    def _toggle_manual_peak_input(self):
        if not self.add_peak_action.isChecked():
            self._close_manual_peak_editor(); return
        self._cancel_peak_information(close_card=True)
        self._cancel_candidate_search_jobs()
        pattern = self._active_pattern()
        if getattr(pattern, 'input_kind', '') != 'peak_list':
            profile = self._instrument_profile_for_pattern(pattern)
            pattern = Pattern.create('Manual peaks')
            pattern.input_kind = 'peak_list'; pattern.y_unit = 'relative_intensity'
            pattern.instrument_profile = profile.to_dict()
            self.project.patterns.append(pattern)
            with QSignalBlocker(self.tree):
                self.tree.set_project(self.project)
                self.tree.select_object('pattern', pattern.id)
            self.project.touch(); self.project_changed.emit()
        self.show_all_selected_patterns = False
        with QSignalBlocker(self.finder_plot_control_bar.pattern_display_mode):
            self.finder_plot_control_bar.pattern_display_mode.setCurrentText('One')
        self._manual_peak_pattern_id = pattern.id
        self._manual_peak_input_armed = True
        self._manual_peak_delete_mode = False
        self.delete_peak_action.setChecked(False)
        self._activate_profile_state_for_pattern(pattern.id)
        self._begin_peak_search()
        editor = getattr(self, '_manual_peak_editor', None)
        if editor is None:
            editor = self._manual_peak_editor = ManualPeakEditor(self)
            editor.addRequested.connect(self._store_manual_peak)
            editor.updateRequested.connect(lambda old, angle, intensity: self._store_manual_peak(angle, intensity, old))
            editor.removeRequested.connect(self._remove_manual_peak)
            editor.finished.connect(lambda _result: self._leave_manual_peak_input())
        editor.set_peaks(pattern.peak_points); editor.show(); editor.raise_()
        if not hasattr(self, '_manual_peak_escape'):
            self._manual_peak_escape = QShortcut(QKeySequence(Qt.Key_Escape), self)
            self._manual_peak_escape.setContext(Qt.WidgetWithChildrenShortcut)
            self._manual_peak_escape.activated.connect(self._close_manual_peak_editor)
        self._manual_peak_escape.setEnabled(True)
        self.match_plot.viewport().setCursor(Qt.CrossCursor)
        self._draw_observed_patterns()
        self._reset_match_plot_view()
        self._set_background_status('Manual peaks: click to add 2θ and intensity; right-click to remove. Esc exits input.')

    def _toggle_manual_peak_delete(self):
        if not self.delete_peak_action.isChecked():
            self._close_manual_peak_editor(); return
        if getattr(self._active_pattern(), 'input_kind', '') != 'peak_list':
            self.delete_peak_action.setChecked(False)
            QMessageBox.information(self, 'Delete peak', 'Choose a manual peak list. Search marks on a measured profile can be removed with right-click in Peak search.')
            return
        self.add_peak_action.setChecked(True)
        self._toggle_manual_peak_input()
        self.add_peak_action.setChecked(False)
        self.delete_peak_action.setChecked(True)
        self._manual_peak_delete_mode = True
        self._set_background_status('Delete manual peak: click a peak on the plot, or use Remove selected in the editor.')

    def _leave_manual_peak_input(self):
        self._manual_peak_input_armed = False
        action = getattr(self, 'add_peak_action', None)
        if action is not None: action.setChecked(False)
        action = getattr(self, 'delete_peak_action', None)
        if action is not None: action.setChecked(False)
        if hasattr(self, '_manual_peak_escape'): self._manual_peak_escape.setEnabled(False)
        self.match_plot.viewport().unsetCursor()

    def _close_manual_peak_editor(self):
        self._leave_manual_peak_input()
        editor = getattr(self, '_manual_peak_editor', None)
        if editor is not None: editor.close()

    def _store_manual_peak(self, angle, intensity, old_angle=None):
        pattern = self._active_pattern()
        if getattr(pattern, 'input_kind', '') != 'peak_list': return
        angle, intensity = round(float(angle), 4), round(float(intensity), 2)
        if not math.isfinite(angle) or not 0. < angle <= 125. or not math.isfinite(intensity) or not 0. <= intensity <= 100.:
            QMessageBox.warning(self, 'Manual peak', 'Use 0 < 2θ ≤ 125° and intensity between 0 and 100.'); return
        points = {float(a): float(i) for a, i in pattern.peak_points}
        selected = set(self._manual_search_peaks.get(pattern.id, [a for a, i in pattern.peak_points if i > 0.]))
        if old_angle is not None: points.pop(float(old_angle), None); selected.discard(float(old_angle))
        points[angle] = intensity
        selected.discard(angle)
        if intensity > 0.: selected.add(angle)
        pattern.peak_points = [[a, points[a]] for a in sorted(points)]
        self._manual_search_peaks[pattern.id] = sorted(selected)
        self._manual_peak_changed(pattern)
        editor = getattr(self, '_manual_peak_editor', None)
        if editor is not None:
            row = next(index for index, (a, _i) in enumerate(pattern.peak_points) if a == angle)
            editor.table.selectRow(row)
            editor._select_row(row, 0)

    def _remove_manual_peak(self, angle):
        pattern = self._active_pattern()
        if getattr(pattern, 'input_kind', '') != 'peak_list': return
        pattern.peak_points = [[a, i] for a, i in pattern.peak_points if a != angle]
        self._manual_search_peaks[pattern.id] = [a for a in self._manual_search_peaks.get(pattern.id, []) if a != angle]
        self._manual_peak_changed(pattern)

    def _manual_peak_changed(self, pattern):
        self._cancel_candidate_search_jobs()
        pattern.touch(); self.project.touch(); self.project_changed.emit()
        self._draw_observed_patterns()
        editor = getattr(self, '_manual_peak_editor', None)
        if editor is not None: editor.set_peaks(pattern.peak_points)
        self._set_candidate_status_state('idle')
        self._set_candidate_batch_detail('Manual peaks changed | Run Peak search')

    def _pick_manual_peak(self, scene_position, button):
        if not getattr(self, '_manual_peak_input_armed', False): return False
        pattern = self._active_pattern()
        if getattr(pattern, 'id', None) != self._manual_peak_pattern_id:
            self._close_manual_peak_editor(); return False
        view = self.match_plot.getViewBox()
        if not view.sceneBoundingRect().contains(scene_position): return False
        nearest = None
        for angle, intensity in pattern.peak_points:
            point = view.mapViewToScene(QPointF(angle, intensity))
            distance = (point.x()-scene_position.x())**2+(point.y()-scene_position.y())**2
            if nearest is None or distance < nearest[0]: nearest = distance, angle
        if button == Qt.RightButton or (button == Qt.LeftButton and getattr(self, '_manual_peak_delete_mode', False)):
            if nearest is not None and nearest[0] <= 18.**2: self._remove_manual_peak(nearest[1])
        elif button == Qt.LeftButton:
            point = view.mapSceneToView(scene_position)
            angle, intensity = round(point.x(), 4), round(point.y(), 2)
            if 0. < angle <= 125. and 0. <= intensity <= 100.:
                self._store_manual_peak(angle, intensity)
        return True

    def _select_manual_peaks(self):
        pattern = self._active_pattern()
        if getattr(pattern, 'input_kind', '') != 'peak_list': return
        self._cancel_selected_peak_search()
        self._manual_search_peaks[pattern.id] = [a for a, i in pattern.peak_points if i > 0.]
        self._begin_peak_search(); self._redraw_selected_search_peaks()
