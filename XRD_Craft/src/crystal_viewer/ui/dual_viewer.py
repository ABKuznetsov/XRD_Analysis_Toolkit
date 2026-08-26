from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from crystal_viewer.analysis.hierarchy import HierarchyLevel
from crystal_viewer.analysis.descriptors.model import FocusCommand
from crystal_viewer.analysis.motif_comparison import MotifComparisonReport
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.ui.comparison_highlight import highlight_pair
from crystal_viewer.ui.viewer import CameraState, StructureViewer


def rotation_only_camera_state(source: CameraState, target: CameraState) -> CameraState:
    """Apply the source orientation while preserving the target framing."""
    direction = np.asarray(source.position) - np.asarray(source.focal_offset)
    distance = np.linalg.norm(np.asarray(target.position) - np.asarray(target.focal_offset))
    if np.linalg.norm(direction) < 1e-12:
        return target
    position = np.asarray(target.focal_offset) + direction / np.linalg.norm(direction) * distance
    return CameraState(
        tuple(position),
        target.focal_offset,
        source.view_up,
        target.parallel_scale,
        target.view_angle,
        source.parallel_projection,
    )


class DualStructureViewer(QWidget):
    """Two structure viewers with guarded, relative camera synchronization."""

    table_requested = Signal()
    pair_swapped = Signal(str, str)
    cif_files_dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._copying_camera = False
        self._camera_sync = True
        self.first_document: StructureDocument | None = None
        self.second_document: StructureDocument | None = None
        self._motif_report: MotifComparisonReport | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.sync_check = QCheckBox("Linked rotation")
        self.sync_check.setChecked(True)
        self.sync_check.toggled.connect(self.set_camera_sync)
        controls.addWidget(self.sync_check)
        controls.addWidget(QLabel("Control:"))
        self.control_combo = QComboBox()
        self.control_combo.addItems(("Both", "A", "B"))
        self.control_combo.currentTextChanged.connect(self._control_changed)
        controls.addWidget(self.control_combo)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_cameras)
        controls.addWidget(self.reset_button)
        self.swap_button = QPushButton("Swap A/B")
        self.swap_button.clicked.connect(self.swap_documents)
        controls.addWidget(self.swap_button)
        self.table_button = QPushButton("Comparison table")
        self.table_button.clicked.connect(self.table_requested)
        controls.addWidget(self.table_button)
        self.status_label = QLabel()
        self.status_label.setObjectName("comparisonStatus")
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        controls.addWidget(self.status_label)
        controls.addStretch(1)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_label = QLabel("A")
        self.right_label = QLabel("B")
        self.left = StructureViewer()
        self.right = StructureViewer()
        for viewer in (self.left, self.right):
            dropped = getattr(viewer, "cif_files_dropped", None)
            if dropped is not None:
                dropped.connect(self.cif_files_dropped)
        self.active_viewer: StructureViewer | None = None
        splitter.addWidget(self._pane(self.left_label, self.left))
        splitter.addWidget(self._pane(self.right_label, self.right))
        splitter.setSizes((1, 1))
        root.addWidget(splitter, 1)
        self.splitter = splitter
        self._install_hover_activation(self.left)
        self._install_hover_activation(self.right)
        self._set_active_viewer(self.left)
        self._attach_camera_observer(self.left, self.right)
        self._attach_camera_observer(self.right, self.left)

    @staticmethod
    def _pane(label: QLabel, viewer: StructureViewer) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("comparisonPaneTitle")
        layout.addWidget(label)
        layout.addWidget(viewer, 1)
        return pane

    def _attach_camera_observer(
        self,
        source: StructureViewer,
        target: StructureViewer,
    ) -> None:
        plotter = getattr(source, "plotter", None)
        interactor = getattr(plotter, "iren", None)
        add_observer = getattr(interactor, "add_observer", None)
        if add_observer is not None:
            add_observer(
                "EndInteractionEvent",
                lambda *_args: self._camera_interacted(source, target),
            )

    def _install_hover_activation(self, viewer: StructureViewer) -> None:
        viewer.installEventFilter(self)
        viewer.setMouseTracking(True)
        plotter = getattr(viewer, "plotter", None)
        if plotter is not None:
            plotter.installEventFilter(self)
            plotter.setMouseTracking(True)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Enter:
            if watched is self.left or watched is getattr(self.left, "plotter", None):
                self._set_active_viewer(self.left)
            elif watched is self.right or watched is getattr(self.right, "plotter", None):
                self._set_active_viewer(self.right)
        return super().eventFilter(watched, event)

    def _set_active_viewer(self, viewer: StructureViewer) -> None:
        if self.active_viewer is viewer:
            return
        self.active_viewer = viewer
        for candidate in (self.left, self.right):
            active = candidate is viewer
            candidate.setProperty("comparisonActive", active)
            candidate.setStyleSheet(
                "border: 2px solid #2f80ed;" if active else "border: 2px solid transparent;"
            )

    def set_pair(
        self,
        first: StructureDocument,
        second: StructureDocument,
    ) -> None:
        self._motif_report = None
        self.left.comparison_highlight = None
        self.right.comparison_highlight = None
        self.first_document = first
        self.second_document = second
        self.left.set_document(first, reset_camera=True)
        self.right.set_document(second, reset_camera=True)
        self._copy_camera(self.left, self.right)
        self.left_label.setText(self._label("A", first))
        self.right_label.setText(self._label("B", second))

    def set_motif_report(self, report: MotifComparisonReport) -> None:
        """Install one directional report on the matching left/right documents."""
        if self.first_document is None or self.second_document is None:
            raise ValueError("Motif report requires an active pair")
        pair_ids = (self.first_document.id, self.second_document.id)
        report_ids = (report.first_document_id, report.second_document_id)
        first_highlight, second_highlight = highlight_pair(report)
        if report_ids == pair_ids:
            left_highlight, right_highlight = first_highlight, second_highlight
        elif report_ids == pair_ids[::-1]:
            left_highlight, right_highlight = second_highlight, first_highlight
        else:
            raise ValueError("Motif report does not describe the active pair")

        self._motif_report = report
        self.left.level = HierarchyLevel.STRUCTURAL_UNITS
        self.right.level = HierarchyLevel.STRUCTURAL_UNITS
        self._copy_camera(self.left, self.right)
        self.left.set_comparison_highlight(left_highlight)
        self.right.set_comparison_highlight(right_highlight)

    def set_comparison_status(self, text: str) -> None:
        self.status_label.setText(text)

    @staticmethod
    def _label(slot: str, document: StructureDocument) -> str:
        structure = document.structure
        space_group = structure.space_group or "space group unknown"
        return f"{slot}  ·  {structure.display_formula}  ·  {space_group}"

    def set_level(self, level: HierarchyLevel) -> None:
        self.left.set_level(level)
        self.right.set_level(level)

    def set_show_labels(self, site_labels: bool, connector_labels: bool) -> None:
        for viewer in (self.left, self.right):
            viewer.show_labels = site_labels
            viewer.show_connector_labels = connector_labels
            viewer.redraw(reset_camera=False)

    def set_camera_sync(self, enabled: bool) -> None:
        self._camera_sync = bool(enabled)
        if self.sync_check.isChecked() != self._camera_sync:
            self.sync_check.blockSignals(True)
            self.sync_check.setChecked(self._camera_sync)
            self.sync_check.blockSignals(False)

    def _control_changed(self, value: str) -> None:
        self.set_camera_sync(value == "Both")
        if value == "A":
            self._set_active_viewer(self.left)
        elif value == "B":
            self._set_active_viewer(self.right)

    def _camera_interacted(
        self,
        source: StructureViewer,
        target: StructureViewer,
    ) -> None:
        if self._camera_sync:
            self._copy_camera(source, target)

    @contextmanager
    def _camera_copy_guard(self):
        if self._copying_camera:
            yield False
            return
        self._copying_camera = True
        try:
            yield True
        finally:
            self._copying_camera = False

    def _copy_camera(
        self,
        source: StructureViewer,
        target: StructureViewer,
    ) -> None:
        with self._camera_copy_guard() as allowed:
            if allowed:
                target.apply_camera_state(
                    rotation_only_camera_state(source.camera_state(), target.camera_state())
                )

    def reset_cameras(self) -> None:
        viewers = (self.left, self.right) if self._camera_sync else (self.active_viewer or self.left,)
        for viewer in viewers:
            plotter = getattr(viewer, "plotter", None)
            if plotter is not None:
                plotter.reset_camera()
        if self._camera_sync:
            self._copy_camera(self.left, self.right)

    def swap_documents(self) -> None:
        if self.first_document is None or self.second_document is None:
            return
        report = self._motif_report
        self.set_pair(self.second_document, self.first_document)
        self.pair_swapped.emit(self.first_document.id, self.second_document.id)
        if self._motif_report is None and report is not None:
            self.set_motif_report(report)

    def focus(self, command: FocusCommand) -> None:
        if command.action != "isolate":
            return
        side_keys = (
            "first_polyhedron_ids",
            "second_polyhedron_ids",
            "first_atom_indices",
            "second_atom_indices",
        )
        if all(key in command.payload for key in side_keys):
            left_prefix, right_prefix = "first", "second"
            if self._motif_report is not None:
                pair_ids = (
                    self.first_document.id if self.first_document is not None else "",
                    self.second_document.id if self.second_document is not None else "",
                )
                report_ids = (
                    self._motif_report.first_document_id,
                    self._motif_report.second_document_id,
                )
                if pair_ids == report_ids[::-1]:
                    left_prefix, right_prefix = "second", "first"
            self._focus_exact_side(
                self.left,
                self.first_document,
                command.level,
                command.payload[f"{left_prefix}_polyhedron_ids"],
                command.payload[f"{left_prefix}_atom_indices"],
            )
            self._focus_exact_side(
                self.right,
                self.second_document,
                command.level,
                command.payload[f"{right_prefix}_polyhedron_ids"],
                command.payload[f"{right_prefix}_atom_indices"],
            )
            return
        self.set_level(command.level)
        if command.selector != "polyhedron-type":
            return
        center = command.payload.get("center")
        coordination = command.payload.get("coordination")
        for viewer, document in (
            (self.left, self.first_document),
            (self.right, self.second_document),
        ):
            if document is None:
                continue
            hidden = set(document.visual.hidden_polyhedron_ids)
            hidden.update(
                polyhedron.id
                for polyhedron in document.hierarchy.polyhedra
                if (center is not None and polyhedron.center_element != center)
                or (
                    coordination is not None
                    and polyhedron.coordination_number != int(coordination)
                )
            )
            viewer.hidden_polyhedron_ids = hidden
            viewer.redraw(reset_camera=False)

    @staticmethod
    def _focus_exact_side(
        viewer: StructureViewer,
        document: StructureDocument | None,
        level: HierarchyLevel,
        polyhedron_ids: object,
        atom_indices: object,
    ) -> None:
        if document is None:
            return
        selected_polyhedra = {str(identifier) for identifier in polyhedron_ids}
        selected_atoms = {int(index) for index in atom_indices}
        all_polyhedra = {polyhedron.id for polyhedron in document.hierarchy.polyhedra}
        for polyhedron in document.hierarchy.polyhedra:
            if polyhedron.id not in selected_polyhedra:
                continue
            selected_atoms.add(polyhedron.center_index)
            selected_atoms.update(ligand.site_index for ligand in polyhedron.ligands)
        viewer.level = HierarchyLevel(level)
        viewer.hidden_polyhedron_ids = all_polyhedra - selected_polyhedra
        viewer.hidden_atom_indices = set(range(len(document.structure.sites))) - selected_atoms
        viewer.hidden_unit_ids = set()
        viewer.hidden_block_ids = set()
        viewer.hidden_connector_ids = set()
        viewer.redraw(reset_camera=False)

    def clear_focus(self) -> None:
        for viewer, document in (
            (self.left, self.first_document),
            (self.right, self.second_document),
        ):
            if document is not None:
                viewer.apply_visual_state(document.visual, redraw=True)

    def save_images(self, left_path: str | Path, right_path: str | Path) -> None:
        self._copy_camera(self.left, self.right)
        self.left.save_screenshot(left_path)
        self.right.save_screenshot(right_path)
