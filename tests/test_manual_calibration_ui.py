"""Manual calibration is preview-only until Apply and invalidates old results."""
from copy import deepcopy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('XRD_FINDER_OFFLINE', '1')
os.environ.setdefault('XRD_FINDER_DATA_DIR', tempfile.mkdtemp(prefix='xrd-calibration-ui-'))

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.app_settings import app_settings


class ManualCalibrationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        settings = app_settings()
        self._settings_before = {key:settings.value(key) for key in settings.allKeys()}
        settings.clear()
        self.slot_errors = []
        hook = patch.object(sys, 'excepthook', side_effect=lambda *args: self.slot_errors.append(args))
        hook.start(); self.addCleanup(hook.stop)
        self.a, self.b = Pattern.create('A'), Pattern.create('B')
        self.x = np.linspace(20., 40., 201)
        self.a.processed_points = np.column_stack([self.x, 3.+100.*np.exp(-((self.x-30.)/.2)**2)]).tolist()
        self.original = deepcopy(self.a.processed_points)
        with patch.object(PhaseFinderWindow, '_start_match_pdf2_preload'):
            self.w = PhaseFinderWindow(Project('Calibration', patterns=[self.a, self.b]), defer_initial_plot=True)
        self.w.normalize_observed_patterns = False
        self.w.resize(1280, 720)
        self.w.show(); self.app.processEvents()
        self.w._draw_observed_patterns()

    def tearDown(self):
        close = getattr(self.w, '_close_manual_calibration', None)
        if close: close()
        self.w._confirm_project_replacement = lambda: True
        self.w.close(); self.w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        settings = app_settings()
        settings.clear()
        for key,value in self._settings_before.items():
            settings.setValue(key,value)
        settings.sync()
        self.assertFalse(self.slot_errors, f'Uncaught Qt callback errors: {self.slot_errors}')

    def open(self):
        menu = next(m for m in self.w.menu_bar._owned_menus if m.title() == 'Tools')
        action = next((a for a in menu.actions() if a.text() == 'Calibrate pattern...'), None)
        self.assertIsNotNone(action, 'Calibrate pattern must replace the placeholder')
        action.trigger(); self.app.processEvents()
        return getattr(self.w, '_manual_calibration_dialog', None)

    def test_preview_and_cancel_do_not_change_data_or_calculated_layer(self):
        item = self.w.plot_layers['observed'][0]
        old = item.pos().x()
        reference = self.w.match_plot.plot([29., 30.], [5., 10.])
        self.w.plot_layers.setdefault('calculated', []).append(reference)
        self.w._tag_plot_item_pattern(reference, self.a.id) if hasattr(self.w, '_tag_plot_item_pattern') else None
        dialog = self.open()
        stamp = self.w.project.updated_at
        dialog.correction.setValue(.25)
        self.assertAlmostEqual(item.pos().x(), old-.25)
        self.assertEqual(reference.pos().x(), 0.)
        self.assertEqual(self.a.processed_points, self.original)
        self.assertEqual(self.a.angle_calibration_deg, 0.)
        self.assertEqual(self.w.project.updated_at, stamp)
        dialog.reject()
        self.assertAlmostEqual(item.pos().x(), old)
        self.assertEqual(self.a.processed_points, self.original)

    def test_apply_updates_analysis_coordinates_and_clears_old_zero_and_search_marks(self):
        self.w.profile_states[self.a.id] = {'zero_shift_auto_deg': .2, 'zero_shift_visual_deg': .1,
            'correct_zero': True, 'result_snapshot': {'fit': {'zero_shift_deg': .2}}}
        self.w._manual_search_peaks[self.a.id] = [30.]
        dialog = self.open(); dialog.correction.setValue(.3)
        with patch.object(self.w, '_rerun_active_calculation') as rerun:
            dialog.apply_button.click()
        np.testing.assert_allclose(np.asarray(self.a.processed_points)[:, 0], self.x-.3)
        np.testing.assert_array_equal(np.asarray(self.a.processed_points)[:, 1], np.asarray(self.original)[:, 1])
        self.assertEqual(self.a.angle_calibration_deg, .3)
        self.assertEqual(self.w._pattern_zero_shift_deg(self.a.id), 0.)
        self.assertFalse(self.w.profile_states[self.a.id].get('correct_zero', False))
        self.assertNotIn('result_snapshot', self.w.profile_states[self.a.id])
        self.assertNotIn(self.a.id, self.w._manual_search_peaks)
        np.testing.assert_allclose(self.w._active_observed_data()[:, 0], self.x-.3)
        rerun.assert_called_once()
        self.assertEqual(self.b.processed_points, [])

    def test_preview_pauses_display_only_zero_and_cancel_restores_it(self):
        state = {'zero_shift_auto_deg': .2, 'zero_shift_visual_deg': .1, 'correct_zero': True}
        self.w.profile_states[self.a.id] = deepcopy(state)
        self.w._apply_zero_shift_display()
        item = self.w.plot_layers['observed'][0]
        self.assertAlmostEqual(item.pos().x(), -.3)
        dialog = self.open(); dialog.correction.setValue(.1)
        self.assertAlmostEqual(item.pos().x(), -.1, msg='Preview must use the same axis as Apply')
        dialog.reject()
        self.assertAlmostEqual(item.pos().x(), -.3)
        self.assertEqual(self.w.profile_states[self.a.id], state)

    def test_reopen_and_reset_return_to_precalibration_data(self):
        dialog = self.open(); dialog.correction.setValue(.15); dialog.apply_button.click()
        dialog = self.open()
        self.assertAlmostEqual(dialog.correction.value(), .15)
        dialog.reset_button.click()
        self.assertEqual(self.a.processed_points, self.original)
        self.assertEqual(self.a.angle_calibration_deg, 0.)

    def test_apply_same_value_does_not_add_a_second_shift(self):
        dialog = self.open(); dialog.correction.setValue(.12); dialog.apply_button.click()
        before = deepcopy(self.a.processed_points)
        dialog = self.open(); dialog.apply_button.click()
        self.assertEqual(self.a.processed_points, before)
        self.assertEqual(len(self.a.preprocessing_history), 1)

    def test_apply_invalidates_candidate_scores_from_previous_angles(self):
        self.w.candidate_table.set_rows([['COD', '123', 'SiO2', 'Reference', '', '88%', '12%', '~1.2']], lambda row: row)
        dialog = self.open(); dialog.correction.setValue(.2); dialog.apply_button.click()
        self.assertEqual(self.w.candidate_table.item(0, 5).text(), '')
        self.assertEqual(self.w.candidate_table.item(0, 6).text(), '')
        self.assertIn(self.w.candidate_table.score_display_text(0, 5), ('Not calculated', 'Inactive'))
        self.assertEqual(self.w.candidate_table.item(0, 1).text(), '123')

    def test_redraw_cancels_preview_and_stale_apply_cannot_edit_another_pattern(self):
        dialog = self.open(); dialog.correction.setValue(.4)
        self.w.project.patterns = [self.b, self.a]
        self.w.tree.set_project(self.w.project)
        self.w.tree.select_object('pattern', self.b.id)
        with patch.object(QMessageBox, 'information'):
            dialog.apply_button.click()
        self.assertEqual(self.a.processed_points, self.original)
        self.assertEqual(self.b.processed_points, [])

    def test_plot_redraw_closes_unapplied_editor(self):
        dialog = self.open(); dialog.correction.setValue(.2)
        self.w._draw_observed_patterns()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.a.processed_points, self.original)

    def test_accepted_profile_redraw_cancels_preview_before_replacing_layers(self):
        dialog = self.open(); dialog.correction.setValue(.2)
        self.w._recalculate_match_profile(active_only=True)
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(self.w._manual_calibration_dialog)
        self.assertEqual(self.a.processed_points, self.original)

    def test_disappearing_working_data_cancels_instead_of_applying_old_snapshot(self):
        dialog = self.open(); dialog.correction.setValue(.2)
        self.a.processed_points = []
        dialog.apply_button.click()
        self.assertIsNone(self.w._manual_calibration_dialog)
        self.assertEqual(self.a.processed_points, [])
        self.assertEqual(self.a.angle_calibration_deg, 0.)

    def test_compact_editor_does_not_clip_wrapped_instructions(self):
        for scale in (75,100,115,125,150):
            with self.subTest(ui_scale=scale):
                self.w.ui_scale_combo.setCurrentText(f'UI {scale}%')
                self.app.processEvents()
                dialog = self.open()
                for label in dialog.findChildren(QLabel):
                    if label.wordWrap():
                        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()),
                            (label.text(), dialog.size(), label.font().pixelSize(), self.w._ui_density_factor))
                self.assertTrue(dialog.rect().contains(dialog.apply_button.geometry().bottomRight()))
                dialog.reject()
                self.app.processEvents()

    def test_restore_original_resets_calibration_value(self):
        dialog = self.open(); dialog.correction.setValue(.2); dialog.apply_button.click()
        self.w._reset_observed_preprocessing()
        self.assertEqual(self.a.angle_calibration_deg, 0.)
        self.assertEqual(self.a.processed_points, [])

    def test_manual_lists_show_explanation_instead_of_creating_a_profile(self):
        self.a.input_kind = 'peak_list'; self.a.peak_points = [[30., 100.]]
        with patch.object(QMessageBox, 'information') as info:
            self.assertIsNone(self.open())
        info.assert_called_once()
        self.assertEqual(self.a.peak_points, [[30., 100.]])


if __name__ == '__main__':
    unittest.main()
