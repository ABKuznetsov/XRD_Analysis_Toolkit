from __future__ import annotations

import html
import math
from numbers import Real
from typing import Mapping

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from crystal_viewer.analysis.comparison import ComparisonReport, ComparisonState
from crystal_viewer.analysis.descriptors.model import FocusCommand
from crystal_viewer.ui.compare_table_model import CompareTableModel


class FrozenFirstColumnTreeView(QTreeView):
    """Tree view with a synchronized overlay that keeps column zero visible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("comparisonTree")
        self.setUniformRowHeights(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.frozen_view = QTreeView(self)
        self.frozen_view.setObjectName("comparisonFrozenTree")
        self.frozen_view.setFocusProxy(self)
        self.frozen_view.setFrameShape(QTreeView.Shape.NoFrame)
        self.frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen_view.setUniformRowHeights(True)
        self.frozen_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.frozen_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.verticalScrollBar().valueChanged.connect(self.frozen_view.verticalScrollBar().setValue)
        self.frozen_view.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        self.expanded.connect(self._expand_frozen)
        self.collapsed.connect(self._collapse_frozen)
        self.frozen_view.expanded.connect(self._expand_main)
        self.frozen_view.collapsed.connect(self._collapse_main)
        self.frozen_view.clicked.connect(self.clicked)
        self.header().sectionResized.connect(self._section_resized)

    def setModel(self, model) -> None:
        super().setModel(model)
        self.frozen_view.setModel(model)
        if model is None:
            return
        self.frozen_view.setSelectionModel(self.selectionModel())
        for column in range(1, model.columnCount()):
            self.frozen_view.setColumnHidden(column, True)
        self._update_frozen_geometry()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_frozen_geometry()

    def _section_resized(self, logical_index: int, _old_size: int, new_size: int) -> None:
        if logical_index == 0:
            self.frozen_view.setColumnWidth(0, new_size)
            self._update_frozen_geometry()

    def _update_frozen_geometry(self) -> None:
        if self.model() is None:
            return
        width = self.columnWidth(0)
        height = self.viewport().height() + self.header().height()
        self.frozen_view.setGeometry(self.frameWidth(), self.frameWidth(), width, height)
        self.frozen_view.setColumnWidth(0, width)
        self.frozen_view.raise_()

    def _expand_frozen(self, index: QModelIndex) -> None:
        if not self.frozen_view.isExpanded(index):
            self.frozen_view.expand(index)

    def _collapse_frozen(self, index: QModelIndex) -> None:
        if self.frozen_view.isExpanded(index):
            self.frozen_view.collapse(index)

    def _expand_main(self, index: QModelIndex) -> None:
        if not self.isExpanded(index):
            self.expand(index)

    def _collapse_main(self, index: QModelIndex) -> None:
        if self.isExpanded(index):
            self.collapse(index)


class CompareWorkspace(QWidget):
    focus_requested = Signal(object)
    visual_requested = Signal()
    export_csv_requested = Signal()
    export_json_requested = Signal()
    export_images_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report: ComparisonReport | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        controls = QHBoxLayout()
        self.visual_button = QPushButton("Back to visual comparison")
        self.visual_button.clicked.connect(self.visual_requested)
        controls.addWidget(self.visual_button)
        self.differences_only = QCheckBox("Show differences only")
        self.differences_only.toggled.connect(self._set_differences_only)
        controls.addWidget(self.differences_only)
        self.highlight_changes = QCheckBox("Highlight major changes")
        self.highlight_changes.setChecked(True)
        controls.addWidget(self.highlight_changes)
        self.expand_distributions = QCheckBox("Expand distributions")
        controls.addWidget(self.expand_distributions)
        controls.addStretch(1)
        self.csv_button = QPushButton("Export CSV")
        self.csv_button.clicked.connect(self.export_csv_requested)
        controls.addWidget(self.csv_button)
        self.json_button = QPushButton("Export JSON")
        self.json_button.clicked.connect(self.export_json_requested)
        controls.addWidget(self.json_button)
        self.images_button = QPushButton("Export images")
        self.images_button.clicked.connect(self.export_images_requested)
        controls.addWidget(self.images_button)
        root.addLayout(controls)

        self.status_label = QLabel()
        self.status_label.setObjectName("comparisonStatus")
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root.addWidget(self.status_label)

        self.summary_strip = QFrame()
        self.summary_strip.setObjectName("comparisonSummaryStrip")
        self.summary_strip.setMaximumHeight(96)
        summary_layout = QVBoxLayout(self.summary_strip)
        summary_layout.setContentsMargins(8, 6, 8, 6)
        self.summary_label = QLabel("No motif comparison summary available")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        summary_controls = QHBoxLayout()
        self.motif_summary_button = QPushButton("Structural Motifs")
        self.motif_summary_button.clicked.connect(
            lambda: self._select_section("Structural Motifs")
        )
        summary_controls.addWidget(self.motif_summary_button)
        self.connections_summary_button = QPushButton(
            "Connections and Interstitial Atoms"
        )
        self.connections_summary_button.clicked.connect(
            lambda: self._select_section("Connections and Interstitial Atoms")
        )
        summary_controls.addWidget(self.connections_summary_button)
        summary_controls.addStretch(1)
        summary_layout.addLayout(summary_controls)
        root.addWidget(self.summary_strip)

        splitter = QSplitter()
        self.table = FrozenFirstColumnTreeView()
        self.table.setAlternatingRowColors(False)
        self.table.setSortingEnabled(False)
        self.table.clicked.connect(self._row_clicked)
        splitter.addWidget(self.table)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.addWidget(QLabel("Method, evidence and warnings"))
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        detail_layout.addWidget(self.detail, 1)
        splitter.addWidget(detail)
        splitter.setSizes((900, 300))
        root.addWidget(splitter, 1)

    def set_report(self, report: ComparisonReport) -> None:
        if len(report.document_ids) != 2:
            raise ValueError("Comparison workspace requires exactly two structures; four or more are not supported.")
        self.report = report
        model = CompareTableModel(report, self)
        model.set_show_differences_only(self.differences_only.isChecked())
        self.table.setModel(model)
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, model.columnCount()):
            self.table.header().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.expandAll()
        self.table.frozen_view.expandAll()
        self._update_summary(report)
        self.detail.setHtml(
            "<b>Comparison ready</b><br>"
            "Select a characteristic to inspect its method, warnings and 3D focus."
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_loading(self, text: str = "Comparing structures…") -> None:
        self.report = None
        self.table.setModel(None)
        self.summary_label.setText(text)
        self.detail.setPlainText(text)
        self.set_status(text)

    def _set_differences_only(self, enabled: bool) -> None:
        model = self.table.model()
        if isinstance(model, CompareTableModel):
            model.set_show_differences_only(enabled)
            self.table.expandAll()
            self.table.frozen_view.expandAll()

    def _update_summary(self, report: ComparisonReport) -> None:
        motif_row = next(
            (row for row in report.rows if row.descriptor_id.startswith("motif.match.")),
            None,
        )
        substitutions = next(
            (row for row in report.rows if row.descriptor_id == "connections.substitutions"),
            None,
        )
        unmatched = next(
            (row for row in report.rows if row.descriptor_id == "connections.unmatched"),
            None,
        )
        motif_common = next(
            (row for row in report.rows if row.descriptor_id == "motif.common"),
            None,
        )
        not_evaluated = motif_common is not None and all(
            cell.state is ComparisonState.UNAVAILABLE for cell in motif_common.cells
        )
        parts = []
        if not_evaluated:
            parts.append("Motif comparison: Not evaluated")
        elif motif_row is not None:
            node_count = len(motif_row.expanded_records)
            parts.append(f"{motif_row.title}: {node_count} nodes")
        else:
            parts.append("Common motif: none")
        if not not_evaluated and substitutions is not None and len(substitutions.cells) >= 2:
            parts.append(
                "substitutions: "
                f"{substitutions.cells[0].display} → {substitutions.cells[1].display}"
            )
        if not not_evaluated and unmatched is not None:
            unmatched_count = sum(
                len(cell.raw) if isinstance(cell.raw, (tuple, list, set, frozenset)) else 0
                for cell in unmatched.cells
            )
            parts.append(f"unmatched: {unmatched_count}")
        warnings = tuple(report.warnings) + tuple(
            cell.warning
            for row in report.rows
            for cell in row.cells
            if cell.warning
        )
        unique_warnings = tuple(dict.fromkeys(warnings))
        approximation = next(
            (warning for warning in unique_warnings if "approximate" in warning.lower()),
            "",
        )
        ambiguity = next(
            (warning for warning in unique_warnings if "ambiguous" in warning.lower()),
            "",
        )
        summary = " · ".join(parts)
        if not_evaluated:
            status_warning = next(
                (
                    warning
                    for warning in unique_warnings
                    if "not evaluated" in warning.lower()
                ),
                "",
            )
            if status_warning:
                summary = f"{summary} · {status_warning}"
        elif approximation:
            summary = f"Approximate · {summary} · {approximation}"
        if ambiguity:
            summary = f"Ambiguous · {summary} · {ambiguity}"
        self.summary_label.setText(summary)

    def _select_section(self, section_name: str) -> None:
        model = self.table.model()
        if not isinstance(model, CompareTableModel):
            return

        def section_index() -> QModelIndex:
            for row in range(model.rowCount()):
                index = model.index(row, 0)
                if index.data() == section_name:
                    return index
            return QModelIndex()

        index = section_index()
        if not index.isValid() and self.differences_only.isChecked():
            self.differences_only.setChecked(False)
            model = self.table.model()
            if not isinstance(model, CompareTableModel):
                return
            index = section_index()
        if not index.isValid():
            return
        self.table.expand(index)
        self.table.frozen_view.expand(index)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(
            index,
            QAbstractItemView.ScrollHint.PositionAtTop,
        )

    def _row_clicked(self, index: QModelIndex) -> None:
        model = self.table.model()
        if not isinstance(model, CompareTableModel) or not index.isValid():
            return
        row = model.comparison_row(index)
        if row is None:
            return
        warnings = list(dict.fromkeys(cell.warning for cell in row.cells if cell.warning))
        records = row.expanded_records
        detail = [
            f"<h3>{html.escape(row.title)}</h3>",
            f"<b>Section:</b> {html.escape(row.section)}<br>",
            f"<b>Method:</b> {html.escape(row.method_id or '—')}<br>",
        ]
        if row.descriptor_id in {
            "motif.common",
            "connections.substitutions",
            "connections.unmatched",
        } and row.cells and all(
            cell.state is ComparisonState.UNAVAILABLE for cell in row.cells
        ):
            detail.append("<b>Status:</b> Not evaluated<br>")
        if warnings:
            detail.append("<b>Warnings:</b><br>" + "<br>".join(html.escape(value) for value in warnings))
        if row.descriptor_id.startswith("motif.match."):
            raw = next(
                (cell.raw for cell in row.cells if isinstance(cell.raw, Mapping)),
                {},
            )
            score_rows = []
            for key, label in (
                ("topology_score", "Topology score"),
                ("geometry_score", "Geometry score"),
                ("chemistry_score", "Chemistry score"),
                ("total_score", "Total score"),
            ):
                value = raw.get(key) if isinstance(raw, Mapping) else None
                display = "—"
                if (
                    isinstance(value, Real)
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    and 0.0 <= float(value) <= 1.0
                ):
                    display = f"{float(value):.3f}"
                score_rows.append(f"{html.escape(label)}: {html.escape(display)}")
            detail.append("<br><b>Scores:</b><br>" + "<br>".join(score_rows))
        if records:
            detail.append(f"<br><b>Expanded records:</b> {len(records)} structure set(s)")
        self.detail.setHtml("".join(detail))
        if isinstance(row.focus, FocusCommand):
            self.focus_requested.emit(row.focus)
