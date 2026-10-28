from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from xrd_finder.ui.theme import is_dark_theme, theme_colors
from xrd_finder.ui.formula_display import FormulaDisplayDelegate, canonical_display_formula
from xrd_finder.ui.workspace_preferences import normalized_proportions
from PySide6.QtWidgets import (
    QHeaderView,
    QApplication,
    QStyle,
    QStyleOptionViewItem,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QStyledItemDelegate,
    QToolTip,
)


@dataclass(frozen=True, slots=True)
class CandidateTableContext:
    candidate_key: tuple[str, str] | None
    horizontal_scroll: int
    vertical_scroll: int


class _PhaseColorDelegate(QStyledItemDelegate):
    """Keep phase swatches visible through stylesheet and row-selection paint."""

    def paint(self, painter, option, index):
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if not isinstance(brush, QBrush) or brush.style() == Qt.BrushStyle.NoBrush:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ''
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        color = (foreground.color() if isinstance(foreground, QBrush)
                 and foreground.style() != Qt.BrushStyle.NoBrush
                 else QColor('#ffffff' if brush.color().lightness() < 150 else '#111111'))
        density = getattr(self.parent().window(), '_ui_density_factor', 1.)
        padding = max(2, round(7*density))
        rect = opt.rect.adjusted(padding, 0, -padding, -1)
        painter.save()
        painter.setClipRect(opt.rect)
        painter.fillRect(opt.rect.adjusted(0, 0, 0, -1), brush)
        painter.setFont(opt.font)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         opt.fontMetrics.elidedText(text, opt.textElideMode, max(0, rect.width())))
        painter.restore()


class _ScoreDisplayDelegate(QStyledItemDelegate):
    """Explain absent scores without inserting labels into numeric model data."""
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if not str(index.data() or '').strip():
            table = self.parent()
            option.text = table.score_display_text(index.row(), index.column())
            option.font.setPixelSize(max(4,round(11*getattr(table.window(),"_ui_density_factor",1.))))
            option.palette.setColor(option.palette.ColorRole.Text,
                                    QColor(theme_colors(is_dark_theme(table))['muted']))

    def helpEvent(self, event, view, option, index):
        if not str(index.data() or '').strip() and not index.data(Qt.ItemDataRole.ToolTipRole):
            messages = {
                'Inactive': 'This score is not active for the current pattern and search mode.',
                'Not calculated': 'No completed score is available for this candidate yet.',
                'Calculating…': 'The score is being calculated in the background.',
                'No score': 'Gain returned no reportable score. This is not a measured numerical zero.',
            }
            message = messages.get(self.parent().score_display_text(index.row(), index.column()))
            if message:
                QToolTip.showText(event.globalPos(), message, view)
                return True
        return super().helpEvent(event, view, option, index)


