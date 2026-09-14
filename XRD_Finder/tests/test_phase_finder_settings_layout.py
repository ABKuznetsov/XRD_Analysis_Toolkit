from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QSizePolicy, QToolButton, QWidget

from xrd_finder.core.project import Project
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.finder_action_bar import FinderActionBar
from xrd_finder.ui.finder_plot_control_bar import FinderPlotControlBar, d_spacing_from_two_theta
from xrd_finder.ui.finder_top_toolbar import FinderTopToolBar
from xrd_finder.ui.phase_finder_menu import build_phase_finder_menu_bar


class PhaseFinderSettingsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_processing_panel_embeds_preprocessing_widget(self) -> None:
        bar = FinderActionBar()
        panel = QWidget()

        bar.show_preprocessing_panel("smooth", panel, "Smoothing")

        self.assertIs(bar.current_preprocessing_panel(), panel)
        self.assertIs(panel.parent(), bar.preprocessing_panel_host("smooth"))

    def test_opening_processing_panel_collapses_previous_section(self) -> None:
        bar = FinderActionBar()
        smoothing_section = next(
            button for button in bar.findChildren(QToolButton) if button.text() == "Smoothing"
        )
        background_section = next(
            button for button in bar.findChildren(QToolButton) if button.text() == "Background"
        )

        bar.show_preprocessing_panel("smooth", QWidget(), "Smoothing")
        bar.show_preprocessing_panel("background", QWidget(), "Background")

        self.assertFalse(smoothing_section.isChecked())
        self.assertTrue(background_section.isChecked())
        self.assertEqual(bar.current_preprocessing_key(), "background")

    def test_menu_actions_open_separate_settings_windows(self) -> None:
        class Owner(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.opened: list[str] = []

            def _show_plot_view_settings_window(self) -> None:
                self.opened.append("view")

            def _show_database_settings_window(self) -> None:
                self.opened.append("database")

            def _open_instrument_profile_editor(self, section: str = "identity") -> None:
                self.opened.append(f"instrument:{section}")

            def _search_pdf2_text(self) -> None:
                pass

            def _search_pdf2_candidates(self) -> None:
                pass

            def _add_selected_candidate_to_match_list(self) -> None:
                pass

            def _add_selected_cif_to_project(self) -> None:
                pass

            def _open_toolkit_catalog(self) -> None:
                pass

        owner = Owner()
        menu_bar = build_phase_finder_menu_bar(owner)
        view_menu = next(menu for menu in menu_bar._owned_menus if menu.title() == "View")
        database_menu = next(menu for menu in menu_bar._owned_menus if menu.title() == "Database")

        next(action for action in view_menu.actions() if action.text() == "Plot appearance...").trigger()
        next(action for action in database_menu.actions() if action.text() == "Database settings").trigger()

        self.assertEqual(owner.opened, ["view", "database"])

    def test_right_panel_keeps_only_work_tabs(self) -> None:
        window = PhaseFinderWindow(Project("Test project"), defer_initial_plot=True)
        try:
            titles = [window.right_tabs.tabText(index) for index in range(window.right_tabs.count())]
            self.assertEqual(titles, ["Elements", "Processing", "Card"])
            self.assertIs(window.cursor_status_panel, window.finder_plot_control_bar)
            self.assertIs(window.plot_area.layout().itemAt(1).widget(), window.finder_plot_control_bar)
        finally:
            window.close()

    def test_top_toolbar_is_compact_and_has_hot_actions(self) -> None:
        toolbar = FinderTopToolBar()
        self.assertLessEqual(toolbar.maximumHeight(), 40)
        self.assertGreater(toolbar.maximumHeight(), 0)
        self.assertEqual(toolbar.sizePolicy().verticalPolicy(), QSizePolicy.Policy.Fixed)

        expected_buttons = {
            "New",
            "Open",
            "Save",
            "Import",
            "Auto",
            "Reset data",
            "Reset view",
            "DB",
            "View",
            "Instr",
        }
        button_texts = {button.text() for button in toolbar.findChildren(type(toolbar.database_button))}

        self.assertEqual(button_texts, expected_buttons)
        self.assertIs(toolbar.layout().itemAt(0).widget(), toolbar.new_button)

    def test_plot_control_bar_owns_compact_pattern_display_controls(self) -> None:
        control_bar = FinderPlotControlBar()
        display_modes: list[str] = []
        aspect_modes: list[str] = []
        offsets: list[int] = []
        normalization: list[bool] = []
        control_bar.patternDisplayModeChanged.connect(display_modes.append)
        control_bar.plotAspectModeChanged.connect(aspect_modes.append)
        control_bar.patternOffsetPercentChanged.connect(offsets.append)
        control_bar.normalizePatternsChanged.connect(normalization.append)

        control_bar.pattern_display_mode.setCurrentText("All selected")
        control_bar.plot_aspect_mode.setCurrentText("16:9")
        control_bar.pattern_offset_slider.setValue(35)
        control_bar.normalize_patterns_checkbox.setChecked(True)

        self.assertEqual(control_bar.pattern_display_mode.itemText(0), "One")
        self.assertEqual(control_bar.pattern_display_mode.itemText(1), "All selected")
        self.assertIn("1:1", [control_bar.plot_aspect_mode.itemText(index) for index in range(control_bar.plot_aspect_mode.count())])
        self.assertIn("16:9", [control_bar.plot_aspect_mode.itemText(index) for index in range(control_bar.plot_aspect_mode.count())])
        self.assertEqual(control_bar.pattern_offset_value.text(), "35%")
        self.assertEqual(display_modes, ["All selected"])
        self.assertEqual(aspect_modes, ["16:9"])
        self.assertEqual(offsets, [35])
        self.assertEqual(normalization, [True])
        self.assertLess(
            control_bar.layout().indexOf(control_bar.pattern_display_mode),
            control_bar.layout().indexOf(control_bar.cursor_position_status_label),
        )

    def test_plot_control_bar_formats_cursor_position_and_d_spacing(self) -> None:
        control_bar = FinderPlotControlBar()

        control_bar.set_cursor_readout(two_theta=28.441, intensity=932.4, d_spacing=3.136)

        self.assertEqual(
            control_bar.cursor_position_status_label.text(),
            "2theta: 28.441 deg    I: 932    d: 3.136 A",
        )

    def test_cursor_d_spacing_uses_active_wavelength_and_bragg_law(self) -> None:
        self.assertAlmostEqual(
            d_spacing_from_two_theta(28.441, 1.5406),
            3.1357,
            places=3,
        )
        self.assertIsNone(d_spacing_from_two_theta(0.0, 1.5406))

    def test_top_toolbar_contains_commands_only(self) -> None:
        toolbar = FinderTopToolBar()

        self.assertFalse(hasattr(toolbar, "pattern_display_mode"))
        self.assertFalse(hasattr(toolbar, "pattern_offset_slider"))

    def test_plot_control_bar_does_not_show_scoring_status(self) -> None:
        control_bar = FinderPlotControlBar()

        self.assertFalse(hasattr(control_bar, "scoring_status_label"))

    def test_compact_format_selector_updates_plot_aspect(self) -> None:
        window = PhaseFinderWindow(Project("Test project"), defer_initial_plot=True)
        try:
            window.finder_plot_control_bar.plot_aspect_mode.setCurrentText("16:9")

            self.assertAlmostEqual(window.plot_view_settings.aspect_ratio, 16.0 / 9.0)
        finally:
            window.close()

    def test_processing_tab_no_longer_contains_auto_and_reset_actions(self) -> None:
        bar = FinderActionBar()
        button_texts = {button.text() for button in bar.findChildren(QPushButton)}
        section_texts = {button.text() for button in bar.findChildren(QToolButton)}

        self.assertIn("Smoothing", section_texts)
        self.assertIn("Background", section_texts)
        self.assertIn("Crop XRD", section_texts)
        self.assertIn("Instrument and radiation", section_texts)
        self.assertNotIn("Profile", section_texts)
        self.assertNotIn("Display", section_texts)
        self.assertNotIn("Smooth", button_texts)
        self.assertNotIn("Remove background", button_texts)
        self.assertNotIn("Crop XRD", button_texts)
        self.assertNotIn("Auto search", button_texts)
        self.assertNotIn("Reset data", button_texts)
        self.assertNotIn("Reset view", button_texts)

    def test_settings_windows_use_scrollable_resizable_layouts(self) -> None:
        window = PhaseFinderWindow(Project("Test project"), defer_initial_plot=True)
        try:
            window._database_tab = lambda: QWidget()
            window._show_database_settings_window()
            database_dialog = window._database_settings_dialog
            self.assertGreaterEqual(database_dialog.minimumWidth(), 760)
            self.assertGreaterEqual(database_dialog.minimumHeight(), 620)
            self.assertTrue(database_dialog.findChildren(QScrollArea))

            window._show_plot_view_settings_window()
            view_dialog = window._plot_view_settings_dialog
            self.assertGreaterEqual(view_dialog.minimumWidth(), 680)
            self.assertGreaterEqual(view_dialog.minimumHeight(), 620)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
