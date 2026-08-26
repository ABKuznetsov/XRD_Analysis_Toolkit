from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QLabel, QTreeView

from crystal_viewer.analysis.comparison import (
    ComparisonCell,
    ComparisonReport,
    ComparisonRow,
    ComparisonState,
)
from crystal_viewer.analysis.descriptors.model import FocusCommand
from crystal_viewer.analysis.hierarchy import HierarchyLevel
from crystal_viewer.ui import compare_workspace
from crystal_viewer.ui.compare_workspace import CompareWorkspace


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _report(count: int = 2) -> ComparisonReport:
    ids = tuple(chr(ord("a") + index) for index in range(count))
    focus = FocusCommand("isolate", HierarchyLevel.POLYHEDRA, "polyhedron-type", {"center": "Mo"})
    row = ComparisonRow(
        "mo_o.distortion_index",
        "Mo–O distortion",
        "Coordination chemistry",
        tuple(ComparisonCell(identifier, "0.01", ComparisonState.SIMILAR, 0.01) for identifier in ids),
        method_id="mo-o-v1",
        focus=focus,
    )
    return ComparisonReport(ids, tuple(f"Structure {value.upper()}" for value in ids), (row,))


def _motif_summary_report(
    *,
    approximate: bool = False,
    ambiguous: bool = False,
) -> ComparisonReport:
    warning_parts = []
    if approximate:
        warning_parts.append("Approximate motif result: max_nodes")
    if ambiguous:
        warning_parts.append("Ambiguous motif result: 2 equivalent best mappings")
    warning = "; ".join(warning_parts)
    motif = ComparisonRow(
        "motif.match.M1",
        "Common chain",
        "Structural Motifs",
        (
            ComparisonCell("a", "chain: 12 nodes · 11 connections", ComparisonState.SIMILAR, warning=warning),
            ComparisonCell("b", "chain: 12 nodes · 11 connections", ComparisonState.SIMILAR, warning=warning),
        ),
        method_id="motif-v1",
        focus=FocusCommand(
            "isolate",
            HierarchyLevel.STRUCTURAL_UNITS,
            "motif-pair",
            {
                "first_polyhedron_ids": ("P1",),
                "second_polyhedron_ids": ("P7",),
                "first_atom_indices": (),
                "second_atom_indices": (),
            },
        ),
        expanded_records=tuple({"pair": index} for index in range(12)),
    )
    substitutions = ComparisonRow(
        "connections.substitutions",
        "Atom substitutions",
        "Connections and Interstitial Atoms",
        (
            ComparisonCell("a", "Na", ComparisonState.DIFFERENT, ("Na",), warning),
            ComparisonCell("b", "Li/Na", ComparisonState.DIFFERENT, ("Li", "Na"), warning),
        ),
        method_id="motif-v1",
    )
    unmatched = ComparisonRow(
        "connections.unmatched",
        "Unmatched nodes",
        "Connections and Interstitial Atoms",
        (
            ComparisonCell("a", "1", ComparisonState.DIFFERENT, ("P3",), warning),
            ComparisonCell("b", "3", ComparisonState.DIFFERENT, ("P8", "I2", "I3"), warning),
        ),
        method_id="motif-v1",
    )
    return ComparisonReport(
        ("a", "b"),
        ("Structure A", "Structure B"),
        (motif, substitutions, unmatched),
        tuple(
            item
            for item in (
                (
                    "Motif comparison is approximate; limits reached: max_nodes"
                    if approximate
                    else ""
                ),
                (
                    "Ambiguous motif comparison: 2 equivalent best mappings"
                    if ambiguous
                    else ""
                ),
            )
            if item
        ),
    )


def test_workspace_uses_grouped_tree_with_synchronized_frozen_column() -> None:
    _application()
    workspace = CompareWorkspace()
    workspace.set_report(_report())

    assert isinstance(workspace.table, compare_workspace.FrozenFirstColumnTreeView)
    assert isinstance(workspace.table, QTreeView)
    assert workspace.table.frozen_view.model() is workspace.table.model()
    assert workspace.table.frozen_view.selectionModel() is workspace.table.selectionModel()
    assert all(
        workspace.table.isExpanded(workspace.table.model().index(row, 0))
        for row in range(workspace.table.model().rowCount())
    )
    assert workspace.table.header().sectionResizeMode(1) is QHeaderView.ResizeMode.Stretch
    assert workspace.table.header().sectionResizeMode(2) is QHeaderView.ResizeMode.Stretch