class _ColumnLayoutTableWidget(QTableWidget):
    """Fit saved column proportions to the panel; edit boundaries in place."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._column_layout_weights = []
        self._fitting_columns = False
        self._column_fit_timer = QTimer(self)
        self._column_fit_timer.setSingleShot(True)
        self._column_fit_timer.timeout.connect(self._fit_columns_to_viewport)
        self.viewport().installEventFilter(self)
        self.horizontalHeader().sectionResized.connect(self._column_section_resized)

    def _capture_column_proportions(self):
        widths = [max(1, self.columnWidth(i)) for i in range(self.columnCount())]
        total = sum(widths)
        self._column_layout_weights = [width/total for width in widths] if total else []

    def column_layout_proportions(self):
        return list(self._column_layout_weights)

    def column_layout_state(self):
        return {
            'order': [self.horizontalHeader().logicalIndex(i) for i in range(self.columnCount())],
            'proportions': normalized_proportions(self._column_layout_weights, self.columnCount()),
        }

    def set_column_layout_editable(self, editable: bool) -> None:
        self._column_layout_managed = True
        self._column_layout_editable = editable
        if editable:
            self._manual_column_layout = True
        self._apply_column_layout_lock()

    def _apply_column_layout_lock(self) -> None:
        if not getattr(self, '_column_layout_managed', False):
            return
        if not self._column_layout_weights or not getattr(self, '_manual_column_layout', False):
            self._capture_column_proportions()
        editable = self._column_layout_editable
        header = self.horizontalHeader()
        self._fitting_columns = True
        try:
            header.setStretchLastSection(False)
            header.setMinimumSectionSize(1)
            header.setSectionsMovable(editable)
            header.setFirstSectionMovable(editable)
            mode = QHeaderView.ResizeMode.Interactive if editable else QHeaderView.ResizeMode.Fixed
            header.setSectionResizeMode(mode)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        finally:
            self._fitting_columns = False
        self._fit_columns_to_viewport()

    def _fit_columns_to_viewport(self):
        if not getattr(self, '_column_layout_managed', False) or self._fitting_columns:
            return
        total = self.viewport().width()
        weights = self._column_layout_weights
        if len(weights) != self.columnCount() or total < len(weights) or not weights:
            return
        # Reserve only the smallest usable widths, then distribute the rest
        # proportionally, including rounding pixels so there is no empty edge.
        minimum = min(20, total//len(weights))
        widths = [0]*len(weights)
        active = list(range(len(weights)))
        remaining = total
        while active:
            scale = remaining/sum(weights[i] for i in active)
            narrow = [i for i in active if weights[i]*scale < minimum]
            if not narrow:
                desired = {i: weights[i]*scale for i in active}
                for i in active:
                    widths[i] = int(desired[i])
                extra = remaining-sum(widths[i] for i in active)
                for i in sorted(active, key=lambda i: desired[i]-widths[i], reverse=True)[:extra]:
                    widths[i] += 1
                break
            for i in narrow:
                widths[i] = minimum
                remaining -= minimum
                active.remove(i)
        self._set_fitted_column_widths(widths)

    def _set_fitted_column_widths(self, widths):
        self._fitting_columns = True
        try:
            for column, width in enumerate(widths):
                if self.columnWidth(column) != width:
                    self.setColumnWidth(column, width)
            # Refresh the scroll range immediately, before Qt can scroll to a
            # selected cell using the previous (wider) header geometry.
            self.updateGeometries()
            self.horizontalScrollBar().setValue(0)
        finally:
            self._fitting_columns = False

    def _column_section_resized(self, column, _old_size, new_size):
        if (self._fitting_columns or not getattr(self, '_column_layout_managed', False)
                or not self._column_layout_editable):
            return
        count = self.columnCount()
        total = self.viewport().width()
        if count < 2 or total < count:
            return
        minimum = min(20, total//count)
        widths = [self.columnWidth(i) for i in range(count)]
        widths[column] = max(minimum, min(new_size, total-minimum*(count-1)))
        header = self.horizontalHeader()
        visual = header.visualIndex(column)
        neighbours = [header.logicalIndex(i) for i in range(visual+1, count)]
        neighbours += [header.logicalIndex(i) for i in range(visual-1, -1, -1)]
        excess = sum(widths)-total
        if excess > 0:
            for i in neighbours:
                take = min(excess, max(0, widths[i]-minimum))
                widths[i] -= take
                excess -= take
                if not excess:
                    break
        elif excess < 0:
            widths[neighbours[0]] -= excess
        self._set_fitted_column_widths(widths)
        self._capture_column_proportions()

    def restore_column_layout(self, state, proportions=None) -> bool:
        if state is None:
            return False
        if isinstance(state, dict):
            order = state.get('order')
            weights = normalized_proportions(state.get('proportions'), self.columnCount())
            if (weights is None or not isinstance(order, list)
                    or any(type(i) is not int for i in order)
                    or sorted(order) != list(range(self.columnCount()))):
                return False
            self._fitting_columns = True
            try:
                header = self.horizontalHeader()
                for visual, logical in enumerate(order):
                    header.moveSection(header.visualIndex(logical), visual)
                self._column_layout_weights = weights
                self._manual_column_layout = True
            finally:
                self._fitting_columns = False
            self._apply_column_layout_lock()
            return True
        self._fitting_columns = True
        try:
            restored = self.horizontalHeader().restoreState(state)
        finally:
            self._fitting_columns = False
        if restored:
            self._manual_column_layout = True
            try:
                weights = [float(value) for value in proportions]
                valid = len(weights) == self.columnCount() and all(math.isfinite(v) and v > 0 for v in weights)
            except (TypeError, ValueError):
                valid = False
            if valid:
                self._column_layout_weights = weights
            else:
                # Existing 1.6.7 layouts stored pixel widths; retain their ratios.
                self._capture_column_proportions()
        self._apply_column_layout_lock()
        return restored

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_columns_to_viewport()

    def eventFilter(self, watched, event):
        timer = getattr(self, '_column_fit_timer', None)
        if timer is not None and watched is self.viewport() and event.type() == QEvent.Type.Resize:
            timer.start(0)
        return super().eventFilter(watched, event)


class CandidateTableWidget(_ColumnLayoutTableWidget):
    rowActivated = Signal(int)
    addRequested = Signal()
    contextRequested = Signal(QPoint)

    MATCH_HEADER = "Match (%)"
    GAIN_HEADER = "Gain (%)"
    HEADERS = ["Source", "Entry", "Formula", "Phase", "Sp. gr.", MATCH_HEADER, GAIN_HEADER, "I/Ic"]
    DISPLAY_HEADERS = ["Source", "Database ID", "Formula", "Phase name", "Sp. group", "Match score (%)", GAIN_HEADER, "I/Ic"]

    def __init__(self, rows: list[list[str]], parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self._gain_active = False
        self._selected_peak_scoring = False
        self._requested_gain_stage = False
        self._user_sort_column = None
        self._user_sort_order = Qt.SortOrder.AscendingOrder
        self._selected_phase_colors: dict[tuple[str, str], str] = {}
        self._match_failures = {}
        self._match_unavailable = set()
        self._score_context = dict(has_pattern=False, match_enabled=True, gain_enabled=False,
                                   match_busy=False, gain_busy=False)
        self._gain_result_keys = set()
        self._score_identity = None
        self._ranking_keys: list[tuple[str, str] | None] = []
        self._user_sort_timer = QTimer(self)
        self._user_sort_timer.setSingleShot(True)
        self._user_sort_timer.timeout.connect(self.refresh_user_sort)
        self.itemChanged.connect(self._schedule_user_sort)
        self.setToolTip(
            "Candidate list\n"
            "Single click: preview this candidate and show its card.\n"
            "Double click: add this candidate to the selected phases.\n"
            "Right click: add, calculate overlay, or export CIF."
        )
        self.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)
        self.setItemDelegateForColumn(1, _PhaseColorDelegate(self))
        self.setItemDelegateForColumn(2, FormulaDisplayDelegate(self))
        self.setItemDelegateForColumn(3, FormulaDisplayDelegate(self))
        self.setItemDelegateForColumn(5, _ScoreDisplayDelegate(self))
        self.setItemDelegateForColumn(6, _ScoreDisplayDelegate(self))
        iic_header = self.horizontalHeaderItem(len(self.HEADERS) - 1)
        if iic_header is not None:
            iic_header.setToolTip("~: calculated ideal-powder I/Ic using CrIStMa, Cu K-alpha1 and a cached corundum reference. Blank: unavailable or pending update. Not a measured reference value.")
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setShowGrid(False)
        self.verticalHeader().setDefaultSectionSize(32)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_request)
        self.cellClicked.connect(self._activate_clicked_row)
        self.currentCellChanged.connect(self._emit_current_row_changed)
        self.cellDoubleClicked.connect(lambda _row, _column: self.addRequested.emit())
        self.set_rows(rows, lambda row: row)
        self.horizontalHeader().setToolTip(
            "Click a column heading to sort; click again to reverse the order."
        )
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().sectionClicked.connect(self._sort_from_header)

    def _sort_from_header(self, column: int) -> None:
        if self._user_sort_column == column:
            self._user_sort_order = (Qt.SortOrder.AscendingOrder
                if self._user_sort_order == Qt.SortOrder.DescendingOrder else Qt.SortOrder.DescendingOrder)
        else:
            self._user_sort_order = (Qt.SortOrder.DescendingOrder if column in (5, 6, 7)
                else Qt.SortOrder.AscendingOrder)
        self._user_sort_column = column
        self.refresh_user_sort()

    def refresh_user_sort(self) -> None:
        self._user_sort_timer.stop()
        context = self.capture_context()
        blocked = self.blockSignals(True)
        try:
            self._apply_user_sort()
            self.restore_context(context)
        finally:
            self.blockSignals(blocked)

    def _schedule_user_sort(self, _item=None) -> None:
        if self._user_sort_column is not None:
            self._user_sort_timer.start(0)

    def _apply_user_sort(self) -> None:
        column = self._user_sort_column
        if column is None:
            return
        # Move complete rows only. Qt's automatic sorting during setItem can
        # otherwise split a row between two candidates while batches arrive.
        def sort_value(row):
            item = self.item(row, column)
            text = item.text().strip() if item is not None else ''
            if column in (2, 3):
                text = canonical_display_formula(text)
            if column in (1, 5, 6, 7):
                try:
                    value = float(text.replace('%', '').replace(',', '.').removeprefix('←').removeprefix('→').strip().removeprefix('~'))
                    return value if math.isfinite(value) else None
                except ValueError:
                    # Entry identifiers may also be alphanumeric.
                    return text.casefold() if column == 1 and text else None
            return text.casefold() if text else None
        populated, missing = [], []
        for row in range(self.rowCount()):
            value = sort_value(row)
            if value is None:
                missing.append(row)
            else:
                populated.append((row, value))
        populated.sort(key=lambda pair: (isinstance(pair[1], str), pair[1]),
            reverse=self._user_sort_order == Qt.SortOrder.DescendingOrder)
        order = [row for row, _ in populated] + missing
        self._move_rows(order)
        header = self.horizontalHeader()
        header.setSortIndicator(column, self._user_sort_order)
        header.setSortIndicatorShown(True)

    def _move_rows(self, order: list[int]) -> None:
        if order != list(range(self.rowCount())):
            hidden = [self.isRowHidden(row) for row in range(self.rowCount())]
            items = [[self.takeItem(row, col) for col in range(self.columnCount())]
                for row in range(self.rowCount())]
            for target, source in enumerate(order):
                for col, item in enumerate(items[source]):
                    if item is not None:
                        self.setItem(target, col, item)
                self.setRowHidden(target, hidden[source])

    def _ranking_row_indices(self) -> list[int]:
        ranks = {key: index for index, key in enumerate(self._ranking_keys)}
        return sorted(range(self.rowCount()), key=lambda row:
            ranks.get(self._candidate_key_from_values(self._row_texts(row)), len(ranks)))

    def _capture_ranking_order(self) -> None:
        self._ranking_keys = [self._candidate_key_from_values(self._row_texts(row))
            for row in range(self.rowCount())]

    def ranking_row_values(self) -> list[dict[str, str]]:
        """Backend order, independent of the user's display-only column sort."""
        return [self.row_values(row) for row in self._ranking_row_indices()]

    def csv_rows(self) -> list[list[str]]:
        """Export display order and meaningful score states, without UI arrows."""
        rows = []
        for row in range(self.rowCount()):
            values = self._row_texts(row)
            if self._candidate_key_from_values(values) is None:
                continue
            for column in (5, 6):
                values[column] = self.score_display_text(row, column).strip().removeprefix('←').removeprefix('→').strip()
            rows.append(values)
        return rows

    def ranking_current_row(self) -> int:
        indices = self._ranking_row_indices()
        return indices.index(self.currentRow()) if self.currentRow() in indices else -1

    def select_ranking_row(self, row: int) -> None:
        indices = self._ranking_row_indices()
        if 0 <= row < len(indices):
            self.setCurrentCell(indices[row], 0)
            self.selectRow(indices[row])

    def set_selected_phase_colors(self, colors: dict[tuple[str, str], str]) -> None:
        self._selected_phase_colors = dict(colors)
        self._apply_selected_phase_colors()

    def _apply_selected_phase_colors(self) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 1)
            if item is None:
                continue
            key = self._candidate_key_from_values(self._row_texts(row))
            color = QColor(self._selected_phase_colors.get(key, ''))
            item.setBackground(QBrush(color) if color.isValid() else QBrush())
            item.setForeground(QBrush(QColor('#ffffff' if color.lightness() < 150 else '#111111'))
                if color.isValid() else QBrush())
            item.setToolTip('Selected in this project; color matches the phase markers.' if color.isValid() else '')

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
            self._apply_selected_phase_colors()
            self._capture_ranking_order()
            self._apply_user_sort()
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

    def upsert_rows(
        self,
        rows: list[list[str]],
        normalize_row: Callable[[list[str]], list[str]],
    ) -> tuple[int, int]:
        """Update keyed rows in place and insert new scored rows without rebuilding."""

        incoming: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            normalized = normalize_row(row)
            key = self._candidate_key_from_values(normalized)
            if key is not None:
                incoming[key] = normalized
        if not incoming:
            return 0, 0

        context = self.capture_context()
        previous_block_state = self.blockSignals(True)
        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        added = 0
        updated = 0
        try:
            self._move_rows(self._ranking_row_indices())
            # Informational placeholder rows do not belong beside real candidates.
            for row_index in range(self.rowCount() - 1, -1, -1):
                values = self.row_values(row_index)
                if not values.get("Source", "") or not values.get("Entry", ""):
                    self.removeRow(row_index)

            existing = {
                key: row_index
                for row_index in range(self.rowCount())
                if (key := self._candidate_key_from_values(self._row_texts(row_index))) is not None
            }
            for key, normalized in incoming.items():
                row_index = existing.get(key, -1)
                if row_index >= 0:
                    self._update_row_values(row_index, normalized)
                    updated += 1
            for key, normalized in incoming.items():
                if key in existing:
                    continue
                row_index = self._score_insertion_index(normalized)
                self.insertRow(row_index)
                self._update_row_values(row_index, normalized)
                added += 1
            self._apply_score_arrows()
            self._apply_selected_phase_colors()
            self._capture_ranking_order()
            self._apply_user_sort()
            self.restore_context(context, select_first_if_missing=False)
        finally:
            self.blockSignals(previous_block_state)
            self.setUpdatesEnabled(True)
        self.viewport().update()
        return added, updated

    def _update_row_values(self, row_index: int, values: list[str]) -> None:
        for column in range(self.columnCount()):
            value = str(values[column] if column < len(values) else "")
            item = self.item(row_index, column)
            if item is None:
                self.setItem(row_index, column, QTableWidgetItem(value))
            elif value or not item.text().strip():
                item.setText(value)

    def _row_texts(self, row_index: int) -> list[str]:
        return [
            self.item(row_index, column).text().strip()
            if self.item(row_index, column) is not None
            else ""
            for column in range(self.columnCount())
        ]

    @staticmethod
    def _candidate_key_from_values(values: list[str]) -> tuple[str, str] | None:
        if len(values) < 2:
            return None
        source = str(values[0] or "").strip().upper()
        entry_id = str(values[1] or "").strip()
        return (source, entry_id) if source and entry_id else None

    def _score_insertion_index(self, values: list[str]) -> int:
        score_column = self._column_index(
            self.GAIN_HEADER if self._gain_active else self.MATCH_HEADER
        )
        if score_column < 0:
            return self.rowCount()
        incoming_score = self._score_number(
            values[score_column] if score_column < len(values) else ""
        )
        if incoming_score <= 0.0:
            return self.rowCount()
        for row_index in range(self.rowCount()):
            item = self.item(row_index, score_column)
            existing_score = self._score_number(item.text() if item is not None else "")
            if incoming_score > existing_score:
                return row_index
        return self.rowCount()

    @staticmethod
    def _score_number(value: object) -> float:
        try:
            text = str(value or "").replace("%", "").replace(",", ".")
            text = text.removeprefix("←").removeprefix("→").strip()
            return float(text) if text else 0.0
        except (TypeError, ValueError):
            return 0.0

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
            header = self.HEADERS[column]
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

    def ensure_visible_selection(self) -> None:
        current = self.currentRow()
        if current >= 0 and not self.isRowHidden(current):
            return
        for row in range(self.rowCount()):
            if not self.isRowHidden(row):
                self.setCurrentCell(row, 0)
                self.selectRow(row)
                self.scrollToTop()
                return

    def all_row_values(self) -> list[dict[str, str]]:
        return [self.row_values(row) for row in range(self.rowCount())]

    def set_iic(self, row: int, value: str) -> None:
        if not value or row < 0 or row >= self.rowCount():
            return
        item = self.item(row, self.columnCount() - 1)
        if item is not None:
            item.setText(value)
            self._schedule_user_sort()

    def set_probability(self, row: int, value: str) -> None:
        if not value or row < 0 or row >= self.rowCount():
            return
        column = self._column_index(self.MATCH_HEADER)
        if column < 0:
            return
        item = self.item(row, column)
        if item is not None:
            item.setText(self._score_display_text(column, value))
            self._schedule_user_sort()

    def set_scoring_stage(self, gain_active: bool) -> None:
        """Point the user to the score that controls the current ranking."""
        self._requested_gain_stage = bool(gain_active)
        if self._selected_peak_scoring:
            gain_active = False
        self._gain_active = bool(gain_active)
        match_column = self._column_index(self.MATCH_HEADER) if self._column_index(self.MATCH_HEADER) >= 0 else 5
        gain_column = self._column_index(self.GAIN_HEADER) if self._column_index(self.GAIN_HEADER) >= 0 else 6
        match_item = self.horizontalHeaderItem(match_column)
        gain_item = self.horizontalHeaderItem(gain_column)
        if match_item is None or gain_item is None:
            return
        match_item.setText(self.DISPLAY_HEADERS[5])
        gain_item.setText("Gain (%)")
        colors = theme_colors(is_dark_theme(self))
        match_item.setBackground(QBrush() if gain_active else QBrush(QColor(colors['match'])))
        match_item.setForeground(QBrush() if gain_active else QBrush(QColor(colors['semantic_text'])))
        gain_item.setBackground(QBrush(QColor(colors['gain'])) if gain_active else QBrush())
        gain_item.setForeground(QBrush(QColor(colors['semantic_text'])) if gain_active else QBrush())
        match_item.setToolTip(
            "Fraction of manually selected peaks matched one-to-one by this phase. "
            "Not an identification probability; unselected lines are not penalized."
            if self._selected_peak_scoring else
            "Normalized peak-compatibility score for ranking candidates against the active XRD pattern. "
            "Not a statistical probability of phase presence or a mass fraction."
        )
        gain_item.setToolTip(
            "Additional phase support after accounting for accepted phases. Depending on available data, "
            "Gain uses peak support or reduction of weighted profile error. "
            "Not a mass fraction or probability; per-row tooltips describe the calculation."
        )
        self._apply_score_arrows()

    def set_joint_gain_diagnostics(self, diagnostics: dict) -> None:
        self._gain_result_keys = {self._candidate_key_from_values(self._row_texts(row)) for row in range(self.rowCount())}
        for row in range(self.rowCount()):
            source, entry, item = self.item(row, 0), self.item(row, 1), self.item(row, 6)
            if source is None or entry is None or item is None:
                continue
            data = diagnostics.get(f'{source.text()}:{entry.text()}', {})
            tooltip = ''
            if data.get('model') == 'experimental_joint':
                mass = data.get('mass_percent')
                quantity = f'~{mass:.2f}% mass' if mass is not None else 'unavailable (non-identifiable fit)'
                tooltip = (
                    'Experimental joint structural profile fit\n'
                    f"Gain: {data['gain_percent']:.3g}% reduction of weighted squared error / target energy\n"
                    f'Conditional candidate quantity: {quantity}\n'
                    f"Supported lines: {data['supported_lines']}; independent: {data['independent_lines']}\n"
                    'Quantity is normalized among the included crystalline phases, not identification probability.'
                )
                if not data.get('accepted'):
                    tooltip += '\nInsufficient independent reflection support; not promoted.'
            elif data.get('model') == 'legacy':
                tooltip = f"Legacy Gain: {data.get('reason', 'Physical model unavailable')}"
            item.setToolTip(tooltip)

    def set_selected_peak_scoring(self, active: bool) -> None:
        self._selected_peak_scoring = bool(active)
        self.setColumnHidden(6, bool(active))
        self.set_scoring_stage(self._requested_gain_stage)

    def set_score_context(self, *, has_pattern: bool, match_enabled: bool, gain_enabled: bool,
                          match_busy: bool = False, gain_busy: bool = False, identity=None) -> None:
        if identity != self._score_identity:
            self._gain_result_keys.clear()
            self._score_identity = identity
        self._score_context = dict(has_pattern=has_pattern, match_enabled=match_enabled,
                                   gain_enabled=gain_enabled, match_busy=match_busy, gain_busy=gain_busy)
        self.viewport().update()

    def score_display_text(self, row: int, column: int) -> str:
        item = self.item(row, column)
        raw = item.text().strip() if item is not None else ''
        if raw:
            return raw
        key = self._candidate_key_from_values(self._row_texts(row))
        if column == 5:
            if key in self._match_failures:
                return 'Error'
            if key in self._match_unavailable:
                return 'Unavailable'
        context = self._score_context
        active = context['has_pattern'] and (
            context['match_enabled'] and not self._gain_active if column == 5 else
            context['gain_enabled'] and self._gain_active and not self._selected_peak_scoring)
        if key is None or not active:
            return 'Inactive'
        if context['match_busy' if column == 5 else 'gain_busy']:
            return 'Calculating…'
        if column == 6 and key in self._gain_result_keys:
            return 'No score'
        return 'Not calculated'

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
        self._apply_match_diagnostics()

    def set_match_diagnostics(self, failures, unavailable_keys):
        self._match_failures = dict(failures)
        self._match_unavailable = set(unavailable_keys)
        self._apply_match_diagnostics()

    def _apply_match_diagnostics(self):
        for row in range(self.rowCount()):
            source, entry, item = self.item(row, 0), self.item(row, 1), self.item(row, 5)
            if source is None or entry is None or item is None:
                continue
            key = (source.text().strip().upper(), entry.text().strip())
            reason = self._match_failures.get(key, '')
            if not reason and key in self._match_unavailable:
                reason = 'Reference reflections are unavailable or not prepared; Match was not calculated.'
            item.setToolTip(f'Match failed: {reason}' if key in self._match_failures else reason)
            colors = theme_colors(widget=self)
            item.setBackground(QBrush(QColor(colors['warning'])) if reason else QBrush())
            item.setForeground(QBrush(QColor(colors['semantic_text'])) if reason else QBrush())

    def _column_index(self, header: str) -> int:
        # UI captions may evolve; calculation and saved-result keys stay stable.
        if header in self.HEADERS:
            return self.HEADERS.index(header)
        if header in self.DISPLAY_HEADERS:
            return self.DISPLAY_HEADERS.index(header)
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
        if getattr(self, '_manual_column_layout', False):
            self._apply_column_layout_lock()
            return
        density=getattr(self.window(),"_ui_density_factor",1.)
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
            entry_width = round(min(max(self.columnWidth(1), 90*density), 170*density))
            formula_width = round(min(max(self.columnWidth(2), 150*density), 260*density))
        else:
            entry_width = round(130*density)
            formula_width = round(190*density)
        self.setColumnWidth(0, max(6,round(58*density)))
        self.setColumnWidth(1, entry_width)
        self.setColumnWidth(2, formula_width)
        self.setColumnWidth(4, max(6,round(92*density)))
        self.setColumnWidth(5, max(6,round(128*density)))
        self.setColumnWidth(6, max(6,round(108*density)))
        self.setColumnWidth(7, max(6,round(72*density)))
        self._apply_column_layout_lock()


