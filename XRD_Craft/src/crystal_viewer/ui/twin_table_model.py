from __future__ import annotations

from enum import IntEnum

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from crystal_viewer.analysis.twin_geometry import TwinAggregate
from crystal_viewer.analysis.twin_state import TwinAggregateSpec


class TwinColumn(IntEnum):
    ID = 0
    AGGREGATE = 1
    ORIENTATION = 2
    LAW = 3
    COMPOSITION = 4
    FRACTION = 5
    STATE = 6


class TwinTableModel(QAbstractTableModel):
    DomainRole = int(Qt.ItemDataRole.UserRole) + 1
    HEADERS = (
        "Individual / lamella",
        "Aggregate",
        "Orientation",
        "Twin law",
        "Composition plane",
        "Interval / fraction",
        "State",
    )

    def __init__(
        self,
        aggregate: TwinAggregate | None,
        parent=None,
        *,
        spec: TwinAggregateSpec | None = None,
    ) -> None:
        super().__init__(parent)
        self.aggregate = aggregate
        self.spec = spec
        self.domains = () if aggregate is None else aggregate.domains

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.domains)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def _aggregate_name(self) -> str:
        if self.spec is not None:
            return self.spec.kind.value
        if any(domain.slab_interval is not None for domain in self.domains):
            return "polysynthetic"
        if self.aggregate is not None and self.aggregate.composition_planes:
            return "contact"
        return "penetration" if self.domains else ""

    def _law_text(self) -> str:
        if self.spec is None:
            return ""
        law = self.spec.law
        if law.plane_hkl is not None:
            return f"reflection ({' '.join(map(str, law.plane_hkl))})"
        if law.axis_uvw is not None:
            return f"twofold [{' '.join(map(str, law.axis_uvw))}]"
        return "matrix U"

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.domains):
            return None
        domain = self.domains[index.row()]
        if role == self.DomainRole:
            return domain.domain_id
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        composition = ""
        if self.spec is not None:
            hkl = self.spec.resolved_composition_plane_hkl
            composition = f"({' '.join(map(str, hkl))})"
        interval = ""
        if domain.slab_interval is not None:
            low, high = domain.slab_interval
            interval = f"{low:.6g} … {high:.6g} · width {high - low:.6g}"
        values = {
            TwinColumn.ID: domain.domain_id,
            TwinColumn.AGGREGATE: self._aggregate_name(),
            TwinColumn.ORIENTATION: domain.orientation_state,
            TwinColumn.LAW: self._law_text(),
            TwinColumn.COMPOSITION: composition,
            TwinColumn.FRACTION: interval,
            TwinColumn.STATE: "ready",
        }
        return values[TwinColumn(index.column())]


__all__ = ["TwinColumn", "TwinTableModel"]
