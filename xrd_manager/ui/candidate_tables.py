from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)


class CandidateTableWidget(QTableWidget):
    rowClicked = Signal(int)
    addRequested = Signal()
    contextRequested = Signal(QPoint)

    HEADERS = ["Source", "Entry", "Formula", "Phase", "I/Ic*"]

    def __init__(self, rows: list[list[str]], parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setToolTip(
            "Candidate list\n"
            "Single click: preview this candidate and show its card.\n"
            "Double click: add this candidate to the selected phases.\n"
            "Right click: add, calculate overlay, or export CIF."
        )
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_request)
        self.cellClicked.connect(self._emit_row_clicked)
        self.cellDoubleClicked.connect(lambda _row, _column: self.addRequested.emit())
        self.set_rows(rows, lambda row: row)
        self.horizontalHeader().setToolTip(
            "Single click a row to preview. Double click a row to add it to selected phases."
        )

    def set_rows(
        self,
        rows: list[list[str]],
        normalize_row: Callable[[list[str]], list[str]],
    ) -> None:
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            normalized_row = normalize_row(row)
            for col_index, value in enumerate(normalized_row[: self.columnCount()]):
                item = QTableWidgetItem(value)
                if col_index == 0 and len(normalized_row) > 5:
                    item.setData(Qt.ItemDataRole.UserRole, normalized_row[5])
                self.setItem(row_index, col_index, item)
        self._resize_columns()

    def row_values(self, row: int) -> dict[str, str]:
        if row < 0 or row >= self.rowCount():
            return {}
        values = {}
        for column in range(self.columnCount()):
            header_item = self.horizontalHeaderItem(column)
            header = header_item.text() if header_item is not None else str(column)
            item = self.item(row, column)
            values[header] = item.text().strip() if item is not None else ""
        first_item = self.item(row, 0)
        if first_item is not None:
            notes = first_item.data(Qt.ItemDataRole.UserRole)
            if notes:
                values["Notes"] = str(notes)
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

    def _emit_row_clicked(self, row: int, _column: int) -> None:
        if row >= 0:
            self.selectRow(row)
        self.rowClicked.emit(row)

    def _emit_context_request(self, point: QPoint) -> None:
        row = self.rowAt(point.y())
        if row >= 0:
            self.selectRow(row)
        self.contextRequested.emit(self.viewport().mapToGlobal(point))

    def _resize_columns(self) -> None:
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)


class SelectedCandidatesTableWidget(QTableWidget):
    rowClicked = Signal(int)
    contextRequested = Signal(QPoint)

    HEADERS = ["Color", "Phase", "Peaks", "Quant. (%)", "I/Ic*"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setToolTip(
            "Selected phases\n"
            "Single click: show the calculated profile and markers for this phase.\n"
            "Right click: change color, export CIF, remove phase, or clear the list."
        )
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_request)
        self.cellClicked.connect(self._emit_row_clicked)
        self._resize_columns()
        self.horizontalHeader().setToolTip(
            "Selected phases included in the calculated total profile."
        )

    def set_rows(self, rows: list[list[str]]) -> None:
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row[: self.columnCount()]):
                item = QTableWidgetItem(value)
                if column == 0:
                    color = QColor(value)
                    if color.isValid():
                        item.setBackground(color)
                        item.setForeground(QColor("#ffffff" if color.lightness() < 150 else "#111111"))
                self.setItem(row_index, column, item)
        self._resize_columns()

    def _emit_row_clicked(self, row: int, _column: int) -> None:
        if row >= 0:
            self.selectRow(row)
        self.rowClicked.emit(row)

    def _emit_context_request(self, point: QPoint) -> None:
        row = self.rowAt(point.y())
        if row >= 0:
            self.selectRow(row)
        self.contextRequested.emit(self.viewport().mapToGlobal(point))

    def _resize_columns(self) -> None:
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
