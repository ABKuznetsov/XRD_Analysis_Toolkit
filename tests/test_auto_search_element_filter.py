from __future__ import annotations

import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.candidate_search_actions import PhaseFinderCandidateSearchActionsMixin
from xrd_finder.ui.candidate_tables import CandidateTableWidget


class SearchServiceProbe:
    def __init__(self):
        self.calls = []

    def search_elements(self, elements, options, **kwargs):
        self.calls.append((list(elements), options))
        return []


class SearchWindowProbe:
    def __init__(self):
        self.selected_element_order = ["Ca", "Si", "O"]
        self.candidate_search_service = SearchServiceProbe()
        self.options = SimpleNamespace(
            local_sources=["USER", "COD", "MP"],
            required_elements=["Ca", "Si", "O"],
            optional_elements=["Al"],
            excluded_elements=["Fe", "Zr"],
            cod_online_enabled=True,
            materials_project_enabled=True,
            aflow_enabled=True,
            oqmd_enabled=True,
            rruff_enabled=True,
            match_pdf2_enabled=True,
        )

    def _active_pattern(self):
        return object()

    def _probability_observed_data(self):
        return [], [], [SimpleNamespace(two_theta=30.0)]

    def _observed_record_position(self, record):
        return record.two_theta

    def _candidate_search_options(self):
        return self.options

    def _prepare_candidate_database_search(self):
        return 1

    def _set_auto_search_busy(self, value):
        pass

    def _run_background_task(self, title, label, task, success, failure, **kwargs):
        task(None, None)


class AsyncRankingWindowProbe(SearchWindowProbe):
    def __init__(self):
        super().__init__()
        self.background_operations = []
        self.rows_set = []
        self._candidate_search_request_token = 0
        self._auto_search_token = 0
        self._auto_search_ranked_rows = None
        self._auto_search_scored_keys = set()
        self.match_candidates = []
        self.local_phase_cache = SimpleNamespace(root="cache-root")
        self.match_pdf2 = SimpleNamespace(root="pdf2-root")
        self.candidate_table = SimpleNamespace(
            rowCount=lambda: 0,
            isRowHidden=lambda _row: False,
            selectRow=lambda _row: None,
            scrollToTop=lambda: None,
        )

    def _prepare_candidate_database_search(self):
        self._candidate_search_request_token += 1
        return self._candidate_search_request_token

    def _active_wavelength(self):
        return 1.5406

    def _record_initial_candidate_rows(self, rows):
        pass

    def _finalize_candidate_search(self, search_token):
        pass

    def _apply_candidate_element_filter(self):
        pass

    def _set_candidate_rows(self, rows, **kwargs):
        self.rows_set.append((rows, kwargs))

    def _run_background_task(self, title, label, task, success, failure, **kwargs):
        operation = kwargs.get("operation_name")
        self.background_operations.append(operation)
        if operation == "match.search.auto":
            success(
                [
                    ["COD", "1", "SiO2", "Quartz", "", "", "", ""],
                    ["USER", "2", "CaSiO3", "Wollastonite", "", "", "", ""],
                ]
            )
            return
        if operation == "match.rank.auto":
            from xrd_finder.services.auto_search_ranker import AutoSearchRankingResult

            success(
                AutoSearchRankingResult(
                    rows=[
                        ["USER", "2", "CaSiO3", "Wollastonite", "", "82%", "", ""],
                        ["COD", "1", "SiO2", "Quartz", "", "71%", "", ""],
                    ],
                    scored_keys={("COD", "1"), ("USER", "2")},
                    matched_count=2,
                )
            )
            return
        raise AssertionError(f"Unexpected operation: {operation}")


class FakeCandidateTable:
    def __init__(self):
        self.rows = [
            {"Source": "COD", "Formula": "CaSiO3"},
            {"Source": "USER", "Formula": "Ca2Al2SiO7"},
            {"Source": "MP", "Formula": "CaZrSiO5"},
            {"Source": "COD", "Formula": "SiO2"},
        ]
        self.hidden = [False] * len(self.rows)
        self.current = -1

    def rowCount(self):
        return len(self.rows)

    def row_values(self, row):
        return self.rows[row]

    def setRowHidden(self, row, hidden):
        self.hidden[row] = hidden

    def currentRow(self):
        return self.current

    def isRowHidden(self, row):
        return self.hidden[row]

    def clearSelection(self):
        self.current = -1

    def setCurrentCell(self, row, column):
        self.current = row

    def selectRow(self, row):
        self.current = row


