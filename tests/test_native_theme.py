"""Finder owns its widgets; only light/dark mode follows the operating system."""
import os
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('XRD_FINDER_DATA_DIR', tempfile.mkdtemp(prefix='xrd-native-test-'))
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget
from xrd_finder.ui.theme import theme_colors, window_style, SEARCH_MODE_COLORS, search_mode_button_style
from xrd_finder.ui.element_filter import element_state_style
from xrd_finder.ui.ui_density import UiDensity

class FinderThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.palette = self.app.palette()
        self.font = self.app.font()
        self.root = QWidget()

    def tearDown(self):
        self.root.close()
        self.app.setPalette(self.palette)
        self.app.setFont(self.font)
        self.root.deleteLater()

    def test_system_accent_does_not_replace_the_finder_skin(self):
        palette=QPalette(self.palette)
        palette.setColor(QPalette.Highlight,QColor('#ff00ff'))
        palette.setColor(QPalette.Base,QColor('#f3edda'))
        self.app.setPalette(palette)
        self.root.setStyleSheet(window_style(False))
        layout=QVBoxLayout(self.root);field=QLineEdit();button=QPushButton('Open')
        layout.addWidget(field);layout.addWidget(button)
        self.root.show();self.app.processEvents()
        self.assertEqual(field.palette().color(QPalette.Base).name(),'#ffffff')
        self.assertEqual(theme_colors(False)['bg'],'#f4f7fa')
        self.assertIn('background: #087f69',self.root.styleSheet())

    def test_semantic_colors_are_identical_in_light_and_dark_palettes(self):
        modes=dict(SEARCH_MODE_COLORS)
        elements=[element_state_style(s) for s in ('required','optional','excluded')]
        self.assertEqual({k:theme_colors(False)[k] for k in ('match','gain','warning')},
                         {k:theme_colors(True)[k] for k in ('match','gain','warning')})
        p=QPalette(self.palette);p.setColor(QPalette.Window,QColor('#101010'))
        self.app.setPalette(p)
        self.assertEqual(SEARCH_MODE_COLORS,modes)
        self.assertEqual([element_state_style(s) for s in ('required','optional','excluded')],elements)
        for background,_,_ in modes.values():self.assertIn(background,search_mode_button_style('QPushButton'))

    def test_finder_font_scales_reversibly_from_its_compact_base(self):
        self.root.setStyleSheet(window_style(False)+'\nQWidget { font-size: 13px; }')
        self.root.show();self.app.processEvents()
        density=UiDensity();density.apply(self.root,.8)
        self.assertEqual(self.root.font().pixelSize(),10)
        density.apply(self.root,1.)
        self.assertEqual(self.root.font().pixelSize(),13)
        native=QFont(self.font);native.setPointSizeF(24.);self.app.setFont(native)
        density.apply(self.root,.8)
        self.assertEqual(self.root.font().pixelSize(),10)

    def test_running_window_follows_light_dark_mode_without_changing_layout(self):
        from unittest.mock import patch
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QCoreApplication,QEvent,Qt
        from xrd_finder.core.project import Project
        from xrd_finder.ui.analysis_windows import PhaseFinderWindow
        palette=QPalette(self.palette);palette.setColor(QPalette.Window,QColor('#fafafa'))
        self.app.setPalette(palette)
        with patch.object(PhaseFinderWindow,'_start_match_pdf2_preload'):
            window=PhaseFinderWindow(Project('Appearance'),defer_initial_plot=True)
        try:
            window.resize(1280,720);window.show();QTest.qWait(100)
            ratios={k:list(v) for k,v in window._layout_state._splitter_proportions.items()}
            window.phase_colors={'USER:test':'#f4f7fa'}
            window.match_plot.setRange(xRange=(12.,14.),yRange=(10.,20.),padding=0)
            view_range=window.match_plot.viewRange()
            self.assertEqual(window.ccdc_doi_input.palette().color(QPalette.Base).name(),'#ffffff')
            for color,base in (('#101010','#111821'),('#fafafa','#ffffff')):
                palette.setColor(QPalette.Window,QColor(color));self.app.setPalette(palette);QTest.qWait(100)
                self.assertEqual(window.ccdc_doi_input.palette().color(QPalette.Base).name(),base)
                self.assertEqual(window._layout_state._splitter_proportions,ratios)
                self.assertEqual(window.font().pixelSize(),10)
                self.assertEqual((window.width(),window.height()),(1280,720))
                self.assertEqual(window.phase_colors,{'USER:test':'#f4f7fa'})
                self.assertEqual(window.match_plot.viewRange(),view_range)
                self.assertIn(theme_colors(color=='#101010')['panel'],window.compound_card.styleSheet())
                for button in window.finder_top_toolbar._buttons:
                    if button.isVisible() and button.toolButtonStyle()==Qt.ToolButtonStyle.ToolButtonTextBesideIcon:
                        self.assertGreaterEqual(button.width()+1,button.sizeHint().width(),button.text())
        finally:
            window._confirm_project_replacement=lambda:True
            window.close();window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_finder_widgets_retain_their_custom_skin(self):
        style=window_style()
        for selector in ('QComboBox::down-arrow','QCheckBox::indicator','QSlider::handle',
                         'QScrollBar::handle','QHeaderView::section','QMenu::item'):
            self.assertIn(selector,style)
        self.assertIn('font-size:',style)
