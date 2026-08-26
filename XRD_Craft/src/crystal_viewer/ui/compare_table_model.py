from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from crystal_viewer.analysis.comparison import (
    ComparisonReport,
    ComparisonRow,
    ComparisonState,
    SectionSummary,
)


SECTION_ORDER = (
    "Unit Cell",
    "Polyhedra",
    "Structural Motifs",
    "Connections and Interstitial Atoms",
    "Topology",
    "Warnings and Data Quality",
)

_SECTION_ALIASES = {
    "Crystal data": "Unit Cell",
    "Coordination": "Polyhedra",
    "Coordination chemistry": "Polyhedra",
    "MoO6 geometry": "Polyhedra",
}


@dataclass(frozen=True, slots=True)
class _SectionNode:
    summary: SectionSummary
    rows: tuple[ComparisonRow, ...]


@dataclass(frozen=True, slots=True)
class _RowNode:
    section: _SectionNode
    row: ComparisonRow


class CompareTableModel(QAbstractItemModel):
    StateRole = int(Qt.ItemDataRole.UserRole) + 1
    RawValueRole = StateRole + 1
    WarningRole = RawValueRole + 1
    FocusRole = WarningRole + 1
    ExpandedRecordsRole = FocusRole + 1
    SectionSummaryRole = ExpandedRecordsRole + 1

    _BACKGROUND = {
        ComparisonState.SIMILAR: QColor("#e8f5ec"),
        ComparisonState.MODERATE: QColor("#fff4d6"),
        ComparisonState.DIFFERENT: QColor("#fde8e7"),
        ComparisonState.UNAVAILABLE: QColor("#eef1f4"),
    }
    _SECTION_BACKGROUND = QColor("#e7f1fb")

    def __init__(self, report: ComparisonReport, parent=None) -> None:
        super().__init__(parent)
        self.report = report
        self._differences_only = False
        self._sections: tuple[_SectionNode, ...] = ()
        self._row_nodes: dict[int, _RowNode] = {}
        self._rebuild_sections()

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if row < 0 or column < 0 or column >= self.columnCount():
            return QModelIndex()
        if not parent.isValid():
            if row >= len(self._sections):
                return QModelIndex()
            return self.createIndex(row, column, self._sections[row])
        if parent.column() != 0:
            return QModelIndex()
        node = parent.internalPointer()
        if not isinstance(node, _SectionNode) or row >= len(node.rows):
            return QModelIndex()
        row_node = self._row_nodes[id(node.rows[row])]
        return self.createIndex(row, column, row_node)

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if not isinstance(node, _RowNode):
            return QModelIndex()
        try:
            section_row = self._sections.index(node.section)
        except ValueError:
            return QModelIndex()
        return self.createIndex(section_row, 0, node.section)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._sections)
        if parent.column() != 0:
            return 0
        node = parent.internalPointer()
        return len(node.rows) if isinstance(node, _SectionNode) else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.report.document_ids) + 1

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return "Characteristic" if section == 0 else self.report.document_titles[section - 1]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if isinstance(node, _SectionNode):
            return self._section_data(node, index.column(), role)
        if not isinstance(node, _RowNode):
            return None
        return self._row_data(node.row, index.column(), role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def comparison_row(self, index: QModelIndex) -> ComparisonRow | None:
        if not index.isValid():
            return None
        node = index.internalPointer()
        return node.row if isinstance(node, _RowNode) else None

    def row_at(self, index: int) -> ComparisonRow:
        rows = tuple(row for section in self._sections for row in section.rows)
        return rows[index]

    def set_show_differences_only(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._differences_only:
            return
        self.beginResetModel()
        self._differences_only = enabled
        self._rebuild_sections()
        self.endResetModel()

    def _rebuild_sections(self) -> None:
        grouped: dict[str, list[ComparisonRow]] = {name: [] for name in SECTION_ORDER}
        for row in self.report.rows:
            if self._differences_only and not row.has_difference:
                continue
            grouped[_section_name(row)].append(row)

        sections = []
        row_nodes: dict[int, _RowNode] = {}
        for name in SECTION_ORDER:
            rows = tuple(grouped[name])
            if self._differences_only and not rows:
                continue
            count = len(rows)
            summary = SectionSummary(
                name=name,
                difference_count=sum(row.has_difference for row in rows),
                summary=f"{count} characteristic{'s' if count != 1 else ''} compared",
            )
            section = _SectionNode(summary, rows)
            sections.append(section)
            for row in rows:
                row_nodes[id(row)] = _RowNode(section, row)
        self._sections = tuple(sections)
        self._row_nodes = row_nodes

    def _section_data(self, node: _SectionNode, column: int, role: int):
        if role == self.SectionSummaryRole:
            return node.summary
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return node.summary.name
            if column == 1:
                count = node.summary.difference_count
                return f"{count} difference{'s' if count != 1 else ''} · {node.summary.summary}"
            return ""
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._SECTION_BACKGROUND
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{node.summary.difference_count} differences; {node.summary.summary}"
        return None

    def _row_data(self, row: ComparisonRow, column: int, role: int):
        if column == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return row.title
            if role == self.FocusRole:
                return row.focus
            if role == self.ExpandedRecordsRole:
                return row.expanded_records
            if role == Qt.ItemDataRole.ToolTipRole:
                return f"Method: {row.method_id or '—'}"
            return None
        cell = row.cells[column - 1]
        if role == Qt.ItemDataRole.DisplayRole:
            return cell.display
        if role == self.StateRole:
            return cell.state
        if role == self.RawValueRole:
            return cell.raw
        if role == self.WarningRole:
            return cell.warning
        if role == self.FocusRole:
            return row.focus
        if role == self.ExpandedRecordsRole:
            return row.expanded_records
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._BACKGROUND[cell.state]
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [f"Method: {row.method_id or '—'}"]
            if cell.warning:
                parts.append(cell.warning)
            return "\n".join(parts)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None


def _section_name(row: ComparisonRow) -> str:
    identifier = row.descriptor_id.lower()
    if identifier.startswith(("occupancy.", "warning.", "quality.")):
        return "Warnings and Data Quality"
    prefix_mapping = (
        (("cell.",), "Unit Cell"),
        (("coordination.", "mo_o."), "Polyhedra"),
        (("motif.",), "Structural Motifs"),
        (("connection.", "connections.", "interstitial.", "substitution."),
         "Connections and Interstitial Atoms"),
        (("topology.",), "Topology"),
    )
    for prefixes, section in prefix_mapping:
        if identifier.startswith(prefixes):
            return section
    if row.section in SECTION_ORDER:
        return row.section
    return _SECTION_ALIASES.get(row.section, "Warnings and Data Quality")
