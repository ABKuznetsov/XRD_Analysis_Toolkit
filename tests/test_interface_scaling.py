"""Small-screen layout and panel access use real Qt widgets."""
import os, tempfile, unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('XRD_FINDER_OFFLINE', '1')
if 'XRD_FINDER_DATA_DIR' not in os.environ:
    os.environ['XRD_FINDER_DATA_DIR'] = tempfile.mkdtemp(prefix='xrd-compact-')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from xrd_finder.core.project import Project
from xrd_finder.ui.analysis_windows import PhaseFinderWindow

class InterfaceScalingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from xrd_finder.ui.app_settings import app_settings
        app_settings().remove('ui/workspace_view_v1')
        with patch.object(PhaseFinderWindow, '_start_match_pdf2_preload'):
            self.window = PhaseFinderWindow(Project('Very long project name ' * 20), defer_initial_plot=True)

    def tearDown(self):
        self.window._confirm_project_replacement = lambda: True
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def settle(self):
        QTest.qWait(100)

    def test_long_status_and_cursor_fit_hd_at_200_percent_logical_size(self):
        w = self.window
        w.resize(640, 360)
        w.show()
        self.settle()
        w._set_background_status('Long diagnostic ' * 150)
        w.candidate_search_detail_label.setText('Found and prepared ' * 100)
        w.cursor_status_panel.set_cursor_readout(two_theta=179.999, intensity=123456789, d_spacing=9876.543)
        self.settle()
        self.assertLessEqual(w.width(), 640)
        self.assertLessEqual(w.height(), 360)

    def test_wrapped_plot_controls_remain_inside_their_panel(self):
        w = self.window
        w.resize(640, 360)
        w.show()
        self.settle()
        bar = w.cursor_status_panel
        for control in [bar.pattern_display_mode, bar.plot_aspect_mode, bar.normalize_patterns_checkbox, bar.pattern_offset_slider, bar.correct_zero_checkbox]:
            p = control.mapTo(bar, QPoint(control.width() - 1, control.height() - 1))
            self.assertLess(p.x(), bar.width())
            self.assertLess(p.y(), bar.height())

    def test_settings_dialogs_fit_compact_parent_and_keep_scroll_access(self):
        from PySide6.QtWidgets import QDialog, QScrollArea
        from xrd_finder.ui.instrument_profile_dialog import InstrumentProfileDialog
        from xrd_finder.instrument.models import InstrumentProfile
        from xrd_finder.ui.preprocessing_dialogs import SmoothDialog, BackgroundRemovalDialog
        w = self.window
        w.resize(640, 360)
        w.show()
        self.settle()
        w._show_database_settings_window()
        w._show_plot_view_settings_window()
        dialogs = [w._database_settings_dialog, w._plot_view_settings_dialog, InstrumentProfileDialog(InstrumentProfile.default_cu_kalpha(), parent=w), SmoothDialog(9, parent=w), BackgroundRemovalDialog(parent=w)]
        for dialog in dialogs:
            with self.subTest(dialog=dialog.windowTitle()):
                dialog.show()
                self.settle()
                self.assertLessEqual(dialog.width(), 640)
                self.assertLessEqual(dialog.height(), 360)
                self.assertTrue(dialog.findChildren(QScrollArea), 'Large settings require scroll access')
                dialog.close()

    def test_edit_layout_is_pressed_to_unlock_and_released_to_save_and_lock(self):
        w = self.window
        w.resize(1500, 950)
        w.show()
        self.settle()
        button = w._layout_state.pin_button
        self.assertEqual(button.text(), 'Edit layout')
        button.setChecked(True)
        self.settle()
        self.assertFalse(w._layout_state.pinned)
        self.assertTrue(w.main_splitter.handle(1).isEnabled())
        w.main_splitter.moveSplitter(round(w.main_splitter.width()*.20), 1)
        self.settle()
        expected = [value/sum(w.main_splitter.sizes()) for value in w.main_splitter.sizes()]
        button.setChecked(False)
        self.settle()
        self.assertTrue(w._layout_state.pinned)
        self.assertFalse(w.main_splitter.handle(1).isEnabled())
        import json
        saved = json.loads(w.settings.value('ui/workspace_view_v1'))['splitters']['main_splitter']
        self.assertAlmostEqual(sum(saved), 1.)
        for actual, desired in zip(saved, expected):
            self.assertAlmostEqual(actual, desired)
        self.assertIsNone(w.settings.value('layout/main_splitter'))

    def test_ui_scale_and_plot_format_fonts_restore_without_saving_axis_range(self):
        import json
        w = self.window
        w.resize(1500, 950)
        w.show()
        self.settle()
        w.ui_scale_combo.setCurrentText('UI 115%')
        w.plot_view_settings.aspect_ratio = 16 / 9
        w.plot_view_settings.label_font_size = 17
        w.match_plot.setRange(xRange=(12, 14), yRange=(1, 2), padding=0)
        w._save_workspace_preferences()
        data = json.loads(w.settings.value('ui/workspace_view_v1'))
        self.assertNotIn('view_range', data)
        with patch.object(PhaseFinderWindow, '_start_match_pdf2_preload'):
            other = PhaseFinderWindow(Project('Restore'), defer_initial_plot=True)
        try:
            self.assertEqual(other.ui_scale_combo.currentText(), 'UI 115%')
            self.assertEqual(other.plot_view_settings.aspect_ratio, 16 / 9)
            self.assertEqual(other.plot_view_settings.label_font_size, 17)
        finally:
            other._confirm_project_replacement = lambda: True
            other.close()
            other.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_initial_plot_callbacks_do_not_outlive_an_unshown_window(self):
        import shiboken6
        calls = []

        def guarded(name, original):

            def callback(window, *args, **kwargs):
                alive = shiboken6.isValid(window)
                calls.append((name, alive))
                if alive:
                    return original(window, *args, **kwargs)
            return callback
        a = PhaseFinderWindow._apply_saved_plot_view_settings
        b = PhaseFinderWindow._apply_plot_view_aspect
        with patch.object(PhaseFinderWindow, '_apply_saved_plot_view_settings', guarded('settings', a)), patch.object(PhaseFinderWindow, '_apply_plot_view_aspect', guarded('aspect', b)), patch.object(PhaseFinderWindow, '_start_match_pdf2_preload'):
            w = PhaseFinderWindow(Project('Unshown'), defer_initial_plot=True)
            w._confirm_project_replacement = lambda: True
            w.close()
            w.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertFalse([name for name, alive in calls if not alive], calls)

    def test_fixed_plot_formats_fit_the_allocated_compact_canvas(self):
        w = self.window
        w.resize(640, 360)
        w.show()
        self.settle()
        for mode in ('1:1', '16:9', 'Fit'):
            with self.subTest(mode=mode):
                w._set_plot_aspect_mode(mode)
                self.settle()
                plot = w.match_plot
                canvas = w.plot_canvas
                point = plot.mapTo(canvas, QPoint(plot.width() - 1, plot.height() - 1))
                self.assertLess(point.x(), canvas.width())
                self.assertLess(point.y(), canvas.height())
                if mode != 'Fit':
                    wanted = 1 if mode == '1:1' else 16 / 9
                    self.assertLess(abs(plot.width() / plot.height() - wanted), 0.04)

    def test_analysis_scroll_does_not_expand_periodic_table_horizontally(self):
        w = self.window
        w.resize(1366, 768)
        w.show()
        self.settle()
        self.assertLessEqual(w.composition_panel.width(), w.right_tabs.width())
        for symbol in ('He', 'Og', 'Lu', 'Lr'):
            cell = w.element_table._buttons[symbol]
            p = cell.mapTo(w.right_tabs, QPoint(cell.width() - 1, 0))
            self.assertLess(p.x(), w.right_tabs.width())

    def test_proportional_font_and_widget_metrics_restore(self):
        w=self.window
        w.resize(1600,900);w.show();self.settle()
        original=w.plot_view_settings.label_font_size
        self.assertEqual(w.font().pixelSize(),13)
        self.assertEqual(w.finder_top_toolbar.height(),56)
        w.resize(1280,720);self.settle()
        self.assertEqual(w.font().pixelSize(),10)
        self.assertEqual(w.finder_top_toolbar.height(),45)
        self.assertEqual(w.plot_view_settings.label_font_size,original)
        w.resize(1600,900);self.settle()
        self.assertEqual(w.font().pixelSize(),13)
        self.assertEqual(w.finder_top_toolbar.height(),56)

    def test_main_workspace_stays_fixed_at_hd_with_200_percent_logical_size(self):
        w=self.window;w.resize(640,360);w.show();self.settle()
        self.assertFalse(hasattr(w,'workspace_buttons'))
        self.assertFalse(hasattr(w,'workspace_actions'))
        self.assertLessEqual(w.width(),640);self.assertLessEqual(w.height(),360)
        for panel in (w.sidebar,w.center,w.right_tabs,w.plot_area,w.candidate_panel):
            self.assertTrue(panel.isVisible())
            point=panel.mapTo(w,QPoint(panel.width()-1,panel.height()-1))
            self.assertLess(point.x(),w.width());self.assertLess(point.y(),w.height())
        for side in ('left','bottom'):
            axis=w.match_plot.getAxis(side)
            self.assertTrue(axis.label.isVisible())
            self.assertTrue(axis.label.toPlainText().strip())

    def test_layout_and_help_follow_instrument_in_the_toolbar(self):
        w=self.window;w.resize(1600,900);w.show();self.settle()
        bar=w.finder_top_toolbar
        layout=bar._groups[-1].layout()
        controls=[layout.itemAt(i).widget() for i in range(layout.count())]
        self.assertEqual(controls,[bar.database_button,bar.view_button,bar.instrument_button,bar.layout_button,bar.help_button])
        self.assertEqual(bar.layout_button.text(),'Edit layout')
        self.assertEqual(bar.help_button.text(),'Help')

    def test_periodic_cells_and_gaps_fit_the_scaled_panel(self):
        w=self.window;w.resize(1600,900);w.show();self.settle()
        grid=w.element_table._grid
        original=(grid.horizontalSpacing(),grid.verticalSpacing())
        w.resize(640,360);self.settle()
        density=w._ui_density_factor
        self.assertEqual(grid.horizontalSpacing(),round(original[0]*density))
        self.assertEqual(grid.verticalSpacing(),round(original[1]*density))
        for symbol in ('H','He','Og','Lu','Lr'):
            cell=w.element_table._buttons[symbol]
            point=cell.mapTo(w.element_table,QPoint(cell.width(),cell.height()))
            self.assertGreater(cell.width(),0)
            self.assertGreater(cell.height(),0)
            self.assertLessEqual(point.x(),w.element_table.width())
            self.assertLessEqual(point.y(),w.element_table.height())

    def test_manual_ui_fine_tuning_keeps_the_hd_workspace_inside_window(self):
        w=self.window;w.resize(640,360);w.show();self.settle()
        for value in (75,100,125,150):
            with self.subTest(scale=value):
                w.ui_scale_combo.setCurrentText(f'UI {value}%');self.settle()
                for panel in (w.sidebar,w.center,w.right_tabs,w.plot_area,w.candidate_panel):
                    point=panel.mapTo(w,QPoint(panel.width()-1,panel.height()-1))
                    self.assertLess(point.x(),w.width());self.assertLess(point.y(),w.height())
