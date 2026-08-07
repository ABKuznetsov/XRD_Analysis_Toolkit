from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from xrd_finder.core.project import Project


class ProjectTree(QTreeWidget):
    object_open_requested = Signal(str, str)
    object_rename_requested = Signal(str, str)
    object_delete_requested = Signal(str, str)
    series_create_requested = Signal()
    object_move_to_series_requested = Signal(str, str, str)
    pattern_selection_changed = Signal(list)
    phase_selection_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabel("Data")
        self.setToolTip(
            "Project tree\n"
            "Select a row to make that XRD pattern or CIF phase active.\n"
            "Use checkboxes to show or hide patterns, phases, or an entire series on the plot.\n"
            "Create series from the project menu and move XRD/CIF items between series from their context menu.\n"
            "Double click an XRD row to show only that pattern.\n"
            "Double click a CIF row to show only that phase marker lane."
        )
        self.setMinimumWidth(150)
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
        self._series_items: dict[str, QTreeWidgetItem] = {}
        self._series_names: list[tuple[str, str]] = []
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemChanged.connect(self._on_item_changed)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        current = self.currentItem()
        data = current.data(0, 256) if current is not None else None
        if data:
            object_type, object_id = data
            if event.key() == Qt.Key.Key_F2 and object_type in {"project", "series", "pattern", "phase"}:
                self.object_rename_requested.emit(object_type, object_id)
                return
            if event.key() == Qt.Key.Key_Delete and object_type in {"series", "pattern", "phase"}:
                self.object_delete_requested.emit(object_type, object_id)
                return
        super().keyPressEvent(event)

    def _show_context_menu(self, position: QPoint) -> None:
        item = self.itemAt(position)
        if item is None:
            return
        data = item.data(0, 256)
        if not data:
            return
        object_type, object_id = data
        if object_type not in {"project", "series", "pattern", "phase"}:
            return
        menu = QMenu(self)
        create_series_action = menu.addAction("Add series") if object_type == "project" else None
        open_action = None
        if object_type in {"pattern", "phase"}:
            open_action = menu.addAction("Open")
        rename_action = menu.addAction("Rename")
        move_actions: list[tuple[object, str]] = []
        if object_type in {"pattern", "phase"}:
            move_menu = menu.addMenu("Move to series")
            move_actions.append((move_menu.addAction("No series"), ""))
            if self._series_names:
                move_menu.addSeparator()
                for series_id, series_name in self._series_names:
                    move_actions.append((move_menu.addAction(series_name), series_id))
        delete_action = None
        if object_type in {"series", "pattern", "phase"}:
            delete_action = menu.addAction("Delete series" if object_type == "series" else "Delete")
        action = menu.exec(self.viewport().mapToGlobal(position))
        if action is None:
            return
        if create_series_action is not None and action == create_series_action:
            self.series_create_requested.emit()
            return
        if open_action is not None and action == open_action:
            self.object_open_requested.emit(object_type, object_id)
            return
        for move_action, series_id in move_actions:
            if action == move_action:
                self.object_move_to_series_requested.emit(object_type, object_id, series_id)
                return
        if action == rename_action:
            self.object_rename_requested.emit(object_type, object_id)
            return
        if delete_action is not None and action == delete_action:
            self.object_delete_requested.emit(object_type, object_id)
    def set_project(self, project: Project) -> None:
        expansion_state = self._capture_expansion_state()
        self._updating = True
        self.clear()
        self._pattern_items = {}
        self._pattern_names = {}
        self._phase_items = {}
        self._phase_names = {}
        self._series_items = {}
        self._series_names = [(series.id, series.name) for series in project.series]
        available_pattern_ids = {pattern.id for pattern in project.patterns}
        self._pattern_order = [pattern.id for pattern in project.patterns]
        new_pattern_ids = available_pattern_ids - self._known_pattern_ids
        self._checked_pattern_ids &= available_pattern_ids
        self._checked_pattern_ids |= new_pattern_ids
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

        if project.series:
            assigned_patterns = set()
            assigned_phases = set()
            for series in project.series:
                series_item = QTreeWidgetItem([series.name])
                series_item.setData(0, 256, ("series", series.id))
                series_item.setFlags(series_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                series_item.setToolTip(
                    0,
                    "Project series\n"
                    "Checkbox: show or hide every XRD pattern and CIF phase in this series.\n"
                    "A partially checked box means that only part of the series is visible.",
                )
                self._series_items[series.id] = series_item
                root.addChild(series_item)
                pattern_ids = set(series.pattern_ids)
                phase_ids = set(series.phase_ids)
                for pattern in project.patterns:
                    if pattern.id in pattern_ids:
                        self._add_project_object_item(series_item, "pattern", pattern)
                        assigned_patterns.add(pattern.id)
                for phase in project.phases:
                    if phase.id in phase_ids:
                        self._add_project_object_item(series_item, "phase", phase)
                        assigned_phases.add(phase.id)
            unassigned_patterns = [pattern for pattern in project.patterns if pattern.id not in assigned_patterns]
            unassigned_phases = [phase for phase in project.phases if phase.id not in assigned_phases]
            if unassigned_patterns or unassigned_phases:
                group = QTreeWidgetItem(["No series"])
                group.setData(0, 256, ("group", "unassigned"))
                root.addChild(group)
                for pattern in unassigned_patterns:
                    self._add_project_object_item(group, "pattern", pattern)
                for phase in unassigned_phases:
                    self._add_project_object_item(group, "phase", phase)
        else:
            groups = [
                ("XRD", "pattern", project.patterns),
                ("Structures", "phase", project.phases),
            ]
            for group_name, object_type, objects in groups:
                group = QTreeWidgetItem([group_name])
                group.setData(0, 256, ("group", group_name))
                root.addChild(group)
                for project_object in objects:
                    self._add_project_object_item(group, object_type, project_object)

        self._restore_expansion_state(root, expansion_state)
        self._refresh_pattern_numbers()
        self._refresh_phase_numbers()
        self._refresh_series_check_states()
        self._updating = False
        self.pattern_selection_changed.emit(self.checked_pattern_ids())
        self.phase_selection_changed.emit(self.checked_phase_ids())

    def _capture_expansion_state(self) -> dict[tuple[str, str], bool]:
        state: dict[tuple[str, str], bool] = {}

        def visit(item: QTreeWidgetItem) -> None:
            data = item.data(0, 256)
            if data and len(data) == 2:
                state[(str(data[0]), str(data[1]))] = bool(item.isExpanded())
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self.topLevelItemCount()):
            visit(self.topLevelItem(index))
        return state

    def expansion_state(self) -> dict[str, bool]:
        return {
            f"{object_type}:{object_id}": expanded
            for (object_type, object_id), expanded in self._capture_expansion_state().items()
            if object_type in {"project", "series", "group"}
        }

    def restore_expansion_state(self, state: dict[str, bool] | None) -> None:
        parsed: dict[tuple[str, str], bool] = {}
        if isinstance(state, dict):
            for raw_key, expanded in state.items():
                object_type, separator, object_id = str(raw_key).partition(":")
                if separator and object_type in {"project", "series", "group"} and object_id:
                    parsed[(object_type, object_id)] = bool(expanded)
        root = self.topLevelItem(0)
        if root is not None:
            self._restore_expansion_state(root, parsed)

    def _restore_expansion_state(
        self,
        root: QTreeWidgetItem,
        state: dict[tuple[str, str], bool],
    ) -> None:
        def visit(item: QTreeWidgetItem) -> None:
            data = item.data(0, 256)
            if data and len(data) == 2:
                key = (str(data[0]), str(data[1]))
                default_expanded = str(data[0]) in {"project", "group"}
                item.setExpanded(state.get(key, default_expanded))
            for index in range(item.childCount()):
                visit(item.child(index))

        visit(root)

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
        if object_type in {"series", "pattern", "phase"}:
            return object_type, object_id
        return None

    def current_series_id(self) -> str | None:
        item = self.currentItem()
        while item is not None:
            data = item.data(0, 256)
            if data and data[0] == "series":
                return data[1]
            item = item.parent()
        return None

    def select_object(self, object_type: str, object_id: str) -> None:
        if object_type == "pattern":
            item = self._pattern_items.get(object_id)
        elif object_type == "phase":
            item = self._phase_items.get(object_id)
        elif object_type == "series":
            item = self._series_items.get(object_id)
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
        self._refresh_series_check_states()
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
        self._refresh_series_check_states()
        self._updating = False
        self.phase_selection_changed.emit(self.checked_phase_ids())

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, 256)
        if not data:
            return
        object_type, object_id = data
        if object_type in {"pattern", "phase"}:
            self.object_open_requested.emit(object_type, object_id)

    def _add_project_object_item(self, parent: QTreeWidgetItem, object_type: str, project_object) -> None:
        child = QTreeWidgetItem([project_object.name])
        child.setData(0, 256, (object_type, project_object.id))
        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
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
            checked = project_object.id in self._checked_pattern_ids
        else:
            self._phase_items[project_object.id] = child
            self._phase_names[project_object.id] = project_object.name
            child.setToolTip(
                0,
                "CIF structure\n"
                "Select: make this phase active.\n"
                "Checkbox: show or hide its marker lane.\n"
                "Double click: show only this phase marker lane.",
            )
            checked = project_object.id in self._checked_phase_ids
        child.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        parent.addChild(child)

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._updating:
            return
        data = item.data(0, 256)
        if not data:
            return
        object_type, object_id = data
        if object_type == "series":
            target_checked = item.checkState(0) == Qt.CheckState.Checked
            previous_patterns = set(self._checked_pattern_ids)
            previous_phases = set(self._checked_phase_ids)
            self._updating = True
            for index in range(item.childCount()):
                child = item.child(index)
                child_data = child.data(0, 256)
                if not child_data:
                    continue
                child_type, child_id = child_data
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked if target_checked else Qt.CheckState.Unchecked,
                )
                if child_type == "pattern":
                    if target_checked:
                        self._checked_pattern_ids.add(child_id)
                    else:
                        self._checked_pattern_ids.discard(child_id)
                elif child_type == "phase":
                    if target_checked:
                        self._checked_phase_ids.add(child_id)
                    else:
                        self._checked_phase_ids.discard(child_id)
            self._refresh_pattern_numbers()
            self._refresh_phase_numbers()
            self._refresh_series_check_states()
            self._updating = False
            if self._checked_pattern_ids != previous_patterns:
                self.pattern_selection_changed.emit(self.checked_pattern_ids())
            if self._checked_phase_ids != previous_phases:
                self.phase_selection_changed.emit(self.checked_phase_ids())
            return
        if object_type == "pattern":
            if item.checkState(0) == Qt.CheckState.Checked:
                self._checked_pattern_ids.add(object_id)
            else:
                self._checked_pattern_ids.discard(object_id)
            self._updating = True
            self._refresh_pattern_numbers()
            self._refresh_phase_numbers()
            self._refresh_series_check_states()
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
            self._refresh_series_check_states()
            self._updating = False
            self.phase_selection_changed.emit(self.checked_phase_ids())

    def _refresh_series_check_states(self) -> None:
        for series_item in self._series_items.values():
            child_states = [
                series_item.child(index).checkState(0)
                for index in range(series_item.childCount())
                if series_item.child(index).data(0, 256)
                and series_item.child(index).data(0, 256)[0] in {"pattern", "phase"}
            ]
            if child_states and all(state == Qt.CheckState.Checked for state in child_states):
                state = Qt.CheckState.Checked
            elif child_states and any(state != Qt.CheckState.Unchecked for state in child_states):
                state = Qt.CheckState.PartiallyChecked
            else:
                state = Qt.CheckState.Unchecked
            series_item.setCheckState(0, state)

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
