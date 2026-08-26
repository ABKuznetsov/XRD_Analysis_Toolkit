from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from collections.abc import Mapping

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from crystal_viewer.analysis.morphology import Hkl
from crystal_viewer.analysis.morphology_geometry import MorphologyModel
from crystal_viewer.ui.morphology_colors import allocate_family_colors


class MorphologyColumn(IntEnum):
    ENABLED = 0
    HKL = 1
    D_HKL = 2
    ORDER = 3
    D_EFFECTIVE = 4
    BFDH_RHO0 = 5
    CURRENT_RHO = 6
    AREA = 7
    REFERENCE_FRACTION = 8
    CURRENT_FRACTION = 9
    FRACTION = 9
    ORIGIN = 10
    STATE = 11


@dataclass(frozen=True, slots=True)
class MorphologyTableEdit:
    hkl: Hkl
    rho: float | None = None
    enabled: bool | None = None


class MorphologyTableModel(QAbstractTableModel):
    edit_requested = Signal(object)

    FamilyRole = int(Qt.ItemDataRole.UserRole) + 1
    ManualRole = int(Qt.ItemDataRole.UserRole) + 2
    ManifestRole = int(Qt.ItemDataRole.UserRole) + 3
    ErrorRole = int(Qt.ItemDataRole.UserRole) + 4
    ColorRole = int(Qt.ItemDataRole.UserRole) + 5

    HEADERS = (
        "On",
        "Family {hkl}",
        "d(hkl), Å",
        "Order",
        "d effective, Å",
        "BFDH rho₀",
        "Current rho",
        "Area",
        "Reference fraction, %",
        "Current fraction, %",
        "Origin",
        "State",
    )

    def __init__(
        self,
        model: MorphologyModel,
        parent=None,
        *,
        color_by_family: Mapping[Hkl, str] | None = None,
        reference_model: MorphologyModel | None = None,
        primary_families: set[Hkl] | tuple[Hkl, ...] = (),
        user_added_families: set[Hkl] | tuple[Hkl, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.color_by_family = color_by_family or allocate_family_colors(
            plane.family.hkl for plane in model.planes
        )
        self.reference_model = reference_model or model
        self.primary_families = frozenset(primary_families)
        self.user_added_families = frozenset(user_added_families)
        self._errors: dict[tuple[int, int], str] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.model.planes)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    @staticmethod
    def _number(value: float) -> str:
        return f"{value:.6g}"

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.model.planes):
            return None
        plane = self.model.planes[index.row()]
        column = MorphologyColumn(index.column())
        hkl = plane.family.hkl
        area = self.model.area_by_family.get(hkl, 0.0)
        fraction = self.model.fraction_by_family.get(hkl, 0.0)
        reference_fraction = self.reference_model.fraction_by_family.get(hkl, 0.0)
        if role == Qt.ItemDataRole.CheckStateRole and column is MorphologyColumn.ENABLED:
            return Qt.CheckState.Checked if plane.enabled else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.EditRole and column is MorphologyColumn.CURRENT_RHO:
            return plane.rho
        if role == self.FamilyRole:
            return hkl
        if role == self.ManualRole:
            return plane.manual
        if role == self.ManifestRole:
            return area > 0.0
        if role == self.ErrorRole:
            return self._errors.get((index.row(), index.column()), "")
        if role == self.ColorRole:
            return self.color_by_family[hkl]
        if role == Qt.ItemDataRole.DecorationRole and column is MorphologyColumn.HKL:
            return QColor(self.color_by_family[hkl])
        if role == Qt.ItemDataRole.BackgroundRole and plane.manual:
            return QBrush(QColor("#fff3cf"))
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._errors.get((index.row(), index.column())) or plane.family.warning or None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        values = {
            MorphologyColumn.ENABLED: "",
            MorphologyColumn.HKL: f"({hkl[0]} {hkl[1]} {hkl[2]})",
            MorphologyColumn.D_HKL: self._number(plane.family.d_hkl),
            MorphologyColumn.ORDER: str(plane.family.allowed_order),
            MorphologyColumn.D_EFFECTIVE: self._number(plane.family.d_effective),
            MorphologyColumn.BFDH_RHO0: self._number(plane.rho0),
            MorphologyColumn.CURRENT_RHO: self._number(plane.rho),
            MorphologyColumn.AREA: self._number(area),
            MorphologyColumn.REFERENCE_FRACTION: self._number(100.0 * reference_fraction),
            MorphologyColumn.CURRENT_FRACTION: self._number(100.0 * fraction),
            MorphologyColumn.ORIGIN: (
                "user-added"
                if hkl in self.user_added_families
                else "primary 80%"
                if hkl in self.primary_families
                else "additional BFDH"
            ),
            MorphologyColumn.STATE: (
                "manual" if plane.manual else "not manifested" if area <= 0.0 else "BFDH"
            ),
        }
        return values[column]

    def flags(self, index: QModelIndex):
        flags = super().flags(index) | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if index.column() == MorphologyColumn.ENABLED:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == MorphologyColumn.CURRENT_RHO:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        plane = self.model.planes[index.row()]
        hkl = plane.family.hkl
        if index.column() == MorphologyColumn.ENABLED and role == Qt.ItemDataRole.CheckStateRole:
            raw_value = value.value if isinstance(value, Qt.CheckState) else int(value)
            enabled = raw_value == Qt.CheckState.Checked.value
            self.edit_requested.emit(MorphologyTableEdit(hkl, enabled=enabled))
            return True
        if index.column() != MorphologyColumn.CURRENT_RHO or role != Qt.ItemDataRole.EditRole:
            return False
        try:
            rho = float(str(value).strip().replace(",", "."))
        except ValueError:
            rho = math.nan
        key = (index.row(), index.column())
        if not math.isfinite(rho) or rho <= 0.0:
            self._errors[key] = "Distance must be a finite positive number."
            self.dataChanged.emit(index, index, [self.ErrorRole, Qt.ItemDataRole.ToolTipRole])
            return False
        self._errors.pop(key, None)
        self.edit_requested.emit(MorphologyTableEdit(hkl, rho=rho))
        return True


__all__ = ["MorphologyColumn", "MorphologyTableEdit", "MorphologyTableModel"]
