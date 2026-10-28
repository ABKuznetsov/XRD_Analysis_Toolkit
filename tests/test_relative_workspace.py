"""Panel/column proportions survive screen changes and constrained legacy imports."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('XRD_FINDER_OFFLINE', '1')
os.environ.setdefault('XRD_FINDER_DATA_DIR', tempfile.mkdtemp(prefix='xrd-relative-ui-'))

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtWidgets import QApplication, QSplitter, QWidget
from xrd_finder.core.project import Project
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.app_settings import app_settings
from xrd_finder.ui.candidate_tables import CandidateTableWidget, SelectedCandidatesTableWidget
from xrd_finder.ui.layout_state import SplitterLayoutState
from xrd_finder.ui.workspace_preferences import DEFAULT_SPLITTER_PROPORTIONS, normalized_proportions

REFERENCE = json.loads((Path(__file__).parent/'fixtures/workspace_start_layout.json').read_text())


class RelativeWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = app_settings()
        self.original = {key:self.settings.value(key) for key in self.settings.allKeys()}
        self.settings.clear()
        self.windows = []
        self.temp = tempfile.TemporaryDirectory(prefix='xrd-layout-settings-')
        self.addCleanup(self.temp.cleanup)

    def tearDown(self):
        for window in self.windows:
            window._confirm_project_replacement = lambda: True
            window.close(); window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.settings.clear()
        for key,value in self.original.items(): self.settings.setValue(key,value)
        self.settings.sync()

    def settle(self):
        end = time.monotonic()+.1
        while time.monotonic() < end:
            self.app.processEvents(); time.sleep(.005)

    def window(self, size=(1280,720)):
        with patch.object(PhaseFinderWindow, '_start_match_pdf2_preload'):
            window = PhaseFinderWindow(Project('Relative layout'), defer_initial_plot=True)
        self.windows.append(window)
        window.resize(*size); window.show(); self.settle()
        return window

    def assert_ratios(self, actual, expected, tolerance=.012):
        values = normalized_proportions(actual, len(expected))
        self.assertIsNotNone(values)
        for a,b in zip(values,expected): self.assertAlmostEqual(a,b,delta=tolerance)

    def test_initial_defaults_match_user_reference(self):
        for name, expected in REFERENCE['splitters'].items():
            self.assert_ratios(DEFAULT_SPLITTER_PROPORTIONS[name], expected, 1.e-8)

    def test_fresh_hd_and_2k_actual_panels_match_reference(self):
        w = self.window()
        for size in ((1280,720),(1366,768),(2560,1440),(1280,720)):
            w.resize(*size); self.settle()
            with self.subTest(size=size):
                self.assert_ratios(w.main_splitter.sizes(), REFERENCE['splitters']['main_splitter'])
                self.assert_ratios(w.center_splitter.sizes(), REFERENCE['splitters']['center_splitter'], .02)
                self.assert_ratios(w.composition_panel.splitter.sizes(), REFERENCE['splitters']['composition_splitter'], .025)

    def test_saved_wide_sidebar_is_not_clamped_to_a_pixel_maximum_at_2k(self):
        self.settings.setValue('ui/workspace_view_v1', json.dumps({'splitters':{'main_splitter':[.20,.50,.30]}}))
        w = self.window()
        for size in ((1280,720),(2560,1440),(1366,768)):
            w.resize(*size); self.settle()
            self.assert_ratios(w.main_splitter.sizes(), (.20,.50,.30))

    def test_user_can_drag_sidebar_beyond_old_360_pixel_cap_on_2k(self):
        w = self.window((2560,1440))
        w._layout_state.set_pinned(False)
        w.main_splitter.moveSplitter(round(w.main_splitter.width()*.25),1)
        self.settle()
        fraction = w.main_splitter.sizes()[0]/sum(w.main_splitter.sizes())
        self.assertAlmostEqual(fraction,.25,delta=.012)

    def test_save_keeps_one_normalized_record_without_native_splitter_writers(self):
        w = self.window()
        w._layout_state.set_pinned(True)
        w._save_workspace_preferences()
        data = json.loads(self.settings.value('ui/workspace_view_v1'))
        for name, values in data['splitters'].items():
            self.assertAlmostEqual(sum(values),1.)
            self.assertTrue(all(0 < v < 1 for v in values))
            self.assertFalse(self.settings.contains('layout/'+name))
        for name in ('candidates','accepted'):
            self.assertAlmostEqual(sum(data['tables'][name]['proportions']),1.)
            self.assertFalse(self.settings.contains('layout/tables/'+name))

    def test_old_json_pixel_weights_normalize_without_becoming_current_pixel_sizes(self):
        self.settings.setValue('ui/workspace_view_v1', json.dumps({'splitters':{'main_splitter':[400,1000,600]}}))
        w = self.window((2560,1440))
        w._save_workspace_preferences()
        data = json.loads(self.settings.value('ui/workspace_view_v1'))
        self.assert_ratios(data['splitters']['main_splitter'], (.2,.5,.3), 1.e-8)
        w.resize(1280,720); self.settle(); w._save_workspace_preferences()
        self.assert_ratios(json.loads(self.settings.value('ui/workspace_view_v1'))['splitters']['main_splitter'], (.2,.5,.3), 1.e-8)

    def test_native_pixel_migration_uses_original_ratios_before_target_constraints(self):
        source = QSplitter(Qt.Horizontal)
        for _ in range(3): source.addWidget(QWidget())
        source.resize(2000,200); source.setSizes([400,1000,600])
        original = normalized_proportions(source.sizes(),3)
        settings = QSettings(str(Path(self.temp.name)/'legacy.ini'), QSettings.IniFormat)
        settings.setValue('layout/main_splitter', source.saveState())
        target = QSplitter(Qt.Horizontal)
        for _ in range(3):
            panel = QWidget(); panel.setMinimumWidth(300); target.addWidget(panel)
        target.resize(910,200)
        state = SplitterLayoutState(settings, names=('main_splitter',))
        state.register('main_splitter',target)
        state.restore()
        self.assert_ratios(state._splitter_proportions['main_splitter'], original, .002)
        target.resize(2200,200); state.apply_proportions()
        self.assert_ratios(target.sizes(), original, .002)
        state.save()
        self.assertFalse(settings.contains('layout/main_splitter'))
        source.deleteLater(); target.deleteLater()

    def test_invalid_legacy_native_state_falls_back_without_raising(self):
        settings = QSettings(str(Path(self.temp.name)/'invalid.ini'),QSettings.IniFormat)
        settings.setValue('layout/main_splitter','not a native QByteArray')
        splitter = QSplitter(Qt.Horizontal)
        for _ in range(3): splitter.addWidget(QWidget())
        state = SplitterLayoutState(settings,names=('main_splitter',))
        state.register('main_splitter',splitter)
        state.restore()
        self.assert_ratios(state._splitter_proportions['main_splitter'],REFERENCE['splitters']['main_splitter'],1.e-8)
        splitter.deleteLater()

    def test_table_defaults_do_not_depend_on_construction_viewport(self):
        for cls,args,expected in (
            (CandidateTableWidget,([],),REFERENCE['tables']['candidates']['proportions']),
            (SelectedCandidatesTableWidget,(),REFERENCE['tables']['accepted']['proportions']),
        ):
            table = cls(*args)
            table.resize(100,150)
            table.set_column_layout_editable(True)
            self.assert_ratios(table.column_layout_proportions(),expected,1.e-8)
            table.resize(900,300); table.show(); self.settle()
            self.assert_ratios([table.columnWidth(i) for i in range(table.columnCount())],expected,.004)
            table.close(); table.deleteLater()

    def test_dense_hd_keeps_accepted_column_fractions_instead_of_a_fixed_pixel_floor(self):
        w = self.window((640,360))
        expected = REFERENCE['tables']['accepted']['proportions']
        self.assert_ratios([w.match_table.columnWidth(i) for i in range(w.match_table.columnCount())],expected,.015)

    def test_candidate_table_minimum_height_does_not_override_saved_panel_fraction(self):
        w = self.window()
        expected = REFERENCE['splitters']['center_splitter']
        for size in ((1280,720),(1600,900),(640,360)):
            w.resize(*size); self.settle()
            self.assert_ratios(w.center_splitter.sizes(),expected,2/sum(w.center_splitter.sizes()))

    def test_custom_column_order_and_fractions_survive_lock_and_restart(self):
        w = self.window((2560,1440))
        w._layout_state.set_pinned(False)
        w.candidate_table.horizontalHeader().moveSection(3,1)
        w.candidate_table.horizontalHeader().resizeSection(3,300)
        self.settle()
        before = w.candidate_table.column_layout_state()
        w._layout_state.set_pinned(True)
        w._save_workspace_preferences()
        other = self.window((1280,720))
        self.assertEqual(other.candidate_table.column_layout_state()['order'],before['order'])
        self.assert_ratios(other.candidate_table.column_layout_proportions(),before['proportions'],1.e-8)

    def test_loading_candidates_and_phases_does_not_replace_locked_column_fractions(self):
        self.settings.setValue('layout/pinned',True)
        w = self.window()
        before = {name:table.column_layout_state() for name,table in w._layout_state._tables.items()}
        w.candidate_table.set_rows([['COD','1234567','BaSiO3','A long reference phase name','P 21/c','90%','','~1.2']],lambda row:row)
        w.match_table.set_rows([['#d93025','A long accepted phase','fit 90% (20/25)','100.0','~1.2']])
        self.settle()
        for size in ((2560,1440),(1280,720)):
            w.resize(*size); self.settle()
            for name,table in w._layout_state._tables.items():
                self.assertEqual(table.column_layout_state()['order'],before[name]['order'])
                self.assert_ratios(table.column_layout_proportions(),before[name]['proportions'],1.e-8)

    def test_user_drag_is_saved_as_fractions_and_survives_repeated_resize(self):
        w = self.window()
        w._layout_state.set_pinned(False)
        w.main_splitter.moveSplitter(round(w.main_splitter.width()*.18),1)
        self.settle()
        expected = normalized_proportions(w.main_splitter.sizes(),3)
        w._layout_state.set_pinned(True)
        for size in ((2560,1440),(1280,720),(1920,1080),(1366,768)):
            w.resize(*size); self.settle()
            self.assert_ratios(w.main_splitter.sizes(),expected)
        w._save_workspace_preferences()
        other = self.window((2560,1440))
        self.assert_ratios(other.main_splitter.sizes(),expected)


if __name__ == '__main__':
    unittest.main()
