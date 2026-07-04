from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from xrd_finder.core.project import Project


class ProjectTree(QTreeWidget):
    object_open_requested = Signal(str, str)
    pattern_selection_changed = Signal(list)
    phase_selection_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabel("Data")
        self.setToolTip(
            "Project tree\n"
            "Select a row to make that XRD pattern or CIF phase active.\n"
            "Use checkboxes to show or hide patterns/phases on the plot.\n"
            "Double click an XRD row to show only that pattern.\n"
            "Double click a CIF row to show only that phase marker lane."
        )
        self.setMinimumWidth(240)
        self._updating = False
        self._checked_pattern_ids: set[str] = set()
        self._known_pattern_ids: set[str] = set()
        self._pattern_order: list[str] = []
        self._pattern_items: dict[str, QTreeWidgetItem] = {}
        self._pattern_names: dict[str, str] = {}
        self._checked_phase_ids: set[str] = set()
        self._known_phase_ids: set[str] = set()
        self._phase_order: list[str] = []
        self._phase_items: dict[str, QTreeWidgetItem] = {}
        self._phase_names: dict[str, str] = {}
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemChanged.connect(self._on_item_changed)

    def set_project(self, project: Project) -> None:
        self._updating = True
        self.clear()
        self._pattern_items = {}
        self._pattern_names = {}
        self._phase_items = {}
        self._phase_names = {}
        available_pattern_ids = {pattern.id for pattern in project.patterns}
        self._pattern_order = [pattern.id for pattern in project.patterns]
        new_pattern_ids = available_pattern_ids - self._known_pattern_ids
        self._checked_pattern_ids &= available_pattern_ids
        self._checked_pattern_ids |= new_pattern_ids
        if project.patterns and not self._checked_pattern_ids:
            self._checked_pattern_ids = set(available_pattern_ids)
        self._known_pattern_ids = set(available_pattern_ids)
        available_phase_ids = {phase.id for phase in project.phases}
        self._phase_order = [phase.id for phase in project.phases]
        new_phase_ids = available_phase_ids - self._known_phase_ids
        self._checked_phase_ids &= available_phase_ids
        self._checked_phase_ids |= new_phase_ids
        self._known_phase_ids = set(available_phase_ids)

        root = QTreeWidgetItem([project.name])
        root.setData(0, 256, ("project", project.id))
        self.addTopLevelItem(root)

        groups = [
            ("XRD", "pattern", project.patterns),
            ("Structures", "phase", project.phases),
        ]

        for group_name, object_type, objects in groups:
            group = QTreeWidgetItem([group_name])
            group.setData(0, 256, ("group", group_name))
            root.addChild(group)
            for project_object in objects:
                child = QTreeWidgetItem([project_object.name])
                child.setData(0, 256, (object_type, project_object.id))
                if object_type == "pattern":
                    self._pattern_items[project_object.id] = child
                    self._pattern_names[project_object.id] = project_object.name
                    child.setToolTip(
                        0,
                        "XRD pattern\n"
                        "Select: make this pattern active for search and preview.\n"
                        "Checkbox: show or hide it on the plot.\n"
                        "Double click: show only this pattern.",
                    )
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    state = (
                        Qt.CheckState.Checked
                        if project_object.id in self._checked_pattern_ids
                        else Qt.CheckState.Unchecked
                    )
                    child.setCheckState(0, state)
                elif object_type == "phase":
                    self._phase_items[project_object.id] = child
                    self._phase_names[project_object.id] = project_object.name
                    child.setToolTip(
                        0,
                        "CIF structure\n"
                        "Select: make this phase active.\n"
                        "Checkbox: show or hide its marker lane.\n"
                        "Double click: show only this phase marker lane.",
                    )
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    state = (
                        Qt.CheckState.Checked
                        if project_object.id in self._checked_phase_ids
                        else Qt.CheckState.Unchecked
                    )
                    child.setCheckState(0, state)
                group.addChild(child)

        root.setExpanded(True)
        self._refresh_pattern_numbers()
        self._refresh_phase_numbers()
        self._updating = False
        self.pattern_selection_changed.emit(self.checked_pattern_ids())
        self.phase_selection_changed.emit(self.checked_phase_ids())

    def checked_pattern_ids(self) -> list[str]:
        return [pattern_id for pattern_id in self._pattern_order if pattern_id in self._checked_pattern_ids]

    def current_pattern_id(self) -> str | None:
        current = self.current_object()
        if current is None:
            return None
        object_type, object_id = current
        return object_id if object_type == "pattern" else None

    def current_object(self) -> tuple[str, str] | None:
        item = self.currentItem()
        if item is None:
            return None
        data = item.data(0, 256)
        if not data:
            return None
        object_type, object_id = data
        if object_type in {"pattern", "phase"}:
            return object_type, object_id
        return None

    def select_object(self, object_type: str, object_id: str) -> None:
        if object_type == "pattern":
            item = self._pattern_items.get(object_id)
        elif object_type == "phase":
            item = self._phase_items.get(object_id)
        else:
            item = None
        if item is None:
            return
        self.setCurrentItem(item)
        self.scrollToItem(item)

    def checked_phase_ids(self) -> list[str]:
        return [phase_id for phase_id in self._phase_order if phase_id in self._checked_phase_ids]

    def set_checked_pattern_ids(self, pattern_ids: list[str]) -> None:
        checked = set(pattern_ids) & self._known_pattern_ids
        if checked == self._checked_pattern_ids:
            return
        self._checked_pattern_ids = checked
        self._updating = True
        for pattern_id, item in self._pattern_items.items():
            state = Qt.CheckState.Checked if pattern_id in checked else Qt.CheckState.Unchecked
            item.setCheckState(0, state)
        self._refresh_pattern_numbers()
        self._refresh_phase_numbers()
        self._updating = False
        self.pattern_selection_changed.emit(self.checked_pattern_ids())

    def set_checked_phase_ids(self, phase_ids: list[str]) -> None:
        checked = set(phase_ids) & self._known_phase_ids
        if checked == self._checked_phase_ids:
            return
        self._checked_phase_ids = checked
        self._updating = True
        for phase_id, item in self._phase_items.items():
            state = Qt.CheckState.Checked if phase_id in checked else Qt.CheckState.Unchecked
            item.setCheckState(0, state)
        self._refresh_pattern_numbers()
        self._refresh_phase_numbers()
        self._updating = False
        self.phase_selection_changed.emit(self.checked_phase_ids())

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, 256)
        if not data:
            return
        object_type, object_id = data
        if object_type not in {"project", "group"}:
            self.object_open_requested.emit(object_type, object_id)

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._updating:
            return
        data = item.data(0, 256)
        if not data:
            return
        object_type, object_id = data
        if object_type == "pattern":
            if item.checkState(0) == Qt.CheckState.Checked:
                self._checked_pattern_ids.add(object_id)
            else:
                self._checked_pattern_ids.discard(object_id)
            self._updating = True
            self._refresh_pattern_numbers()
            self._refresh_phase_numbers()
            self._updating = False
            self.pattern_selection_changed.emit(self.checked_pattern_ids())
            return
        if object_type == "phase":
            if item.checkState(0) == Qt.CheckState.Checked:
                self._checked_phase_ids.add(object_id)
            else:
                self._checked_phase_ids.discard(object_id)
            self._updating = True
            self._refresh_pattern_numbers()
            self._refresh_phase_numbers()
            self._updating = False
            self.phase_selection_changed.emit(self.checked_phase_ids())

    def _refresh_pattern_numbers(self) -> None:
        selected_numbers = self._selected_layer_numbers()
        for pattern_id in self._pattern_order:
            item = self._pattern_items.get(pattern_id)
            if item is None:
                continue
            name = self._pattern_names.get(pattern_id, item.text(0))
            number = selected_numbers["patterns"].get(pattern_id)
            item.setText(0, f"{number:02d}  {name}" if number is not None else f"--  {name}")

    def _refresh_phase_numbers(self) -> None:
        selected_numbers = self._selected_layer_numbers()
        for phase_id in self._phase_order:
            item = self._phase_items.get(phase_id)
            if item is None:
                continue
            name = self._phase_names.get(phase_id, item.text(0))
            number = selected_numbers["phases"].get(phase_id)
            item.setText(0, f"{number:02d}  {name}" if number is not None else f"--  {name}")

    def _selected_layer_numbers(self) -> dict[str, dict[str, int]]:
        number = 1
        pattern_numbers = {}
        for pattern_id in self.checked_pattern_ids():
            pattern_numbers[pattern_id] = number
            number += 1
        phase_numbers = {}
        for phase_id in self.checked_phase_ids():
            phase_numbers[phase_id] = number
            number += 1
        return {"patterns": pattern_numbers, "phases": phase_numbers}
