from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from crystal_viewer.analysis.reporting import ReportRow, ReportTable


class ReportTableModel(QAbstractTableModel):
    ProvenanceRole = int(Qt.ItemDataRole.UserRole) + 1
    SourceNameRole = ProvenanceRole + 1
    WarningRole = SourceNameRole + 1
    ObjectRefsRole = WarningRole + 1
    RawValueRole = ObjectRefsRole + 1

    def __init__(self, table: ReportTable, parent=None) -> None:
        super().__init__(parent)
        self.table = table
        self.columns = tuple(column for column in table.columns if column.visible)
        self.rows: list[ReportRow] = list(table.rows)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = self.columns[index.column()]
        cell = row.cells.get(column.id)
        if cell is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return cell.display
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if row.include_in_publication else Qt.CheckState.Unchecked
        if role == self.ProvenanceRole:
            return cell.provenance.value
        if role == self.SourceNameRole:
            return cell.source_name
        if role == self.WarningRole:
            return cell.warning
        if role == self.ObjectRefsRole:
            return row.object_refs
        if role == self.RawValueRole:
            value = cell.value
            return getattr(value, "raw", value)
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if (
            not index.isValid()
            or index.column() != 0
            or role != Qt.ItemDataRole.CheckStateRole
        ):
            return False
        included = value == Qt.CheckState.Checked
        self.rows[index.row()] = replace(
            self.rows[index.row()], include_in_publication=included
        )
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.columns):
            column = self.columns[section]
            return f"{column.title} [{column.unit}]" if column.unit else column.title
        return section + 1 if orientation == Qt.Orientation.Vertical else None
