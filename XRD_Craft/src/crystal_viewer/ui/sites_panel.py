from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from crystal_viewer.core.chemistry import site_colour
from crystal_viewer.core.site_orbits import (
    bond_families,
    connector_orbits,
    hierarchy_object_orbits,
    polyhedron_orbits,
    site_orbit_key,
    site_orbits,
)


_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_UNIT_COLORS = ("#2878b5", "#7b4ab8", "#008f7a", "#c05b2b", "#9a6b00")
_BLOCK_COLORS = ("#335c81", "#795548", "#536d3b", "#7a4d7b", "#8a6d1d")


class SitesPanel(QWidget):
    """One context-sensitive object table controlled by the hierarchy tree."""

    state_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._document = None
        self._updating = False
        self._color_mode = "automatic"
        self._comparison_locked = False
        self._category = "atoms"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.topology_status = QLabel()
        self.topology_status.setWordWrap(True)
        self.topology_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.topology_status.hide()
        layout.addWidget(self.topology_status)
        self.stack = QStackedWidget()
        self.atom_table = self._table(("Site", "Color", "Visible"))
        self.bond_table = self._table(("Bond", "Gradient", "Visible"))
        self.polyhedron_table = self._table(("Polyhedron", "Color", "Visible"))
        self.unit_table = self._table(("Structural unit", "Color", "Visible"))
        self.block_table = self._table(("Rigid block", "Color", "Visible"))
        self.interpretation_table = self._table(("Domain", "Interpretation"))
        self.connector_table = self._table(("Shared site", "Connection"))
        self.topology_table = self._table(
            ("Network", "Type", "Direction / plane", "Connections", "Visible")
        )
        self.organic_table = self._table(("Object", "Type", "Details", "Evidence"))
        self.tables = {
            "atoms": self.atom_table,
            "bonds": self.bond_table,
            "polyhedra": self.polyhedron_table,
            "units": self.unit_table,
            "interpretations": self.interpretation_table,
            "blocks": self.block_table,
            "connectors": self.connector_table,
            "topology": self.topology_table,
            "covalent_bonds": self.organic_table,
            "coordination_bonds": self.organic_table,
            "molecules": self.organic_table,
            "rings": self.organic_table,
            "contacts": self.organic_table,
            "packing": self.organic_table,
            "voids": self.organic_table,
            "coordination_nodes": self.organic_table,
            "linkers": self.organic_table,
            "sbus": self.organic_table,
            "organic_topology": self.organic_table,
        }
        for table in dict.fromkeys(self.tables.values()):
            self.stack.addWidget(table)
        layout.addWidget(self.stack)
        self.atom_table.itemChanged.connect(self._atom_changed)
        self.bond_table.itemChanged.connect(self._bond_changed)
        self.polyhedron_table.itemChanged.connect(self._polyhedron_changed)
        self.unit_table.itemChanged.connect(self._unit_changed)
        self.block_table.itemChanged.connect(self._block_changed)
        self.topology_table.itemChanged.connect(self._topology_changed)
        for table, callback in (
            (self.atom_table, self._atom_color_clicked),
            (self.polyhedron_table, self._polyhedron_color_clicked),
            (self.unit_table, self._unit_color_clicked),
            (self.block_table, self._block_color_clicked),
        ):
            table.cellDoubleClicked.connect(callback)
        self.set_category("atoms")

    @staticmethod
    def _table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    @staticmethod
    def _check_item(checked: bool) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    @staticmethod
    def _color_item(color: str, key: str) -> QTableWidgetItem:
        item = QTableWidgetItem("■")
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setForeground(QColor(color))
        item.setToolTip("Double-click to change color")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @staticmethod
    def _name_item(text: str, key: object) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, key)
        return item

    def set_category(self, category: str) -> None:
        table = self.tables.get(category)
        if table is not None:
            self._category = category
            if table is self.organic_table:
                self._fill_organic_table(category)
            self.stack.setCurrentWidget(table)
        self._update_topology_status_visibility()

    def current_table(self) -> QTableWidget:
        return self.stack.currentWidget()  # type: ignore[return-value]

    def select_object(self, kind: str, object_id: object) -> bool:
        """Show and select the symmetry-orbit row containing a scene object."""
        if self._document is None:
            return False
        category = {
            "atom": "atoms",
            "bond": "bonds",
            "polyhedron": "polyhedra",
            "unit": "units",
            "block": "blocks",
        }.get(str(kind))
        if category is None:
            return False
        table = self.tables[category]
        target = object_id
        if kind == "atom":
            try:
                target = site_orbit_key(
                    self._document.structure.sites[int(object_id)].label
                )
            except (IndexError, TypeError, ValueError):
                return False
        elif kind == "polyhedron":
            polyhedron = next(
                (
                    item
                    for item in self._document.hierarchy.polyhedra
                    if item.id == str(object_id)
                ),
                None,
            )
            if polyhedron is None:
                return False
            target = site_orbit_key(
                self._document.structure.sites[polyhedron.center_index].label
            )
        for row in range(table.rowCount()):
            key = self._key(table, row)
            matches = key == target
            if kind in {"unit", "block"} and isinstance(key, tuple):
                matches = str(object_id) in key
            if not matches:
                continue
            self.set_category(category)
            table.setCurrentCell(row, 0)
            table.selectRow(row)
            table.scrollToItem(table.item(row, 0))
            return True
        return False

    def set_document(self, document) -> None:
        self._document = document
        self._updating = True
        try:
            for table in self.tables.values():
                table.setRowCount(0)
            if document is None:
                return
            self._fill_atoms()
            self._fill_bonds()
            self._fill_polyhedra()
            self._fill_units()
            self._fill_blocks()
            self._fill_read_only_tables()
            if self._category in {
                "covalent_bonds", "coordination_bonds", "molecules", "rings", "contacts",
                "packing", "voids"
                , "coordination_nodes", "linkers", "sbus", "organic_topology"
            }:
                self._fill_organic_table(self._category)
            self._update_color_availability()
            self._update_topology_status_visibility()
        finally:
            self._updating = False

    def _fill_organic_table(self, category: str) -> None:
        table = self.organic_table
        table.setRowCount(0)
        report = getattr(self._document, "organic_analysis", None)
        if report is None:
            return

        rows: list[tuple[str, str, str, str]] = []
        if category in {"covalent_bonds", "coordination_bonds"}:
            edges = (
                report.bonds.covalent
                if category == "covalent_bonds"
                else report.bonds.coordination
            )
            for edge in edges:
                first = self._document.structure.sites[edge.first].label
                second = self._document.structure.sites[edge.second].label
                rows.append(
                    (
                        edge.id,
                        f"{first}—{second}",
                        f"{edge.distance:.3f} Å · image {edge.image}",
                        f"{edge.method} · confidence {edge.confidence:.2f}",
                    )
                )
        elif category == "molecules" and report.components is not None:
            for component in report.components.components:
                dimensionality = "finite" if component.periodic_rank == 0 else f"{component.periodic_rank}D"
                rows.append(
                    (
                        component.id,
                        component.formula or "molecule",
                        f"{len(component.atom_indices)} atoms · {dimensionality}",
                        f"confidence {component.confidence:.2f}",
                    )
                )
        elif category == "rings" and report.components is not None:
            for ring in report.components.rings:
                rows.append(
                    (
                        ring.id,
                        f"{len(ring.atom_indices)}-membered ring",
                        f"planarity RMS {ring.planarity_rms:.3f} Å",
                        f"{'pi-capable' if ring.pi_capable else 'non-pi'} · confidence {ring.confidence:.2f}",
                    )
                )
        elif category == "contacts" and report.contacts is not None:
            for contact in report.contacts.contacts:
                angle = "" if contact.angle is None else f" · {contact.angle:.1f}°"
                rows.append(
                    (
                        contact.id,
                        contact.kind.value,
                        f"{contact.first_component_id}—{contact.second_component_id}",
                        f"{contact.distance:.3f} Å{angle} · confidence {contact.confidence:.2f}",
                    )
                )
        elif category == "packing" and report.packing is not None:
            for assembly in report.packing.assemblies:
                rows.append(
                    (
                        assembly.id,
                        assembly.classification,
                        ", ".join(assembly.component_ids),
                        f"rank {assembly.periodic_rank} · {len(assembly.contact_ids)} interactions",
                    )
                )
        elif category == "voids" and report.packing is not None:
            for region in report.packing.voids:
                rows.append(
                    (
                        region.id,
                        region.classification,
                        f"volume fraction {100.0 * region.volume_fraction:.2f}%",
                        f"periodic rank {region.periodic_rank} · grid {report.packing.effective_grid_spacing:.3f} Å",
                    )
                )
        elif category == "coordination_nodes" and report.reticular is not None:
            for node in report.reticular.coordination_nodes:
                rows.append(
                    (
                        node.id,
                        "coordination node",
                        f"{len(node.atom_indices)} metal centre(s)",
                        f"{len(node.coordination_edge_ids)} coordination bonds · confidence {node.confidence:.2f}",
                    )
                )
        elif category == "linkers" and report.reticular is not None:
            for linker in report.reticular.linkers:
                rows.append(
                    (
                        linker.id,
                        "organic linker",
                        linker.component_id,
                        f"connectivity {len(linker.incident_node_ids)} · confidence {linker.confidence:.2f}",
                    )
                )
        elif category == "sbus" and report.reticular is not None:
            for sbu in report.reticular.sbus:
                rows.append(
                    (sbu.id, "SBU candidate", sbu.representation, ", ".join(sbu.coordination_node_ids))
                )
        elif category == "organic_topology" and report.reticular is not None:
            for edge in report.reticular.underlying_edges:
                rows.append(
                    (
                        edge.id,
                        "underlying edge",
                        f"{edge.first}—{edge.second}",
                        f"image {edge.image} · {edge.linker_id}",
                    )
                )
        for row, values in enumerate(rows):
            table.insertRow(row)
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))

    def _update_topology_status_visibility(self) -> None:
        report = getattr(self._document, "inorganic_topology", None)
        is_topology = self.stack.currentWidget() is self.topology_table
        unavailable = report is not None and not report.interpretable
        if unavailable:
            self.topology_status.setText(
                " ".join(report.warnings) or "Topology could not be evaluated."
            )
        else:
            self.topology_status.clear()
        self.topology_status.setVisible(is_topology and unavailable)

    def set_color_mode(self, mode: str) -> None:
        self._color_mode = str(mode).strip().lower().replace(" ", "_")
        self._update_color_availability()

    def set_comparison_locked(self, locked: bool) -> None:
        self._comparison_locked = bool(locked)
        self._update_color_availability()

    def _update_color_availability(self) -> None:
        editable = {
            "atoms": True,
            "polyhedra": self._color_mode in {"automatic", "element"},
            "units": True,
            "blocks": self._color_mode not in {"automatic", "rigidity"},
        }
        for category, table in (
            ("atoms", self.atom_table),
            ("polyhedra", self.polyhedron_table),
            ("units", self.unit_table),
            ("blocks", self.block_table),
        ):
            enabled = editable[category] and not self._comparison_locked
            for row in range(table.rowCount()):
                item = table.item(row, 1)
                if item is None:
                    continue
                flags = item.flags()
                item.setFlags(
                    flags | Qt.ItemFlag.ItemIsEnabled
                    if enabled
                    else flags & ~Qt.ItemFlag.ItemIsEnabled
                )
                item.setToolTip(
                    "Double-click to change color"
                    if enabled
                    else "Color is controlled by the active coloring mode"
                )

    def _fill_atoms(self) -> None:
        document = self._document
        orbits = site_orbits(document.structure)
        for row, site in enumerate(document.structure.asymmetric_sites):
            key = site_orbit_key(site.label)
            indices = orbits.get(key, ())
            self.atom_table.insertRow(row)
            self.atom_table.setItem(row, 0, self._name_item(site.label, key))
            color = document.visual.atom_orbit_colors.get(key, site_colour(site))
            self.atom_table.setItem(row, 1, self._color_item(color, key))
            visible = not any(index in document.visual.hidden_atom_indices for index in indices)
            self.atom_table.setItem(row, 2, self._check_item(visible))

    def _bond_families(self) -> list[tuple[str, str]]:
        return list(bond_families(self._document))

    def _fill_bonds(self) -> None:
        for row, pair in enumerate(self._bond_families()):
            self.bond_table.insertRow(row)
            self.bond_table.setItem(row, 0, self._name_item("—".join(pair), pair))
            gradient = QTableWidgetItem("■  →  ■")
            gradient.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bond_table.setItem(row, 1, gradient)
            visible = pair not in self._document.visual.hidden_bond_families
            self.bond_table.setItem(row, 2, self._check_item(visible))

    def _fill_polyhedra(self) -> None:
        document = self._document
        first_by_key = {}
        for polyhedron in document.hierarchy.polyhedra:
            key = site_orbit_key(document.structure.sites[polyhedron.center_index].label)
            first_by_key.setdefault(key, polyhedron)
        asym = {site_orbit_key(site.label): site for site in document.structure.asymmetric_sites}
        for row, (key, ids) in enumerate(polyhedron_orbits(document).items()):
            polyhedron = first_by_key[key]
            site = asym.get(key, document.structure.sites[polyhedron.center_index])
            coordination = str(polyhedron.coordination_number).translate(_SUBSCRIPT)
            formula = f"{site.label}{polyhedron.ligand_element}{coordination}"
            self.polyhedron_table.insertRow(row)
            self.polyhedron_table.setItem(row, 0, self._name_item(formula, key))
            color = document.visual.polyhedron_orbit_colors.get(key, site_colour(site))
            self.polyhedron_table.setItem(row, 1, self._color_item(color, key))
            visible = not any(identifier in document.visual.hidden_polyhedron_ids for identifier in ids)
            self.polyhedron_table.setItem(row, 2, self._check_item(visible))

    def _fill_units(self) -> None:
        units = {item.id: item for item in self._document.hierarchy.structural_units}
        for row, identifiers in enumerate(
            hierarchy_object_orbits(self._document, tuple(units.values()))
        ):
            unit = units[identifiers[0]]
            self.unit_table.insertRow(row)
            self.unit_table.setItem(
                row, 0, self._name_item(self._aggregate_name(unit), identifiers)
            )
            color = self._document.visual.unit_colors.get(
                identifiers[0], _UNIT_COLORS[row % len(_UNIT_COLORS)]
            )
            self.unit_table.setItem(row, 1, self._color_item(color, identifiers))
            self.unit_table.setItem(
                row,
                2,
                self._check_item(
                    all(
                        identifier in self._document.visual.shown_unit_ids
                        for identifier in identifiers
                    )
                ),
            )

    def _fill_blocks(self) -> None:
        blocks = {item.id: item for item in self._document.hierarchy.blocks}
        for row, identifiers in enumerate(
            hierarchy_object_orbits(self._document, tuple(blocks.values()))
        ):
            block = blocks[identifiers[0]]
            self.block_table.insertRow(row)
            self.block_table.setItem(
                row, 0, self._name_item(self._aggregate_name(block), identifiers)
            )
            color = self._document.visual.block_colors.get(
                identifiers[0], _BLOCK_COLORS[row % len(_BLOCK_COLORS)]
            )
            self.block_table.setItem(row, 1, self._color_item(color, identifiers))
            self.block_table.setItem(
                row,
                2,
                self._check_item(
                    all(
                        identifier in self._document.visual.shown_block_ids
                        for identifier in identifiers
                    )
                ),
            )

    def _aggregate_name(self, item) -> str:
        polyhedra = {
            polyhedron.id: polyhedron
            for polyhedron in self._document.hierarchy.polyhedra
        }
        labels = tuple(
            dict.fromkeys(
                site_orbit_key(
                    self._document.structure.sites[
                        polyhedra[identifier].center_index
                    ].label
                )
                for identifier in item.polyhedron_ids
                if identifier in polyhedra
            )
        )
        return (
            f"{item.classification} · {'/'.join(labels)}"
            if labels
            else item.classification
        )

    def _fill_read_only_tables(self) -> None:
        for row, domain in enumerate(self._document.hierarchy.structural_domains):
            self.interpretation_table.insertRow(row)
            self.interpretation_table.setItem(row, 0, QTableWidgetItem(domain.id))
            self.interpretation_table.setItem(row, 1, QTableWidgetItem(domain.classification))
        connectors = {
            connector.id: connector for connector in self._document.hierarchy.connectors
        }
        for row, identifiers in enumerate(connector_orbits(self._document)):
            connector = connectors[identifiers[0]]
            labels = tuple(
                dict.fromkeys(
                    site_orbit_key(self._document.structure.sites[index].label)
                    for index in connector.ligand_indices
                )
            )
            self.connector_table.insertRow(row)
            self.connector_table.setItem(
                row,
                0,
                QTableWidgetItem("/".join(labels) if labels else connector.id),
            )
            self.connector_table.setItem(row, 1, QTableWidgetItem(connector.kind))
        report = self._document.inorganic_topology
        if report is None:
            return
        families = (*report.families, *report.cation_families)
        for row, family in enumerate(families):
            self.topology_table.insertRow(row)
            name = "/".join(family.building_units) or family.id
            if family.representation == "cation":
                name += " · cation network"
            self.topology_table.setItem(row, 0, self._name_item(name, family.id))
            self.topology_table.setItem(row, 1, QTableWidgetItem(family.classification))
            self.topology_table.setItem(
                row, 2, QTableWidgetItem(self._topology_orientation(family))
            )
            connections = " · ".join(
                f"{kind}: {count}" for kind, count in family.connection_counts
            )
            if family.distance_range is not None:
                minimum, maximum = family.distance_range
                distance = (
                    f"d: {minimum:.2f} Å"
                    if abs(maximum - minimum) < 0.005
                    else f"d: {minimum:.2f}–{maximum:.2f} Å"
                )
                connections = " · ".join(filter(None, (connections, distance)))
            self.topology_table.setItem(row, 3, QTableWidgetItem(connections or "—"))
            self.topology_table.setItem(
                row,
                4,
                self._check_item(
                    family.id not in self._document.visual.hidden_topology_family_ids
                ),
            )

    @staticmethod
    def _topology_orientation(family) -> str:
        if family.periodic_rank == 0:
            return "finite"
        if family.periodic_rank == 3:
            return "3D"
        if family.periodic_rank == 2 and family.plane_normal is not None:
            return "(" + " ".join(str(value) for value in family.plane_normal) + ")"
        if family.directions:
            return " · ".join(
                "[" + " ".join(str(value) for value in direction) + "]"
                for direction in family.directions
            )
        return "—"

    @staticmethod
    def _key(table: QTableWidget, row: int):
        return table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _atom_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or self._document is None or item.column() != 2:
            return
        key = self._key(self.atom_table, item.row())
        visible = item.checkState() == Qt.CheckState.Checked
        hidden = self._document.visual.hidden_atom_indices
        for index in site_orbits(self._document.structure).get(key, ()):
            hidden.discard(index) if visible else hidden.add(index)
        self.state_changed.emit()

    def _bond_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or self._document is None or item.column() != 2:
            return
        pair = self._key(self.bond_table, item.row())
        hidden = self._document.visual.hidden_bond_families
        hidden.discard(pair) if item.checkState() == Qt.CheckState.Checked else hidden.add(pair)
        self.state_changed.emit()

    def _polyhedron_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or self._document is None or item.column() != 2:
            return
        key = self._key(self.polyhedron_table, item.row())
        visible = item.checkState() == Qt.CheckState.Checked
        hidden = self._document.visual.hidden_polyhedron_ids
        for identifier in polyhedron_orbits(self._document).get(key, ()):
            hidden.discard(identifier) if visible else hidden.add(identifier)
        self.state_changed.emit()

    def _unit_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or self._document is None or item.column() != 2:
            return
        identifiers = self._key(self.unit_table, item.row())
        shown = self._document.visual.shown_unit_ids
        for identifier in identifiers:
            shown.add(identifier) if item.checkState() == Qt.CheckState.Checked else shown.discard(identifier)
        self.state_changed.emit()

    def _block_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or self._document is None or item.column() != 2:
            return
        identifiers = self._key(self.block_table, item.row())
        shown = self._document.visual.shown_block_ids
        for identifier in identifiers:
            shown.add(identifier) if item.checkState() == Qt.CheckState.Checked else shown.discard(identifier)
        self.state_changed.emit()

    def _topology_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or self._document is None or item.column() != 4:
            return
        identifier = self._key(self.topology_table, item.row())
        hidden = self._document.visual.hidden_topology_family_ids
        if item.checkState() == Qt.CheckState.Checked:
            hidden.discard(identifier)
        else:
            hidden.add(identifier)
        self.state_changed.emit()

    def set_atom_color(self, key: str, color: str) -> None:
        self._set_color("atom_orbit_colors", key, color)

    def set_polyhedron_color(self, key: str, color: str) -> None:
        self._set_color("polyhedron_orbit_colors", key, color)

    def set_unit_color(self, identifiers: tuple[str, ...], color: str) -> None:
        self._set_color("unit_colors", identifiers, color)

    def set_block_color(self, identifiers: tuple[str, ...], color: str) -> None:
        self._set_color("block_colors", identifiers, color)

    def _set_color(self, attribute: str, key, color: str) -> None:
        if self._document is None:
            return
        identifiers = key if isinstance(key, tuple) else (key,)
        for identifier in identifiers:
            getattr(self._document.visual, attribute)[identifier] = QColor(color).name()
        self.set_document(self._document)
        self.state_changed.emit()

    def _choose_color(self, table: QTableWidget, row: int, column: int, attribute: str) -> None:
        if column != 1 or self._document is None:
            return
        if not table.item(row, column).flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        key = self._key(table, row)
        color = QColorDialog.getColor(table.item(row, 1).foreground().color(), self, "Object color")
        if color.isValid():
            self._set_color(attribute, key, color.name())

    def _atom_color_clicked(self, row: int, column: int) -> None:
        self._choose_color(self.atom_table, row, column, "atom_orbit_colors")

    def _polyhedron_color_clicked(self, row: int, column: int) -> None:
        self._choose_color(self.polyhedron_table, row, column, "polyhedron_orbit_colors")

    def _unit_color_clicked(self, row: int, column: int) -> None:
        self._choose_color(self.unit_table, row, column, "unit_colors")

    def _block_color_clicked(self, row: int, column: int) -> None:
        self._choose_color(self.block_table, row, column, "block_colors")