class AutoSearchElementTests(unittest.TestCase):
    def test_large_manual_result_can_return_to_element_filter_without_processing(self):
        queued = []
        shown = []
        cancelled = []
        stopped = []
        detail = []
        rows = [["COD", str(index), "O2", "Phase", "", "", "", ""] for index in range(101)]
        window = SimpleNamespace(
            candidate_search_service=SimpleNamespace(
                queue_candidate_rows=lambda values, session_token=None: queued.append(values),
                preparation_queue=SimpleNamespace(
                    cancel_session=lambda token: cancelled.append(token)
                ),
            ),
            _candidate_batch_updates=SimpleNamespace(stop=lambda: stopped.append(True)),
            candidate_search_detail_label=SimpleNamespace(setText=detail.append),
            _confirm_large_candidate_search=lambda count: False,
            _set_candidate_rows=lambda values: shown.append(values),
        )

        accepted = PhaseFinderCandidateSearchActionsMixin._finish_manual_candidate_rows(
            window, rows, 17
        )

        self.assertFalse(accepted)
        self.assertEqual(queued, [])
        self.assertEqual(shown, [])
        self.assertEqual(cancelled, [17])
        self.assertEqual(stopped, [True])
        self.assertIn("101", detail[-1])

    def test_up_to_one_hundred_manual_results_start_processing_without_prompt(self):
        queued = []
        shown = []
        rows = [["COD", str(index), "O2", "Phase", "", "", "", ""] for index in range(100)]
        window = SimpleNamespace(
            candidate_search_service=SimpleNamespace(
                queue_candidate_rows=lambda values, session_token=None: queued.append((values, session_token)) or 5,
            ),
            _confirm_large_candidate_search=lambda count: (_ for _ in ()).throw(
                AssertionError("confirmation must not be shown")
            ),
            _set_candidate_rows=lambda values: shown.append(values),
            _candidate_processing_seconds_per_item=0.0,
        )

        accepted = PhaseFinderCandidateSearchActionsMixin._finish_manual_candidate_rows(
            window, rows, 9
        )

        self.assertTrue(accepted)
        self.assertEqual(queued[0][1], 9)
        self.assertEqual(shown, [rows])

    def test_find_without_required_element_does_not_start_broad_search(self):
        text_input = SimpleNamespace(text=lambda: "")
        calls = []
        window = SimpleNamespace(
            ccdc_doi_input=text_input,
            search_input=text_input,
            selected_elements=set(),
            _search_pdf2_text=lambda: calls.append("search"),
        )

        with patch("xrd_finder.ui.candidate_search_actions.QMessageBox.information") as information:
            PhaseFinderCandidateSearchActionsMixin._search_from_controls(window)

        self.assertEqual(calls, [])
        self.assertIn("required element", information.call_args.args[2].lower())

    def test_auto_search_ranks_candidates_in_a_second_background_task(self):
        window = AsyncRankingWindowProbe()

        PhaseFinderCandidateSearchActionsMixin._auto_search_candidates(window)

        self.assertEqual(
            window.background_operations,
            ["match.search.auto", "match.rank.auto"],
        )
        self.assertEqual(window.rows_set[-1][0][0][1], "2")
        self.assertTrue(window.rows_set[-1][1].get("skip_rank"))
        self.assertEqual(window._auto_search_scored_keys, {("COD", "1"), ("USER", "2")})

    def test_filter_scores_candidates_below_broad_ranking_cutoff(self):
        app = QApplication.instance() or QApplication([])
        rows = [
            ["COD", "1", "SiO2", "Quartz", "", "70%", "", ""],
            ["COD", "2", "CaSiO3", "Wollastonite", "", "", "", ""],
            ["COD", "3", "CaZrSiO5", "Other", "", "", "", ""],
        ]
        table = CandidateTableWidget(rows)
        calls = []
        window = SimpleNamespace(
            candidate_table=table,
            _auto_search_ranked_rows=[list(row) for row in rows],
            _auto_search_scored_keys={("COD", "1"), ("COD", "3")},
            _candidate_formula_matches_gate=PhaseFinderWindow._candidate_formula_matches_gate,
            _percent_text_value=lambda value: float(str(value).replace("%", "") or 0),
            _probability_observed_data=lambda: ([], [], [object()]),
            _candidate_row_peak_probability_from_records=lambda row, records, **kwargs: (
                calls.append(row[1]) or 87.0
            ),
        )

        PhaseFinderWindow._rerank_auto_search_element_subset(
            window, {"Ca", "Si", "O"}, set()
        )
        self.assertEqual(calls, ["2"])
        self.assertEqual(table.row_values(0)["Entry"], "2")
        self.assertEqual(table.row_values(0)["Match (%)"], "87%")

        PhaseFinderWindow._rerank_auto_search_element_subset(window, set(), set())
        self.assertEqual(table.row_values(0)["Entry"], "1")
        self.assertEqual(table.row_values(1)["Match (%)"], "87%")
        table.deleteLater()
        app.processEvents()

    def test_auto_search_with_blue_and_green_stays_local_and_chemistry_free(self):
        window = SearchWindowProbe()

        PhaseFinderCandidateSearchActionsMixin._auto_search_candidates(window)

        elements, options = window.candidate_search_service.calls[0]
        self.assertEqual(elements, [])
        self.assertEqual(options.local_sources, ["USER", "COD", "MP"])
        self.assertEqual(options.required_elements, [])
        self.assertEqual(options.optional_elements, [])
        self.assertEqual(options.excluded_elements, [])
        self.assertFalse(options.cod_online_enabled)
        self.assertFalse(options.materials_project_enabled)
        self.assertFalse(options.aflow_enabled)
        self.assertFalse(options.oqmd_enabled)
        self.assertTrue(options.rruff_enabled)

    def test_element_selection_filters_existing_rows_and_can_be_cleared(self):
        table = FakeCandidateTable()
        window = SimpleNamespace(
            candidate_table=table,
            selected_elements={"Ca", "Si", "O"},
            element_states={"Ca": "required", "Si": "required", "O": "required", "Al": "optional"},
        )

        PhaseFinderWindow._apply_candidate_element_filter(window)
        self.assertEqual(table.hidden, [False, False, False, True])
        self.assertEqual(table.rowCount(), 4)

        window.selected_elements = set()
        window.element_states = {}
        PhaseFinderWindow._apply_candidate_element_filter(window)
        self.assertEqual(table.hidden, [False, False, False, False])

    def test_real_candidate_table_keeps_rows_when_filter_changes(self):
        app = QApplication.instance() or QApplication([])
        table = CandidateTableWidget(
            [
                ["COD", "1", "CaSiO3", "A", "", "", "", ""],
                ["USER", "2", "Ca2Al2SiO7", "B", "", "", "", ""],
                ["MP", "3", "CaZrSiO5", "C", "", "", "", ""],
            ]
        )
        table.selectRow(2)
        window = SimpleNamespace(
            candidate_table=table,
            selected_elements={"Ca", "Si", "O"},
            element_states={"Ca": "required", "Si": "required", "O": "required", "Al": "optional"},
        )

        PhaseFinderWindow._apply_candidate_element_filter(window)
        self.assertEqual([table.isRowHidden(i) for i in range(3)], [False, False, False])
        self.assertEqual(table.rowCount(), 3)

        window.selected_elements = set()
        window.element_states = {}
        PhaseFinderWindow._apply_candidate_element_filter(window)
        self.assertEqual([table.isRowHidden(i) for i in range(3)], [False, False, False])
        table.deleteLater()
        app.processEvents()

    def test_candidate_table_upsert_preserves_scores_and_selection(self):
        app = QApplication.instance() or QApplication([])
        table = CandidateTableWidget(
            [
                ["COD", "1", "SiO2", "Quartz", "", "73%", "", ""],
                ["COD", "2", "CaCO3", "Calcite", "", "41%", "", ""],
            ]
        )
        table.selectRow(1)

        added, updated = table.upsert_rows(
            [
                ["COD", "1", "SiO2", "Quartz updated", "P 31 2 1", "", "", "5.0"],
                ["USER", "3", "CaSiO3", "Wollastonite", "", "62%", "", ""],
            ],
            lambda row: row,
        )

        self.assertEqual((added, updated), (1, 1))
        self.assertEqual([table.row_values(i)["Entry"] for i in range(3)], ["1", "3", "2"])
        quartz = table.row_values(0)
        self.assertEqual(quartz["Match (%)"], "73%")
        self.assertEqual(quartz["Phase"], "Quartz updated")
        self.assertEqual(table.selected_row_values()["Entry"], "2")
        table.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