def test_loading_status_is_selectable_text_and_clears_a_previous_pair() -> None:
    _application()
    workspace = CompareWorkspace()
    workspace.set_report(_report())

    workspace.set_loading("Comparing structures…")

    assert isinstance(workspace.status_label, QLabel)
    assert workspace.status_label.text() == "Comparing structures…"
    assert workspace.status_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert workspace.report is None
    assert workspace.table.model() is None


def test_section_click_is_ignored_and_descriptor_click_emits_focus_command() -> None:
    _application()
    workspace = CompareWorkspace()
    received = []
    workspace.focus_requested.connect(received.append)
    workspace.set_report(_report())
    model = workspace.table.model()
    section = model.index(1, 0)

    workspace.table.clicked.emit(section)
    assert received == []

    descriptor = model.index(0, 0, section)
    workspace.table.clicked.emit(descriptor)

    assert isinstance(received[-1], FocusCommand)
    assert "Mo–O distortion" in workspace.detail.toPlainText()
    assert "mo-o-v1" in workspace.detail.toPlainText()


def test_workspace_limits_report_to_four_columns() -> None:
    _application()
    workspace = CompareWorkspace()

    with pytest.raises(ValueError, match="four"):
        workspace.set_report(_report(5))


def test_summary_strip_reports_motif_substitutions_unmatched_and_approximation() -> None:
    _application()
    workspace = CompareWorkspace()

    workspace.set_report(_motif_summary_report(approximate=True))

    summary = workspace.summary_label.text()
    assert "Approximate" in summary
    assert "Common chain: 12 nodes" in summary
    assert "substitutions: Na → Li/Na" in summary
    assert "unmatched: 4" in summary
    assert "max_nodes" in summary


def test_summary_strip_surfaces_equivalent_mapping_ambiguity() -> None:
    _application()
    workspace = CompareWorkspace()

    workspace.set_report(_motif_summary_report(ambiguous=True))

    summary = workspace.summary_label.text()
    assert "Ambiguous" in summary
    assert "2 equivalent best mappings" in summary


def test_not_evaluated_summary_and_detail_emit_no_absence_or_count_claims() -> None:
    _application()
    workspace = CompareWorkspace()
    warning = (
        "Motif comparison not evaluated: graph construction incomplete; "
        "limits reached: max_nodes"
    )
    rows = tuple(
        ComparisonRow(
            descriptor_id,
            title,
            section,
            tuple(
                ComparisonCell(
                    document_id,
                    "Not evaluated",
                    ComparisonState.UNAVAILABLE,
                    None,
                    warning,
                )
                for document_id in ("a", "b")
            ),
            method_id="motif-v2",
        )
        for descriptor_id, title, section in (
            ("motif.common", "Common motif", "Structural Motifs"),
            (
                "connections.substitutions",
                "Atom substitutions",
                "Connections and Interstitial Atoms",
            ),
            (
                "connections.unmatched",
                "Unmatched nodes",
                "Connections and Interstitial Atoms",
            ),
        )
    )
    workspace.set_report(
        ComparisonReport(
            ("a", "b"),
            ("Structure A", "Structure B"),
            rows,
            (warning,),
        )
    )

    summary = workspace.summary_label.text()
    assert "Not evaluated" in summary
    assert "Common motif: none" not in summary
    assert "substitutions:" not in summary
    assert "unmatched:" not in summary

    model = workspace.table.model()
    section = next(
        model.index(row, 0)
        for row in range(model.rowCount())
        if model.index(row, 0).data() == "Structural Motifs"
    )
    workspace.table.clicked.emit(model.index(0, 0, section))

    detail = workspace.detail.toPlainText()
    assert "Status: Not evaluated" in detail
    assert "graph construction incomplete" in detail
    assert "none" not in detail.lower()
    assert " 0" not in detail


