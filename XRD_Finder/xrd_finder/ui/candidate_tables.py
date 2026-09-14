from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)


@dataclass(frozen=True, slots=True)
class CandidateTableContext:
    candidate_key: tuple[str, str] | None
    horizontal_scroll: int
    vertical_scroll: int


class CandidateTableWidget(QTableWidget):
    rowActivated = Signal(int)
    addRequested = Signal()
    contextRequested = Signal(QPoint)

    MATCH_HEADER = "Match (%)"
    GAIN_HEADER = "Gain (%)"
    HEADERS = ["Source", "Entry", "Formula", "Phase", "Sp. gr.", MATCH_HEADER, GAIN_HEADER, "I/Ic"]

    def __init__(self, rows: list[list[str]], parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self._gain_active = False
        self.setToolTip(
            "Candidate list\n"
            "Single click: preview this candidate and show its card.\n"
            "Double click: add this candidate to the selected phases.\n"
            "Right click: add, calculate overlay, or export CIF."
        )
        self.setHorizontalHeaderLabels(self.HEADERS)
        iic_header = self.horizontalHeaderItem(len(self.HEADERS) - 1)
        if iic_header is not None:
            iic_header.setToolTip("Reference-source I/Ic value only; blank when no traceable reference value is available.")
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_request)
        self.cellClicked.connect(self._activate_clicked_row)
        self.currentCellChanged.connect(self._emit_current_row_changed)
        self.cellDoubleClicked.connect(lambda _row, _column: self.addRequested.emit())
        self.set_rows(rows, lambda row: row)
        self.horizontalHeader().setToolTip(
            "Single click a row to preview. Double click a row to add it to selected phases."
        )

    def set_rows(
        self,
        rows: list[list[str]],
        normalize_row: Callable[[list[str]], list[str]],
        *,
        preserve_context: bool = True,
        select_first_if_missing: bool = False,
    ) -> None:
        context = self.capture_context() if preserve_context else None
        previous_block_state = self.blockSignals(True)
        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        try:
            self.clearContents()
            self.setRowCount(len(rows))
            column_count = self.columnCount()
            for row_index, row in enumerate(rows):
                normalized_row = normalize_row(row)
                for col_index, value in enumerate(normalized_row[:column_count]):
                    self.setItem(row_index, col_index, QTableWidgetItem(value))
            self._apply_score_arrows()
            self._resize_columns()
            if context is not None:
                self.restore_context(
                    context,
                    select_first_if_missing=select_first_if_missing,
                )
            elif select_first_if_missing and self.rowCount() > 0:
                self.setCurrentCell(0, 0)
                self.selectRow(0)
        finally:
            self.blockSignals(previous_block_state)
            self.setUpdatesEnabled(True)
        self.viewport().update()

    def capture_context(self) -> CandidateTableContext:
        values = self.selected_row_values()
        candidate_key = None
        if values:
            source = values.get("Source", "").strip().upper()
            entry_id = values.get("Entry", "").strip()
            if source and entry_id:
                candidate_key = source, entry_id
        return CandidateTableContext(
            candidate_key=candidate_key,
            horizontal_scroll=self.horizontalScrollBar().value(),
            vertical_scroll=self.verticalScrollBar().value(),
        )

    def restore_context(
        self,
        context: CandidateTableContext,
        *,
        select_first_if_missing: bool = False,
    ) -> None:
        selected_row = self._row_for_candidate_key(context.candidate_key)
        if selected_row < 0 and select_first_if_missing and self.rowCount() > 0:
            selected_row = 0
        if selected_row >= 0:
            self.setCurrentCell(selected_row, 0)
            self.selectRow(selected_row)
        self.horizontalScrollBar().setValue(context.horizontal_scroll)
        self.verticalScrollBar().setValue(context.vertical_scroll)

    def _row_for_candidate_key(self, candidate_key: tuple[str, str] | None) -> int:
        if candidate_key is None:
            return -1
        for row in range(self.rowCount()):
            values = self.row_values(row)
            key = (
                values.get("Source", "").strip().upper(),
                values.get("Entry", "").strip(),
            )
            if key == candidate_key:
                return row
        return -1

    def row_values(self, row: int) -> dict[str, str]:
        if row < 0 or row >= self.rowCount():
            return {}
        values = {}
        for column in range(self.columnCount()):
            header_item = self.horizontalHeaderItem(column)
            header = header_item.text().lstrip("→ ") if header_item is not None else str(column)
            item = self.item(row, column)
            value = item.text().strip() if item is not None else ""
            if header in {self.MATCH_HEADER, self.GAIN_HEADER}:
                value = value.removeprefix("←").removeprefix("→").strip()
            values[header] = value
            if header == "I/Ic":
                values["I/Ic*"] = value
        return values

    def selected_row_values(self) -> dict[str, str] | None:
        row = self.currentRow()
        if row < 0:
            return None
        return self.row_values(row)

    def all_row_values(self) -> list[dict[str, str]]:
        return [self.row_values(row) for row in range(self.rowCount())]

    def set_iic(self, row: int, value: str) -> None:
        if not value or row < 0 or row >= self.rowCount():
            return
        item = self.item(row, self.columnCount() - 1)
        if item is not None:
            item.setText(value)

    def set_probability(self, row: int, value: str) -> None:
        if not value or row < 0 or row >= self.rowCount():
            return
        column = self._column_index(self.MATCH_HEADER)
        if column < 0:
            return
        item = self.item(row, column)
        if item is not None:
            item.setText(self._score_display_text(column, value))

    def set_scoring_stage(self, gain_active: bool) -> None:
        """Point the user to the score that controls the current ranking."""
        self._gain_active = bool(gain_active)
        match_column = self._column_index(self.MATCH_HEADER) if self._column_index(self.MATCH_HEADER) >= 0 else 5
        gain_column = self._column_index(self.GAIN_HEADER) if self._column_index(self.GAIN_HEADER) >= 0 else 6
        match_item = self.horizontalHeaderItem(match_column)
        gain_item = self.horizontalHeaderItem(gain_column)
        if match_item is None or gain_item is None:
            return
        match_item.setText("Match (%)")
        gain_item.setText("Gain (%)")
        match_item.setBackground(QColor() if gain_active else QColor("#dceeff"))
        match_item.setForeground(QColor() if gain_active else QColor("#185abc"))
        gain_item.setBackground(QColor("#dff3e4") if gain_active else QColor())
        gain_item.setForeground(QColor("#176b35") if gain_active else QColor())
        match_item.setToolTip(
            "Global candidate compatibility used before the first phase is accepted."
        )
        gain_item.setToolTip(
            "Conditional residual contribution used after at least one phase is accepted."
        )
        self._apply_score_arrows()

    def _score_display_text(self, column: int, value: str) -> str:
        text = str(value).strip().removeprefix("←").removeprefix("→").strip()
        if not text:
            return ""
        active_column = self._column_index(self.GAIN_HEADER if self._gain_active else self.MATCH_HEADER)
        if column != active_column:
            return text
        return f"→ {text}" if self._gain_active else f"← {text}"

    def _apply_score_arrows(self) -> None:
        for header in (self.MATCH_HEADER, self.GAIN_HEADER):
            column = self._column_index(header)
            if column < 0:
                continue
            for row in range(self.rowCount()):
                item = self.item(row, column)
                if item is not None:
                    item.setText(self._score_display_text(column, item.text()))

    def _column_index(self, header: str) -> int:
        for column in range(self.columnCount()):
            item = self.horizontalHeaderItem(column)
            if item is not None and item.text().lstrip("→ ") == header:
                return column
        return -1

    def _activate_clicked_row(self, row: int, _column: int) -> None:
        if row >= 0:
            self.selectRow(row)

    def _emit_current_row_changed(self, current_row: int, _current_column: int, previous_row: int, _previous_column: int) -> None:
        if current_row >= 0 and current_row != previous_row:
            self.rowActivated.emit(current_row)

    def _emit_context_request(self, point: QPoint) -> None:
        row = self.rowAt(point.y())
        if row >= 0:
            self.selectRow(row)
        self.contextRequested.emit(self.viewport().mapToGlobal(point))

    def _resize_columns(self) -> None:
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(self.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        if self.rowCount() <= 80:
            self.resizeColumnsToContents()
            entry_width = min(max(self.columnWidth(1), 90), 170)
            formula_width = min(max(self.columnWidth(2), 150), 260)
        else:
            entry_width = 130
            formula_width = 190
        self.setColumnWidth(0, 58)
        self.setColumnWidth(1, entry_width)
        self.setColumnWidth(2, formula_width)
        self.setColumnWidth(4, 92)
        self.setColumnWidth(5, 82)
        self.setColumnWidth(6, 82)
        self.setColumnWidth(7, 72)


class SelectedCandidatesTableWidget(QTableWidget):
    rowClicked = Signal(int)
    contextRequested = Signal(QPoint)
    phaseNameEdited = Signal(int, str)

    HEADERS = ["Color", "Phase", "Fit / Peaks", "Quant. (%)", "I/Ic"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setToolTip(
            "Selected phases\n"
            "Single click: show the calculated profile and markers for this phase.\n"
            "Double click the Phase cell to rename the phase for tables and figures.\n"
            "Right click: rename, change color, export CIF, remove phase, or clear the list."
        )
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
        )
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_request)
        self.cellClicked.connect(self._emit_row_clicked)
        self.itemChanged.connect(self._emit_phase_name_edited)
        self._resize_columns()
        self.horizontalHeader().setToolTip(
            "Selected phases included in the calculated total profile."
        )

    def set_rows(self, rows: list[list[str]]) -> None:
        previous_block_state = self.blockSignals(True)
        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        try:
            self.clearContents()
            self.setRowCount(len(rows))
            column_count = self.columnCount()
            for row_index, row in enumerate(rows):
                for column, value in enumerate(row[:column_count]):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        color = QColor(value)
                        if color.isValid():
                            item.setBackground(color)
                            item.setForeground(QColor("#ffffff" if color.lightness() < 150 else "#111111"))
                    if column != 1:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.setItem(row_index, column, item)
            self._resize_columns()
        finally:
            self.blockSignals(previous_block_state)
            self.setUpdatesEnabled(True)
        self.viewport().update()

    def _emit_row_clicked(self, row: int, _column: int) -> None:
        if row >= 0:
            self.selectRow(row)
        self.rowClicked.emit(row)

    def _emit_context_request(self, point: QPoint) -> None:
        row = self.rowAt(point.y())
        if row >= 0:
            self.selectRow(row)
        self.contextRequested.emit(self.viewport().mapToGlobal(point))

    def _emit_phase_name_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        self.phaseNameEdited.emit(item.row(), item.text().strip())

    def edit_phase_name(self, row: int) -> None:
        item = self.item(row, 1)
        if item is None:
            return
        self.setCurrentItem(item)
        self.editItem(item)

    def _resize_columns(self) -> None:
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(self.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 56)
        self.setColumnWidth(2, 86)
        self.setColumnWidth(3, 76)
        self.setColumnWidth(4, 54)