class SelectedCandidatesTableWidget(_ColumnLayoutTableWidget):
    rowClicked = Signal(int)
    contextRequested = Signal(QPoint)
    phaseNameEdited = Signal(int, str)

    HEADERS = ["Color", "Phase", "Fit / Peaks", "Quant. (%)", "I/Ic"]
    DISPLAY_HEADERS = ["Color", "Phase name", "Fit / Peaks", "Est. wt.%", "I/Ic"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self._column_resize_timer = QTimer(self)
        self._column_resize_timer.setSingleShot(True)
        self._column_resize_timer.timeout.connect(self._resize_columns)
        self.setToolTip(
            "Selected phases\n"
            "Single click: show the calculated profile and markers for this phase.\n"
            "Double click the Phase cell to rename the phase for tables and figures.\n"
            "Right click: rename, change color, export CIF, remove phase, or clear the list."
        )
        self.setHorizontalHeaderLabels(self.DISPLAY_HEADERS)
        self.setItemDelegateForColumn(0, _PhaseColorDelegate(self))
        self.setItemDelegateForColumn(1, FormulaDisplayDelegate(self))
        self.horizontalHeaderItem(2).setToolTip(
            "Overall profile-fit score shared by the selected phases, followed by this phase's matched / total reference-reflection counts. "
            "Separate from phase mass-fraction estimation; not a Rietveld R-factor."
        )
        self.horizontalHeaderItem(3).setToolTip(
            "Estimated mass fractions among the selected crystalline phases, using "
            "absolute integrated profiles and Hill–Howard S × (ZM) × V. "
            "A dash means the physical scale, structure metadata or phase separation is unavailable."
        )
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
        )
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setShowGrid(False)
        self.verticalHeader().setDefaultSectionSize(32)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_request)
        self.cellClicked.connect(self._emit_row_clicked)
        self.itemChanged.connect(self._emit_phase_name_edited)
        self.horizontalHeaderItem(len(self.HEADERS) - 1).setToolTip(
            "~: calculated ideal-powder I/Ic, Cu K-alpha1, relative to the cached corundum reference."
        )
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
                    item = QTableWidgetItem('' if column == 0 else value)
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
        self._column_resize_timer.start(0)
        self.phaseNameEdited.emit(item.row(), item.text().strip())

    def edit_phase_name(self, row: int) -> None:
        item = self.item(row, 1)
        if item is None:
            return
        self.setCurrentItem(item)
        self.editItem(item)

    def _resize_columns(self) -> None:
        if getattr(self, '_manual_column_layout', False):
            self._apply_column_layout_lock()
            return
        if getattr(self, '_resizing_columns', False):
            return
        self._resizing_columns = True
        try:
            self._fit_columns_to_text()
        finally:
            self._resizing_columns = False

    def _fit_columns_to_text(self) -> None:
        density = getattr(self.window(), '_ui_density_factor', 1.)
        header = self.horizontalHeader()
        if header is None:
            return
        header.setStretchLastSection(False)
        padding = max(4, round(16*density))
        widths = {}
        for column in range(self.columnCount()):
            item = self.horizontalHeaderItem(column)
            label = item.text() if item is not None else self.DISPLAY_HEADERS[column]
            label_width = header.fontMetrics().horizontalAdvance(label) + padding
            values = [self.item(row, column).text() for row in range(self.rowCount())
                      if self.item(row, column) is not None]
            content_width = max((self.fontMetrics().horizontalAdvance(value) for value in values), default=0) + padding
            # Qt's delegate hint also includes stylesheet padding and the
            # actual painted font, which can differ from the table font.
            styled_width = self.sizeHintForColumn(column) + max(2, round(8*density))
            widths[column] = max(label_width, content_width, styled_width)
        widths[1] = max(widths[1], self.viewport().width()-sum(width for col, width in widths.items() if col != 1))
        for column, width in widths.items():
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive if column == 1 else QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(column, width)
        self.verticalHeader().setDefaultSectionSize(max(round(32*density), self.fontMetrics().height()+round(12*density)))
        self._apply_column_layout_lock()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_columns()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        timer = getattr(self, '_column_resize_timer', None)
        if timer is not None and event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            timer.start(0)
