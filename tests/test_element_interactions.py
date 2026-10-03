from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.element_filter import PeriodicTableWidget, element_state_style
from xrd_finder.ui.candidate_tables import CandidateTableWidget
from xrd_finder.services.candidate_search_service import CandidateSearchService


class ElementInteractionTests(unittest.TestCase):
    def test_absent_element_filters_candidates_without_required_elements(self):
        self.assertFalse(PhaseFinderWindow._candidate_formula_matches_gate(
            "CaSiO3", "COD", set(), set(), excluded={"Ca"}, strict=False
        ))
        self.assertTrue(PhaseFinderWindow._candidate_formula_matches_gate(
            "SiO2", "COD", set(), set(), excluded={"Ca"}, strict=False
        ))

    def test_old_optional_project_elements_restore_as_green_allowed(self):
        shown_states = {}
        table = SimpleNamespace(
            set_element_state=lambda element, state: shown_states.update({element: state})
        )
        window = SimpleNamespace(
            element_table=table,
            _element_symbols=lambda: ["Ca", "Al", "Si"],
            _update_element_fields=lambda: None,
            search_input=None,
            name_input=None,
            formula_sum_input=None,
            ccdc_doi_input=None,
            inorganics_checkbox=None,
            organics_checkbox=None,
            structural_data_checkbox=None,
            reference_patterns_checkbox=None,
            rank_by_probability_checkbox=None,
        )
        state = SimpleNamespace(
            element_states={"Ca": "required", "Al": "optional"},
            selected_elements={"Ca"},
            selected_element_order=["Ca"],
            exclude_all_other_elements=True,
            search_text="",
            name_text="",
            formula_text="",
            ccdc_doi_text="",
            inorganics_checked=True,
            organics_checked=False,
            structural_data_checked=True,
            reference_patterns_checked=False,
            rank_by_probability_checked=True,
        )

        PhaseFinderWindow._restore_filter_state(window, state)

        self.assertEqual(window.element_states, {"Ca": "required", "Si": "excluded"})
        self.assertEqual(shown_states, {"Ca": "required", "Al": "neutral", "Si": "excluded"})

    def test_drag_can_clear_multiple_selected_elements_in_one_update(self):
        states = {"Ca": "required", "Sc": "required"}
        updates = []

        def set_state(element, state):
            if state == "neutral":
                states.pop(element, None)
            else:
                states[element] = state

        window = SimpleNamespace(
            _set_element_state=set_state,
            _update_element_fields=lambda: updates.append(True),
        )
        PhaseFinderWindow._paint_elements(window, ["Ca", "Sc"], "neutral")
        self.assertEqual(states, {})
        self.assertEqual(len(updates), 1)

    def test_mode_button_is_inside_periodic_table_and_updates_label(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        button = table.mode_button
        self.assertIs(button.parentWidget(), table)
        self.assertEqual(button.text(), "Element absent")
        self.assertIn("#9b1b59", button.styleSheet())
        table.set_excluded_mode(False)
        self.assertEqual(button.text(), "Element absent")
        self.assertIn("#9b1b59", button.styleSheet())
        table.set_excluded_mode(True)
        self.assertEqual(button.text(), "May be present")
        self.assertIn("#0f8a75", button.styleSheet())
        table.deleteLater()
        app.processEvents()

    def test_mode_switch_restores_only_gray_elements_to_no(self):
        states = {"Ca": "required", "Al": "optional", "Si": "excluded", "Zr": "excluded"}

        def set_state(element, state):
            if state == "neutral":
                states.pop(element, None)
            else:
                states[element] = state

        window = SimpleNamespace(
            element_states=states,
            exclude_all_other_elements=True,
            _element_symbols=lambda: ["Ca", "Al", "Si", "Zr"],
            _set_element_state=set_state,
            _update_element_fields=lambda: None,
        )
        window._clear_excluded_elements = lambda: PhaseFinderWindow._clear_excluded_elements(window)
        window._restore_excluded_elements = lambda: PhaseFinderWindow._restore_excluded_elements(window)

        PhaseFinderWindow._toggle_excluded_mode(window)
        self.assertEqual(states, {"Ca": "required", "Al": "optional"})
        self.assertFalse(window.exclude_all_other_elements)

        PhaseFinderWindow._toggle_excluded_mode(window)
        self.assertEqual(states, {
            "Ca": "required", "Al": "optional", "Si": "excluded", "Zr": "excluded"
        })
        self.assertTrue(window.exclude_all_other_elements)

    def test_single_click_returns_blue_to_gray_in_not_selected_mode(self):
        states = {"Ca": "required", "Al": "optional"}

        def set_state(element, state):
            if state == "neutral":
                states.pop(element, None)
            else:
                states[element] = state

        window = SimpleNamespace(
            element_states=states,
            exclude_all_other_elements=False,
            _set_element_state=set_state,
            _update_element_fields=lambda: None,
            _element_symbols=lambda: ["Ca", "Al", "Si"],
        )

        PhaseFinderWindow._toggle_required_element(window, "Ca")

        self.assertNotIn("Ca", states)
        self.assertEqual(states["Al"], "optional")
        self.assertFalse(window.exclude_all_other_elements)

    def test_relaxed_auto_filter_keeps_gray_formula_components(self):
        app = QApplication.instance() or QApplication([])
        table = CandidateTableWidget([
            ["COD", "1", "CaSiO3", "A", "", "", "", ""],
            ["COD", "2", "SiO2", "B", "", "", "", ""],
        ])
        window = SimpleNamespace(
            candidate_table=table,
            selected_elements={"Ca"},
            element_states={"Ca": "required"},
            exclude_all_other_elements=False,
        )

        PhaseFinderWindow._apply_candidate_element_filter(window)

        self.assertFalse(table.isRowHidden(0))
        self.assertTrue(table.isRowHidden(1))
        table.deleteLater()
        app.processEvents()

    def test_relaxed_gate_retains_candidates_with_gray_elements(self):
        options = SimpleNamespace(
            required_elements=["Ca"], optional_elements=["Al"],
            excluded_elements=["Zr"], restrict_to_selected_elements=False,
            material_class_allowed=lambda formula: True,
        )
        rows = [
            ["COD", "1", "CaSiO3", "A", "", ""],
            ["COD", "2", "CaZrSiO5", "B", "", ""],
            ["COD", "3", "SiO2", "C", "", ""],
        ]
        filtered = CandidateSearchService.filter_candidate_rows_by_excluded_elements(
            None, rows, options
        )
        self.assertEqual([row[1] for row in filtered], ["1"])

    def test_clear_no_keeps_blue_and_green_and_allows_gray_elements(self):
        states = {"Ca": "required", "Al": "optional", "Zr": "excluded", "Si": "excluded"}
        changed = []

        def set_state(element, state):
            changed.append((element, state))
            if state == "neutral":
                states.pop(element, None)
            else:
                states[element] = state

        window = SimpleNamespace(
            element_states=states,
            exclude_all_other_elements=True,
            _element_symbols=lambda: ["Ca", "Al", "Zr", "Si"],
            _set_element_state=set_state,
            _update_element_fields=lambda: changed.append(("updated", "")),
        )

        PhaseFinderWindow._clear_excluded_elements(window)

        self.assertEqual(states, {"Ca": "required", "Al": "optional"})
        self.assertFalse(window.exclude_all_other_elements)
        self.assertEqual(changed[-1], ("updated", ""))
        self.assertEqual(changed.count(("updated", "")), 1)
        self.assertTrue(PhaseFinderWindow._candidate_formula_matches_gate(
            "CaSiO3", "COD", {"Ca"}, {"Al"}, excluded=set(), strict=False
        ))

    def test_drag_paints_each_crossed_element_once(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        table.resize(900, 300)
        table.show()
        app.processEvents()
        painted = []
        clicked = []
        table.elementsPainted.connect(lambda elements, state: painted.append((elements, state)))
        table.leftClicked.connect(clicked.append)
        start = table._buttons["Ca"]
        middle = table._buttons["Sc"]
        end = table._buttons["Ti"]

        QTest.mousePress(start, Qt.MouseButton.LeftButton)
        self.assertEqual(start.styleSheet(), element_state_style("required"))
        for target in (middle, end):
            local = start.mapFromGlobal(target.mapToGlobal(target.rect().center()))
            QTest.mouseMove(start, local)
            self.assertEqual(target.styleSheet(), element_state_style("required"))
        QTest.mouseRelease(start, Qt.MouseButton.LeftButton,
                           pos=start.mapFromGlobal(end.mapToGlobal(end.rect().center())))

        self.assertEqual(painted, [(["Ca", "Sc", "Ti"], "required")])
        self.assertEqual(clicked, [])
        table.close()
        table.deleteLater()

    def test_drag_backtrack_restores_cells_before_release(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        table.resize(900, 300)
        table.show()
        app.processEvents()
        painted = []
        table.elementsPainted.connect(lambda elements, state: painted.append((elements, state)))
        start = table._buttons["Ca"]
        middle = table._buttons["Sc"]
        end = table._buttons["Ti"]
        QTest.mousePress(start, Qt.MouseButton.LeftButton)
        for target in (middle, end, middle):
            pos = start.mapFromGlobal(target.mapToGlobal(target.rect().center()))
            QTest.mouseMove(start, pos)
        self.assertEqual(end.styleSheet(), element_state_style("neutral"))
        QTest.mouseRelease(start, Qt.MouseButton.LeftButton, pos=pos)
        self.assertEqual(painted, [(["Ca", "Sc"], "required")])
        table.close()
        table.deleteLater()

    def test_drag_backtrack_restores_selected_cell_while_erasing(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        table.resize(900, 300)
        table.show()
        app.processEvents()
        table.set_excluded_mode(True)
        for symbol in ("Ca", "Sc", "Ti"):
            table.set_element_state(symbol, "required")
        painted = []
        table.elementsPainted.connect(lambda elements, state: painted.append((elements, state)))
        start = table._buttons["Ca"]
        middle = table._buttons["Sc"]
        end = table._buttons["Ti"]
        QTest.mousePress(start, Qt.MouseButton.LeftButton)
        for target in (middle, end, middle):
            pos = start.mapFromGlobal(target.mapToGlobal(target.rect().center()))
            QTest.mouseMove(start, pos)
        self.assertEqual(end.styleSheet(), element_state_style("required"))
        QTest.mouseRelease(start, Qt.MouseButton.LeftButton, pos=pos)
        self.assertEqual(painted, [(["Ca", "Sc"], "neutral")])
        table.close()
        table.deleteLater()

    def test_color_legend_explains_three_element_states(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        self.assertEqual(
            [label.text() for label in table._legend_labels],
            ["Required", "May be present", "Element absent"],
        )
        self.assertEqual(
            [swatch.text() for swatch in table._legend_swatches],
            ["H", "H", "H"],
        )
        for swatch, color in zip(table._legend_swatches, ("#315f92", "#0f8a75", "#9b1b59")):
            self.assertIn(color, swatch.styleSheet())
        table.deleteLater()
        app.processEvents()

    def test_new_table_starts_with_green_allowed_elements(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        self.assertFalse(table._excluded_mode)
        self.assertEqual(table.mode_button.text(), "Element absent")
        self.assertIn("#9b1b59", table.mode_button.styleSheet())
        self.assertEqual(table._element_states["H"], "neutral")
        self.assertIn("#0f8a75", table._buttons["H"].styleSheet())
        table.deleteLater()
        app.processEvents()

    def test_right_click_toggles_allowed_and_absent(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        states = []
        table.rightClicked.connect(states.append)

        button = table._buttons["H"]
        QTest.mouseClick(button, Qt.MouseButton.RightButton)

        self.assertEqual(states, ["H"])
        self.assertEqual(button.styleSheet(), element_state_style("excluded"))
        table.deleteLater()
        app.processEvents()

    def test_default_filter_uses_unselected_mode(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        states = {}
        window = SimpleNamespace(
            element_states=states,
            selected_element_order=[],
            exclude_all_other_elements=True,
            _element_symbols=lambda: ["H", "He"],
            _set_element_state=lambda element, state: (states.pop(element, None) if state == "neutral" else states.update({element: state})),
            _update_element_fields=lambda: None,
            inorganics_checkbox=None,
            organics_checkbox=None,
            structural_data_checkbox=None,
            reference_patterns_checkbox=None,
        )
        PhaseFinderWindow._apply_default_phase_filter(window)
        self.assertFalse(window.exclude_all_other_elements)
        self.assertEqual(states, {})
        table.deleteLater()
        app.processEvents()

    def test_drag_from_selected_elements_removes_highlight_immediately(self):
        app = QApplication.instance() or QApplication([])
        table = PeriodicTableWidget()
        table.resize(900, 300)
        table.show()
        app.processEvents()
        table.set_excluded_mode(True)
        for symbol in ("Ca", "Sc"):
            table.set_element_state(symbol, "required")
        painted = []
        table.elementsPainted.connect(lambda elements, state: painted.append((elements, state)))
        start = table._buttons["Ca"]
        end = table._buttons["Sc"]

        QTest.mousePress(start, Qt.MouseButton.LeftButton)
        self.assertEqual(start.styleSheet(), element_state_style("neutral"))
        end_pos = start.mapFromGlobal(end.mapToGlobal(end.rect().center()))
        QTest.mouseMove(start, end_pos)
        self.assertEqual(end.styleSheet(), element_state_style("neutral"))
        QTest.mouseRelease(start, Qt.MouseButton.LeftButton, pos=end_pos)
        self.assertEqual(painted, [(["Ca", "Sc"], "neutral")])

        table.set_excluded_mode(False)
        for symbol in ("Ca", "Sc"):
            table.set_element_state(symbol, "required")
        QTest.mousePress(start, Qt.MouseButton.LeftButton)
        QTest.mouseMove(start, end_pos)
        self.assertEqual(end.styleSheet(), element_state_style("neutral"))
        QTest.mouseRelease(start, Qt.MouseButton.LeftButton, pos=end_pos)
        self.assertEqual(painted[-1], (["Ca", "Sc"], "neutral"))
        table.close()
        table.deleteLater()


if __name__ == "__main__":
    unittest.main()