def test_summary_controls_select_sections_without_emitting_focus() -> None:
    _application()
    workspace = CompareWorkspace()
    received = []
    workspace.focus_requested.connect(received.append)
    workspace.set_report(_motif_summary_report())

    workspace.motif_summary_button.click()

    motif_index = workspace.table.currentIndex()
    assert motif_index.data() == "Structural Motifs"
    assert workspace.table.isExpanded(motif_index)
    assert received == []

    workspace.connections_summary_button.click()

    connections_index = workspace.table.currentIndex()
    assert connections_index.data() == "Connections and Interstitial Atoms"
    assert workspace.table.isExpanded(connections_index)
    assert received == []


def test_summary_control_reveals_exact_section_hidden_by_differences_filter() -> None:
    _application()
    workspace = CompareWorkspace()
    received = []
    workspace.focus_requested.connect(received.append)
    workspace.set_report(_motif_summary_report())
    workspace.differences_only.setChecked(True)
    model = workspace.table.model()

    assert all(
        model.index(row, 0).data() != "Structural Motifs"
        for row in range(model.rowCount())
    )

    workspace.motif_summary_button.click()

    section = workspace.table.currentIndex()
    assert workspace.differences_only.isChecked() is False
    assert section.data() == "Structural Motifs"
    assert workspace.table.isExpanded(section)
    assert workspace.table.model().rowCount(section) == 1
    assert workspace.table.model().comparison_row(
        workspace.table.model().index(0, 0, section)
    ).descriptor_id == "motif.match.M1"
    assert received == []


def test_motif_row_detail_shows_scores_and_limit_and_ambiguity_warnings() -> None:
    _application()
    workspace = CompareWorkspace()
    raw = {
        "topology_score": 0.82,
        "geometry_score": 0.90,
        "chemistry_score": 0.75,
        "total_score": 0.835,
    }
    warning = (
        "Approximate motif result: max_nodes, max_seconds; "
        "Ambiguous motif result: 2 equivalent best mappings"
    )
    motif = ComparisonRow(
        "motif.match.M1",
        "Common <chain>",
        "Structural Motifs",
        (
            ComparisonCell("a", "chain", ComparisonState.MODERATE, raw, warning),
            ComparisonCell("b", "chain", ComparisonState.MODERATE, raw, warning),
        ),
        method_id="motif-v1",
    )
    workspace.set_report(ComparisonReport(("a", "b"), ("A", "B"), (motif,)))
    model = workspace.table.model()
    section = next(
        model.index(row, 0)
        for row in range(model.rowCount())
        if model.index(row, 0).data() == "Structural Motifs"
    )

    workspace.table.clicked.emit(model.index(0, 0, section))

    detail = workspace.detail.toPlainText()
    assert "Common <chain>" in detail
    assert "Topology score: 0.820" in detail
    assert "Geometry score: 0.900" in detail
    assert "Chemistry score: 0.750" in detail
    assert "Total score: 0.835" in detail
    assert detail.count("Approximate motif result") == 1
    assert detail.count("Ambiguous motif result") == 1


def test_motif_row_detail_handles_missing_and_malformed_scores_safely() -> None:
    _application()
    workspace = CompareWorkspace()
    malformed = {
        "topology_score": float("nan"),
        "geometry_score": "<unsafe>",
        "chemistry_score": None,
    }
    motif = ComparisonRow(
        "motif.match.M1",
        "Unsafe <motif>",
        "Structural Motifs",
        (
            ComparisonCell("a", "motif", ComparisonState.MODERATE, malformed),
            ComparisonCell("b", "motif", ComparisonState.MODERATE, None),
        ),
        method_id="motif-v1",
    )
    workspace.set_report(ComparisonReport(("a", "b"), ("A", "B"), (motif,)))
    model = workspace.table.model()
    section = next(
        model.index(row, 0)
        for row in range(model.rowCount())
        if model.index(row, 0).data() == "Structural Motifs"
    )

    workspace.table.clicked.emit(model.index(0, 0, section))

    detail = workspace.detail.toPlainText()
    assert "Unsafe <motif>" in detail
    assert "Topology score: —" in detail
    assert "Geometry score: —" in detail
    assert "Chemistry score: —" in detail
    assert "Total score: —" in detail
