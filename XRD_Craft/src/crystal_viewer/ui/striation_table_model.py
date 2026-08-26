from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from crystal_viewer.analysis.morphology import Hkl
from crystal_viewer.analysis.surface_markings import SurfaceMarking, SurfaceMarkingKind


class StriationColumn(IntEnum):
    VISIBLE = 0
    FAMILY = 1
    TYPE = 2
    DENSITY = 3
    LINE_WIDTH = 4
    PROVENANCE = 5
    STATE = 6


@dataclass(frozen=True, slots=True)
class StriationEdit:
    family_hkl: Hkl
    marking: SurfaceMarking | None


class StriationTableModel(QAbstractTableModel):
    edit_requested = Signal(object)

    FamilyRole = int(Qt.ItemDataRole.UserRole) + 1
    HEADERS = ("On", "Family {hkl}", "Type", "Density", "Line width", "Provenance", "State")

    def __init__(
        self,
        families,
        markings,
        twin_available: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.families = tuple(sorted(tuple(hkl) for hkl in families))
        self.twin_available = bool(twin_available)
        self._markings = {
            item.target_family: item
            for item in markings
        }
        self._errors: dict[Hkl, str] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.families)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.families):
            return None
        family = self.families[index.row()]
        marking = self._markings.get(family)
        column = StriationColumn(index.column())
        if role == self.FamilyRole:
            return family
        if role == Qt.ItemDataRole.CheckStateRole and column is StriationColumn.VISIBLE:
            return Qt.CheckState.Checked if marking is not None else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.EditRole:
            if column is StriationColumn.TYPE:
                return "none" if marking is None else marking.kind.value
            if column is StriationColumn.DENSITY:
                return 6 if marking is None else marking.density
            if column is StriationColumn.LINE_WIDTH:
                return 1.5 if marking is None else marking.line_width
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._errors.get(family)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        provenance = (
            ""
            if marking is None
            else "manual"
            if marking.kind is SurfaceMarkingKind.INDUCTION
            else "derived-polysynthetic"
        )
        values = {
            StriationColumn.VISIBLE: "",
            StriationColumn.FAMILY: f"({family[0]} {family[1]} {family[2]})",
            StriationColumn.TYPE: "none" if marking is None else marking.kind.value,
            StriationColumn.DENSITY: "" if marking is None else str(marking.density),
            StriationColumn.LINE_WIDTH: "" if marking is None else f"{marking.line_width:g}",
            StriationColumn.PROVENANCE: provenance,
            StriationColumn.STATE: self._errors.get(family, "ready" if marking is not None else "available"),
        }
        return values[column]

    def flags(self, index):
        flags = super().flags(index) | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not index.isValid():
            return flags
        column = StriationColumn(index.column())
        family = self.families[index.row()]
        marking = self._markings.get(family)
        if column is StriationColumn.VISIBLE:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if column is StriationColumn.TYPE:
            flags |= Qt.ItemFlag.ItemIsEditable
        if column in (StriationColumn.DENSITY, StriationColumn.LINE_WIDTH) and (
            marking is None or marking.kind is SurfaceMarkingKind.INDUCTION
        ):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def _emit(self, family: Hkl, marking: SurfaceMarking | None) -> bool:
        self._errors.pop(family, None)
        if marking is None:
            self._markings.pop(family, None)
        else:
            self._markings[family] = marking
        self.layoutChanged.emit()
        self.edit_requested.emit(StriationEdit(family, marking))
        return True

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        family = self.families[index.row()]
        column = StriationColumn(index.column())
        current = self._markings.get(family)
        if column is StriationColumn.VISIBLE and role == Qt.ItemDataRole.CheckStateRole:
            raw = value.value if isinstance(value, Qt.CheckState) else int(value)
            if raw == Qt.CheckState.Unchecked.value:
                return self._emit(family, None)
            return self._emit(
                family,
                current or SurfaceMarking(family, SurfaceMarkingKind.INDUCTION),
            )
        if role != Qt.ItemDataRole.EditRole:
            return False
        if column is StriationColumn.TYPE:
            try:
                text = str(value).strip().lower()
                if text in ("", "none"):
                    return self._emit(family, None)
                kind = SurfaceMarkingKind(text)
                if kind is SurfaceMarkingKind.TWIN and not self.twin_available:
                    self._errors[family] = "Twin striation requires a polysynthetic twin aggregate."
                    self.dataChanged.emit(index, self.index(index.row(), StriationColumn.STATE))
                    return False
                return self._emit(
                    family,
                    SurfaceMarking(
                        family,
                        kind,
                        6 if current is None else current.density,
                        1.5 if current is None else current.line_width,
                    ),
                )
            except (TypeError, ValueError):
                return False
        if current is None or current.kind is SurfaceMarkingKind.TWIN:
            return False
        try:
            if column is StriationColumn.DENSITY:
                marking = SurfaceMarking(family, current.kind, int(value), current.line_width)
            elif column is StriationColumn.LINE_WIDTH:
                marking = SurfaceMarking(family, current.kind, current.density, float(value))
            else:
                return False
        except (TypeError, ValueError):
            return False
        return self._emit(family, marking)


__all__ = ["StriationColumn", "StriationEdit", "StriationTableModel"]
