from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from crystal_viewer.analysis.hierarchy import HierarchyLevel
from crystal_viewer.analysis.structure_profile import ResolvedProfile
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.site_orbits import (
    bond_families,
    connector_orbits,
    hierarchy_object_orbits,
    polyhedron_orbits,
)
from crystal_viewer.knowledge.resolve import resolve_interpretation


Payload = tuple[str, str, object]


class HierarchyTree(QTreeWidget):
    """Collection-aware hierarchy browser with independent A/B/compare state."""

    active_requested = Signal(str)
    visual_slot_requested = Signal(str, str)
    compare_toggled = Signal(str, bool)
    visibility_changed = Signal(str, str, object, bool)
    object_selected = Signal(str, str, object)
    SearchTextRole = int(Qt.ItemDataRole.UserRole) + 20

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._collection: StructureCollection | None = None
        self._updating = False
        self._root_buttons: list[QToolButton] = []
        self._root_labels: list[QLabel] = []
        self.setColumnCount(1)
        self.setHeaderLabels(("Structures",))
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.currentItemChanged.connect(self._current_item_changed)

    def set_collection(self, collection: StructureCollection) -> None:
        self._collection = collection
        self._updating = True
        try:
            self.clear()
            self._root_buttons.clear()
            self._root_labels.clear()
            for document_id in collection.order:
                document = collection.documents[document_id]
                item = self._document_root(document)
                self.addTopLevelItem(item)
                self._install_root_widget(item, document)
            self.collapseAll()
            QTimer.singleShot(0, self.collapseAll)
        finally:
            self._updating = False

    def _document_root(self, document: StructureDocument) -> QTreeWidgetItem:
        root = QTreeWidgetItem([""])
        root.setData(0, Qt.ItemDataRole.UserRole, (document.id, "structure", document.id))
        root.setData(0, self.SearchTextRole, document.structure.name)
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        root.setSizeHint(0, QSize(0, 28))

        cell = self._leaf(document.id, "cell", "cell", "Unit Cell")
        root.addChild(cell)

        profile = document.profile_decision
        if profile is not None and profile.resolved is not ResolvedProfile.INORGANIC:
            report = document.organic_analysis
            bonds = report.bonds if report is not None else None
            components = report.components if report is not None else None
            contacts = report.contacts if report is not None else None
            packing = report.packing if report is not None else None
            reticular = report.reticular if report is not None else None
            organic_groups = [
                ("atoms", f"Atoms ({len(document.structure.asymmetric_sites)})", True),
                (
                    "covalent_bonds",
                    f"Covalent Bonds ({len(bonds.covalent) if bonds is not None else 0})",
                    bonds is not None,
                ),
                (
                    "coordination_bonds",
                    f"Coordination Bonds ({len(bonds.coordination) if bonds is not None else 0})",
                    bonds is not None,
                ),
                (
                    "molecules",
                    f"Molecules ({len(components.components) if components is not None else 0})",
                    components is not None,
                ),
                (
                    "rings",
                    f"Rings ({len(components.rings) if components is not None else 0})",
                    components is not None,
                ),
                (
                    "contacts",
                    f"Contacts ({len(contacts.contacts) if contacts is not None else 0})",
                    contacts is not None,
                ),
                (
                    "packing",
                    f"Packing Assemblies ({len(packing.assemblies) if packing is not None else 0})",
                    packing is not None,
                ),
                (
                    "voids",
                    f"Geometric Voids ({len(packing.voids) if packing is not None else 0})",
                    packing is not None,
                ),
            ]
            if profile.resolved is ResolvedProfile.RETICULAR:
                organic_groups.extend(
                    (
                        (
                            "coordination_nodes",
                            f"Coordination Nodes ({len(reticular.coordination_nodes) if reticular is not None else 0})",
                            reticular is not None,
                        ),
                        (
                            "linkers",
                            f"Linkers ({len(reticular.linkers) if reticular is not None else 0})",
                            reticular is not None,
                        ),
                        (
                            "sbus",
                            f"SBUs ({len(reticular.sbus) if reticular is not None else 0})",
                            reticular is not None,
                        ),
                        (
                            "organic_topology",
                            f"Underlying Topology ({len(reticular.underlying_edges) if reticular is not None else 0})",
                            reticular is not None,
                        ),
                    )
                )
            for kind, label, ready in organic_groups:
                item = self._group(
                    document.id,
                    "category",
                    label if ready else f"{label.split(' (', 1)[0]} — calculating…",
                    object_id=kind,
                )
                if not ready:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                root.addChild(item)
            return root

        bond_count = len(bond_families(document))
        polyhedron_count = len(polyhedron_orbits(document))
        unit_count = len(
            hierarchy_object_orbits(document, document.hierarchy.structural_units)
        )
        block_count = len(
            hierarchy_object_orbits(document, document.hierarchy.blocks)
        )
        connector_count = len(connector_orbits(document))
        topology_count = (
            len(document.inorganic_topology.families)
            + len(document.inorganic_topology.cation_families)
            if document.inorganic_topology is not None
            else 0
        )
        stage_order = {
            "parsed": 0,
            "bonds": 1,
            "polyhedra": 2,
            "units": 3,
            "topology": 4,
        }
        current_stage = stage_order.get(document.analysis_stage, 4)
        required_stage = {
            "atoms": 0,
            "bonds": 1,
            "polyhedra": 2,
            "units": 3,
            "interpretations": 3,
            "blocks": 3,
            "connectors": 3,
            "topology": 4,
        }
        for kind, label in (
            ("atoms", f"Atoms ({len(document.structure.asymmetric_sites)})"),
            ("bonds", f"Bonds ({bond_count})"),
            ("polyhedra", f"Polyhedra ({polyhedron_count})"),
            ("units", f"Structural Units ({unit_count})"),
            ("interpretations", f"Interpretation ({len(document.hierarchy.structural_domains)})"),
            ("blocks", f"Rigid Blocks ({block_count})"),
            ("connectors", f"Shared sites / pivot candidates ({connector_count})"),
            ("topology", f"Topology ({topology_count})"),
        ):
            ready = current_stage >= required_stage[kind]
            item = self._group(
                document.id,
                "category",
                label if ready else f"{label.split(' (', 1)[0]} — calculating…",
                object_id=kind,
            )
            if not ready:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            root.addChild(item)
        return root

    @staticmethod
    def _unit_name(document: StructureDocument, unit) -> str:
        analysis = document.structural_analysis
        if analysis is None:
            return unit.classification
        direct_assignment = next(
            (item for item in analysis.nomenclature if item.domain_id == unit.id),
            None,
        )
        domain = next(
            (
                item
                for item in analysis.structural_domains
                if item.polyhedron_ids == unit.polyhedron_ids
            ),
            None,
        )
        if domain is None and direct_assignment is None:
            return unit.classification
        assignment = direct_assignment or next(
            (item for item in analysis.nomenclature if item.domain_id == domain.id),  # type: ignore[union-attr]
            None,
        )
        if assignment is None:
            return unit.classification
        if assignment.vocabulary == "borate" and "-membered ring" in unit.classification:
            generic = unit.classification.split(" · ", 1)[0]
            descriptor = assignment.descriptor.replace(
                f"{len(unit.polyhedron_ids)}-membered ",
                "",
                1,
            )
            return f"{generic} · {descriptor}"
        return f"{unit.classification} · {assignment.descriptor}"

    def _install_root_widget(
        self,
        item: QTreeWidgetItem,
        document: StructureDocument,
    ) -> None:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(1, 0, 3, 0)
        layout.setSpacing(7)
        button = QToolButton(container)
        button.setObjectName("structureCompareCheck")
        button.setCheckable(True)
        button.setFixedSize(20, 20)
        button.setToolTip("Select structure for comparison")
        button.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #8da0b5; "
            "border-radius: 4px; color: #ffffff; font-weight: 800; padding: 0; }"
            "QToolButton:checked { background: #2678c8; border-color: #1f68b1; }"
        )
        selected = self._collection is not None and document.id in self._collection.compared_ids
        button.setChecked(selected)
        self._update_check_visual(button, selected)
        button.toggled.connect(
            lambda checked, document_id=document.id, current=button: self._root_toggled(
                document_id,
                current,
                checked,
            )
        )
        layout.addWidget(button)
        label = QLabel(document.structure.name, container)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(label, 1)
        self.setItemWidget(item, 0, container)
        self._root_buttons.append(button)
        self._root_labels.append(label)

    @staticmethod
    def _update_check_visual(button: QToolButton, checked: bool) -> None:
        button.setText("✓" if checked else "")

    def _root_toggled(
        self,
        document_id: str,
        button: QToolButton,
        checked: bool,
    ) -> None:
        if self._updating:
            self._update_check_visual(button, checked)
            return
        if checked and sum(candidate.isChecked() for candidate in self._root_buttons) > 2:
            self._updating = True
            try:
                button.setChecked(False)
                self._update_check_visual(button, False)
            finally:
                self._updating = False
            return
        self._update_check_visual(button, checked)
        self.compare_toggled.emit(document_id, checked)

    def root_checkbox(self, index: int) -> QToolButton:
        return self._root_buttons[index]

    def root_label(self, index: int) -> QLabel:
        return self._root_labels[index]

    @staticmethod
    def _payload(document_id: str, kind: str, object_id: object) -> Payload:
        return document_id, kind, object_id

    def _group(
        self,
        document_id: str,
        kind: str,
        label: str,
        level: HierarchyLevel | None = None,
        object_id: object | None = None,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        resolved_id: object = level.value if level is not None else object_id if object_id is not None else label
        payload_kind = "level" if level is not None else kind
        item.setData(0, Qt.ItemDataRole.UserRole, self._payload(document_id, payload_kind, resolved_id))
        return item

    def _leaf(
        self,
        document_id: str,
        kind: str,
        object_id: object,
        label: str,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, self._payload(document_id, kind, object_id))
        return item

    def _current_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        payload = current.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        document_id, kind, object_id = payload
        self.active_requested.emit(document_id)
        self.object_selected.emit(document_id, kind, object_id)
