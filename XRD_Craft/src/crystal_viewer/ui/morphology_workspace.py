from __future__ import annotations

from dataclasses import dataclass, replace
import inspect

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QSlider,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from crystal_viewer.analysis.morphology import build_bfdh_planes, reduce_hkl
from crystal_viewer.analysis.morphology_geometry import MorphologyModel, build_morphology_model
from crystal_viewer.analysis.surface_markings import (
    SurfaceMarking,
    SurfaceMarkingKind,
    build_induction_contours,
    build_twin_striation,
)
from crystal_viewer.analysis.twin_geometry import TwinAggregate, build_twin_aggregate
from crystal_viewer.analysis.twin_law import twin_cartesian_transform, validate_distinct_twin
from crystal_viewer.analysis.twin_state import TwinAggregateKind
from crystal_viewer.core.symmetry import parse_affine_operation
from crystal_viewer.analysis.morphology_selection import (
    PrimaryFormSelection,
    select_primary_forms,
    with_active_families,
)
from crystal_viewer.analysis.morphology_state import (
    MorphologyEditState,
    apply_edit_state,
    initialize_primary_selection,
)
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.ui.morphology_requests import MorphologyRequestManager, QtMorphologyExecutor
from crystal_viewer.ui.morphology_table_model import MorphologyTableEdit, MorphologyTableModel
from crystal_viewer.ui.morphology_viewer import MorphologyViewer
from crystal_viewer.ui.morphology_colors import allocate_family_colors
from crystal_viewer.ui.striation_table_model import StriationEdit, StriationTableModel
from crystal_viewer.ui.twin_editor import TwinEditor
from crystal_viewer.ui.twin_table_model import TwinTableModel


@dataclass(frozen=True, slots=True)
class MorphologyCalculation:
    reference_model: MorphologyModel
    current_model: MorphologyModel
    selection: PrimaryFormSelection
    state: MorphologyEditState
    color_by_family: object
    twin_aggregate: TwinAggregate | None = None
    induction_contours: tuple = ()
    twin_segments: tuple = ()


class MorphologyWorkspace(QWidget):
    save_requested = Signal()
    open_requested = Signal()
    export_csv_requested = Signal()
    export_png_requested = Signal()
    cif_files_dropped = Signal(tuple)
    result_installed = Signal(bool)

    def __init__(self, parent=None, *, executor=None, viewer_factory=MorphologyViewer) -> None:
        super().__init__(parent)
        self.document: StructureDocument | None = None
        self.state = MorphologyEditState()
        self.current_model: MorphologyModel | None = None
        self.current_calculation: MorphologyCalculation | None = None
        self._signature = None
        self._initialize_primary_on_request = False
        self._pending_incompatible_state: MorphologyEditState | None = None
        self._selected_facet_family = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(28)
        self.splitter.setChildrenCollapsible(True)
        root.addWidget(self.splitter)
        self.viewer = viewer_factory()
        self.splitter.addWidget(self.viewer)

        lower = QFrame()
        self.lower_panel = lower
        lower.setMinimumHeight(0)
        lower.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(7, 7, 7, 7)
        self.method_label = QLabel(
            "BFDH geometric morphology prediction — not a thermodynamic equilibrium Wulff shape."
        )
        self.method_label.setWordWrap(True)
        self.method_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lower_layout.addWidget(self.method_label)
        self.status_label = QLabel("Open a CIF structure to calculate morphology.")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lower_layout.addWidget(self.status_label)

        self.mismatch_bar = QFrame()
        mismatch_layout = QHBoxLayout(self.mismatch_bar)
        mismatch_layout.setContentsMargins(0, 0, 0, 0)
        self.mismatch_label = QLabel()
        self.mismatch_label.setWordWrap(True)
        self.mismatch_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.apply_mismatch_button = QPushButton("Load as manual model")
        self.cancel_mismatch_button = QPushButton("Cancel")
        mismatch_layout.addWidget(self.mismatch_label, 1)
        mismatch_layout.addWidget(self.apply_mismatch_button)
        mismatch_layout.addWidget(self.cancel_mismatch_button)
        self.mismatch_bar.hide()
        lower_layout.addWidget(self.mismatch_bar)

        self.editor_tabs = QTabWidget()
        self.editor_tabs.setMinimumHeight(0)
        self.editor_tabs.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Ignored,
        )
        lower_layout.addWidget(self.editor_tabs, 1)

        self.facets_page = QWidget()
        facets_layout = QVBoxLayout(self.facets_page)
        facets_layout.setContentsMargins(0, 6, 0, 0)
        commands = QHBoxLayout()
        self.primary_coverage_label = QLabel("Primary coverage: 80%")
        commands.addWidget(self.primary_coverage_label)
        self.restore_primary_button = QPushButton("Restore primary forms")
        commands.addWidget(self.restore_primary_button)
        commands.addWidget(QLabel("Maximum |hkl|"))
        self.max_index = QSpinBox()
        self.max_index.setRange(1, 12)
        self.max_index.setValue(3)
        self.max_index.valueChanged.connect(self._max_index_changed)
        commands.addWidget(self.max_index)
        self.hkl_input = QLineEdit()
        self.hkl_input.setPlaceholderText("h k l")
        self.hkl_input.setMaximumWidth(90)
        self.add_family_button = QPushButton("Add (hkl)")
        self.remove_family_button = QPushButton("Remove added")
        commands.addWidget(self.hkl_input)
        commands.addWidget(self.add_family_button)
        commands.addWidget(self.remove_family_button)
        self.reset_row_button = QPushButton("Reset row to BFDH")
        self.reset_all_button = QPushButton("Reset all")
        commands.addWidget(self.reset_row_button)
        commands.addWidget(self.reset_all_button)
        commands.addStretch()
        facets_layout.addLayout(commands)

        distance_controls = QHBoxLayout()
        self.selected_facet_label = QLabel("Select a facet to edit its distance")
        distance_controls.addWidget(self.selected_facet_label)
        distance_controls.addWidget(QLabel("Distance from centre"))
        self.distance_slider = QSlider(Qt.Orientation.Horizontal)
        self.distance_slider.setRange(20, 300)
        self.distance_slider.setValue(100)
        self.distance_slider.setEnabled(False)
        self.distance_slider.setMinimumWidth(180)
        self.distance_slider.setToolTip("20–300% of the BFDH distance ρ₀")
        distance_controls.addWidget(self.distance_slider, 1)
        self.distance_ratio_label = QLabel("—")
        self.distance_ratio_label.setMinimumWidth(54)
        distance_controls.addWidget(self.distance_ratio_label)
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0.000001, 1_000_000.0)
        self.distance_spin.setDecimals(6)
        self.distance_spin.setKeyboardTracking(False)
        self.distance_spin.setEnabled(False)
        distance_controls.addWidget(self.distance_spin)
        facets_layout.addLayout(distance_controls)

        self.table = QTableView()
        self.table.setMinimumHeight(0)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.clicked.connect(self._row_selected)
        facets_layout.addWidget(self.table, 1)
        self.editor_tabs.addTab(self.facets_page, "Facets")

        self.twins_page = QWidget()
        twins_layout = QVBoxLayout(self.twins_page)
        twins_layout.setContentsMargins(0, 6, 0, 0)
        self.twin_editor = TwinEditor(self.twins_page)
        twins_layout.addWidget(self.twin_editor)
        self.twin_table = QTableView(self.twins_page)
        self.twin_table.setMinimumHeight(0)
        self.twin_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.twin_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.twin_table.clicked.connect(self._twin_row_selected)
        twins_layout.addWidget(self.twin_table, 1)
        self.editor_tabs.addTab(self.twins_page, "Twins")

        self.striation_page = QWidget()
        striation_layout = QVBoxLayout(self.striation_page)
        striation_layout.setContentsMargins(0, 6, 0, 0)
        marking_controls = QHBoxLayout()
        marking_controls.addWidget(QLabel("Selected family marking"))
        self.marking_kind = QComboBox(self.striation_page)
        self.marking_kind.addItem("None", "none")
        self.marking_kind.addItem("Induction", SurfaceMarkingKind.INDUCTION.value)
        self.marking_kind.addItem("Twin (derived)", SurfaceMarkingKind.TWIN.value)
        marking_controls.addWidget(self.marking_kind)
        marking_controls.addWidget(QLabel("Density"))
        self.marking_density = QSpinBox(self.striation_page)
        self.marking_density.setRange(1, 50)
        self.marking_density.setValue(6)
        marking_controls.addWidget(self.marking_density)
        marking_controls.addWidget(QLabel("Line width"))
        self.marking_line_width = QDoubleSpinBox(self.striation_page)
        self.marking_line_width.setRange(0.25, 8.0)
        self.marking_line_width.setValue(1.5)
        marking_controls.addWidget(self.marking_line_width)
        self.marking_apply_button = QPushButton("Apply marking", self.striation_page)
        marking_controls.addWidget(self.marking_apply_button)
        marking_controls.addStretch()
        striation_layout.addLayout(marking_controls)
        self.marking_status = QLabel(
            "Induction is a manual growth/contact annotation; twin lines require polysynthetic geometry."
        )
        self.marking_status.setWordWrap(True)
        self.marking_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        striation_layout.addWidget(self.marking_status)
        self.striation_table = QTableView(self.striation_page)
        self.striation_table.setMinimumHeight(0)
        self.striation_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.striation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.striation_table.clicked.connect(self._striation_row_selected)
        striation_layout.addWidget(self.striation_table, 1)
        self.editor_tabs.addTab(self.striation_page, "Striation")
        self.splitter.addWidget(lower)
        self.splitter.setSizes((560, 330))
        self._expanded_panel_sizes = (560, 330)
        handle = self.splitter.handle(1)
        handle_layout = QHBoxLayout(handle)
        handle_layout.setContentsMargins(0, 2, 0, 2)
        handle_layout.addStretch()
        self.panel_toggle_button = QPushButton("Hide table", handle)
        self.panel_toggle_button.setFixedHeight(24)
        handle_layout.addWidget(self.panel_toggle_button)
        handle_layout.addStretch()

        self.reset_row_button.clicked.connect(self._reset_selected)
        self.reset_all_button.clicked.connect(self._reset_all)
        self.restore_primary_button.clicked.connect(self._restore_primary)
        self.add_family_button.clicked.connect(self._add_family)
        self.remove_family_button.clicked.connect(self._remove_selected_family)
        self.twin_editor.spec_changed.connect(self._twin_spec_changed)
        self.marking_apply_button.clicked.connect(self._apply_selected_marking)
        self.apply_mismatch_button.clicked.connect(self._apply_incompatible_state)
        self.cancel_mismatch_button.clicked.connect(self._cancel_incompatible_state)
        self.panel_toggle_button.clicked.connect(self._toggle_lower_panel)
        self.distance_slider.valueChanged.connect(self._distance_slider_changed)
        self.distance_spin.editingFinished.connect(self._distance_spin_finished)
        drop_signal = getattr(self.viewer, "cif_files_dropped", None)
        if drop_signal is not None:
            drop_signal.connect(self.cif_files_dropped)
        pick_signal = getattr(self.viewer, "family_picked", None)
        if pick_signal is not None:
            pick_signal.connect(self._family_picked)

        real_executor = executor or QtMorphologyExecutor(self)
        self._requests = MorphologyRequestManager(
            real_executor,
            self._ready,
            self._failed,
            max_cached=8,
        )

    def _toggle_lower_panel(self) -> None:
        sizes = self.splitter.sizes()
        if sizes[1] > 0:
            self._expanded_panel_sizes = tuple(sizes)
            self.splitter.setSizes((sum(sizes), 0))
            self.panel_toggle_button.setText("Show table")
            return
        total = max(sum(sizes), sum(self._expanded_panel_sizes), 1)
        previous_lower = max(int(self._expanded_panel_sizes[1]), 200)
        lower = min(previous_lower, max(total - 1, 1))
        self.splitter.setSizes((max(total - lower, 1), lower))
        self.panel_toggle_button.setText("Hide table")

    def set_document(self, document: StructureDocument) -> None:
        changed = self.document is not document
        if changed:
            self._cancel_incompatible_state()
            self._selected_facet_family = None
            self.current_model = None
            self.current_calculation = None
            self.table.setModel(None)
            self.twin_table.setModel(None)
            self.striation_table.setModel(None)
            self.viewer.clear()
            self._sync_distance_editor()
        self.document = document
        stored = document.morphology_state
        self.state = stored if isinstance(stored, MorphologyEditState) else MorphologyEditState()
        self._initialize_primary_on_request = not isinstance(stored, MorphologyEditState)
        self.max_index.blockSignals(True)
        self.max_index.setValue(self.state.max_index)
        self.max_index.blockSignals(False)
        self._request(reset_camera=changed)

    def _request(self, *, reset_camera: bool = False) -> None:
        if self.document is None:
            return
        document = self.document
        state = self.state
        initialize_primary = self._initialize_primary_on_request
        signature = (document.id, document.content_identity(), state, initialize_primary)
        self._signature = signature
        self.set_loading("Calculating BFDH morphology…")

        def work():
            base = build_bfdh_planes(document.structure, state.max_index)
            selection = select_primary_forms(
                document.structure.cell,
                base,
                target=state.selection_policy.target,
            )
            resolved_state = (
                initialize_primary_selection(state, selection)
                if initialize_primary
                else state
            )
            planes = apply_edit_state(document.structure, base, resolved_state)
            current_model = build_morphology_model(document.structure.cell, planes)
            reference_model = build_morphology_model(
                document.structure.cell,
                with_active_families(base, {plane.family.hkl for plane in base}),
            )
            colors = allocate_family_colors(plane.family.hkl for plane in planes)
            twin_aggregate = None
            induction_contours = []
            twin_segments = ()
            if resolved_state.twin is not None:
                transform = twin_cartesian_transform(
                    document.structure.cell,
                    resolved_state.twin.law,
                )
                rotations = tuple(
                    parse_affine_operation(operation).rotation
                    for operation in document.structure.symmetry_operations
                )
                validate_distinct_twin(
                    transform,
                    rotations,
                    document.structure.cell,
                )
                twin_aggregate = build_twin_aggregate(
                    document.structure.cell,
                    current_model,
                    resolved_state.twin,
                )
            visible_facets = (
                current_model.facets
                if twin_aggregate is None
                else twin_aggregate.external_facets
            )
            for marking in resolved_state.markings:
                if marking.kind is SurfaceMarkingKind.INDUCTION:
                    induction_contours.extend(
                        build_induction_contours(visible_facets, marking)
                    )
            if (
                twin_aggregate is not None
                and resolved_state.twin is not None
                and resolved_state.twin.kind is TwinAggregateKind.POLYSYNTHETIC
            ):
                twin_families = {
                    marking.target_family
                    for marking in resolved_state.markings
                    if marking.kind is SurfaceMarkingKind.TWIN
                }
                twin_segments = tuple(
                    segment
                    for segment in build_twin_striation(twin_aggregate)
                    if segment.family_hkl in twin_families
                )
            calculation = MorphologyCalculation(
                reference_model,
                current_model,
                selection,
                resolved_state,
                colors,
                twin_aggregate,
                tuple(induction_contours),
                twin_segments,
            )
            return calculation, reset_camera

        self._requests.request(signature, work)

    def _ready(self, signature, bundle) -> None:
        if signature != self._signature:
            return
        calculation, reset_camera = bundle
        self.state = calculation.state
        self._initialize_primary_on_request = False
        if self.document is not None:
            self.document.morphology_state = self.state
        self.install_result(calculation, reset_camera=reset_camera)

    def _failed(self, signature, error: BaseException) -> None:
        if signature == self._signature:
            if self.current_calculation is not None:
                self.state = self.current_calculation.state
                self.twin_editor.set_spec(self.state.twin)
                if self.document is not None:
                    self.document.morphology_state = self.state
                    self._signature = (
                        self.document.id,
                        self.document.content_identity(),
                        self.state,
                        False,
                    )
            self.show_error(str(error))

    def install_result(
        self,
        result: MorphologyCalculation | MorphologyModel,
        *,
        reset_camera: bool = False,
    ) -> None:
        if isinstance(result, MorphologyCalculation):
            calculation = result
        else:
            if self.document is None:
                raise ValueError("A document is required to install a morphology model.")
            selection = select_primary_forms(self.document.structure.cell, result.planes)
            calculation = MorphologyCalculation(
                result,
                result,
                selection,
                self.state,
                allocate_family_colors(plane.family.hkl for plane in result.planes),
            )
        model = calculation.current_model
        self.current_calculation = calculation
        self.current_model = model
        user_added_families = {
            plane.family.hkl
            for plane in model.planes
            if any(
                override.user_added and override.hkl in plane.family.equivalents
                for override in calculation.state.overrides
            )
        }
        table_model = MorphologyTableModel(
            model,
            self.table,
            color_by_family=calculation.color_by_family,
            reference_model=calculation.reference_model,
            primary_families=set(calculation.state.primary_families),
            user_added_families=user_added_families,
        )
        table_model.edit_requested.connect(self._edit_requested)
        self.table.setModel(table_model)
        self.table.resizeColumnsToContents()
        self._restore_selected_facet()
        self.twin_editor.set_spec(calculation.state.twin)
        self.twin_editor.set_error("")
        self.twin_table.setModel(
            TwinTableModel(
                calculation.twin_aggregate,
                self.twin_table,
                spec=calculation.state.twin,
            )
        )
        twin_available = (
            calculation.state.twin is not None
            and calculation.state.twin.kind is TwinAggregateKind.POLYSYNTHETIC
            and calculation.twin_aggregate is not None
        )
        striation_model = StriationTableModel(
            (plane.family.hkl for plane in model.planes),
            calculation.state.markings,
            twin_available,
            self.striation_table,
        )
        striation_model.edit_requested.connect(self._striation_edit_requested)
        self.striation_table.setModel(striation_model)
        set_name = getattr(self.viewer, "set_structure_name", None)
        if set_name is not None and self.document is not None:
            set_name(self.document.structure.name)
        set_model = self.viewer.set_model
        if "color_by_family" in inspect.signature(set_model).parameters:
            viewer_arguments = {
                "color_by_family": calculation.color_by_family,
                "reset_camera": reset_camera,
            }
            parameters = inspect.signature(set_model).parameters
            if "aggregate" in parameters:
                viewer_arguments.update(
                    aggregate=calculation.twin_aggregate,
                    induction_contours=calculation.induction_contours,
                    twin_segments=calculation.twin_segments,
                    markings=calculation.state.markings,
                )
            set_model(model, **viewer_arguments)
        else:
            set_model(model, reset_camera=reset_camera)
        manifested = sum(area > 0.0 for area in model.area_by_family.values())
        warnings = model.warnings + (
            ()
            if calculation.twin_aggregate is None
            else calculation.twin_aggregate.warnings
        )
        warning = f" · {'; '.join(warnings)}" if warnings else ""
        self.status_label.setText(
            f"BFDH ready · {manifested} manifested families · relative volume {model.volume:.6g}{warning}"
        )
        self.primary_coverage_label.setText(
            "Primary forms: target 80% · "
            f"coverage {100.0 * calculation.selection.coverage:.1f}%"
        )
        self.result_installed.emit(True)

    def set_loading(self, text: str) -> None:
        self.status_label.setText(text)

    def show_error(self, text: str) -> None:
        self.status_label.setText(f"Morphology was not changed: {text}")

    def offer_incompatible_state(self, state: MorphologyEditState, message: str) -> None:
        self._pending_incompatible_state = state
        self.mismatch_label.setText(
            f"{message} You can load the saved values as a manual model or cancel."
        )
        self.mismatch_bar.show()

    def _apply_incompatible_state(self) -> None:
        if self._pending_incompatible_state is None:
            return
        self.state = self._pending_incompatible_state
        self._pending_incompatible_state = None
        self.mismatch_bar.hide()
        self.max_index.blockSignals(True)
        self.max_index.setValue(self.state.max_index)
        self.max_index.blockSignals(False)
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _cancel_incompatible_state(self) -> None:
        self._pending_incompatible_state = None
        self.mismatch_bar.hide()

    def _edit_requested(self, edit: MorphologyTableEdit) -> None:
        if edit.rho is not None:
            self.state = self.state.with_distance(edit.hkl, edit.rho)
        if edit.enabled is not None:
            self.state = self.state.with_enabled(edit.hkl, edit.enabled)
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _max_index_changed(self, value: int) -> None:
        self.state = replace(self.state, max_index=int(value))
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _selected_family(self):
        model = self.table.model()
        index = self.table.currentIndex()
        if not isinstance(model, MorphologyTableModel) or not index.isValid():
            return None
        return model.data(model.index(index.row(), 0), MorphologyTableModel.FamilyRole)

    def _selected_plane(self):
        if self.current_model is None or self._selected_facet_family is None:
            return None
        return next(
            (
                plane
                for plane in self.current_model.planes
                if self._selected_facet_family == plane.family.hkl
                or self._selected_facet_family in plane.family.equivalents
            ),
            None,
        )

    def _sync_distance_editor(self) -> None:
        plane = self._selected_plane()
        enabled = plane is not None
        self.distance_slider.setEnabled(enabled)
        self.distance_spin.setEnabled(enabled)
        if plane is None:
            self.selected_facet_label.setText("Select a facet to edit its distance")
            self.distance_ratio_label.setText("—")
            return
        h, k, l = plane.family.hkl
        ratio = plane.rho / plane.rho0
        self.selected_facet_label.setText(
            f"Selected {{{h} {k} {l}}} · ρ₀ = {plane.rho0:.6g}"
        )
        self.distance_slider.blockSignals(True)
        self.distance_slider.setValue(
            max(self.distance_slider.minimum(), min(self.distance_slider.maximum(), round(100 * ratio)))
        )
        self.distance_slider.blockSignals(False)
        self.distance_spin.blockSignals(True)
        self.distance_spin.setSingleStep(max(plane.rho0 * 0.01, 0.000001))
        self.distance_spin.setValue(plane.rho)
        self.distance_spin.blockSignals(False)
        self.distance_ratio_label.setText(f"{100 * ratio:.0f}% ρ₀")

    def _restore_selected_facet(self) -> None:
        model = self.table.model()
        if not isinstance(model, MorphologyTableModel):
            self._sync_distance_editor()
            return
        target = self._selected_facet_family
        if target is not None:
            for row, plane in enumerate(model.model.planes):
                if target == plane.family.hkl or target in plane.family.equivalents:
                    self._selected_facet_family = plane.family.hkl
                    self.table.selectRow(row)
                    self.table.setCurrentIndex(model.index(row, 0))
                    break
            else:
                self._selected_facet_family = None
        self._sync_distance_editor()

    def _apply_selected_distance(self, rho: float) -> None:
        plane = self._selected_plane()
        if plane is None:
            return
        self.state = self.state.with_distance(plane.family.hkl, rho)
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _distance_slider_changed(self, percent: int) -> None:
        plane = self._selected_plane()
        if plane is None:
            return
        self._apply_selected_distance(plane.rho0 * float(percent) / 100.0)

    def _distance_spin_finished(self) -> None:
        if self._selected_plane() is not None:
            self._apply_selected_distance(self.distance_spin.value())

    def _reset_selected(self) -> None:
        family = self._selected_family()
        if family is None:
            return
        self.state = self.state.reset_family(family)
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _reset_all(self) -> None:
        self.state = self.state.reset_all()
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _restore_primary(self) -> None:
        self.state = self.state.reset_primary()
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _add_family(self) -> None:
        text = self.hkl_input.text().strip().replace("(", " ").replace(")", " ").replace(",", " ")
        parts = text.split()
        try:
            if len(parts) != 3:
                raise ValueError("Enter three integer Miller indices: h k l.")
            hkl = tuple(int(value) for value in parts)
            self.state = self.state.with_added_family(hkl)
        except ValueError as error:
            self.show_error(str(error))
            return
        self.hkl_input.clear()
        self._selected_facet_family = reduce_hkl(hkl)
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _remove_selected_family(self) -> None:
        family = self._selected_family()
        if family is None or self.current_model is None:
            return
        plane = next((item for item in self.current_model.planes if item.family.hkl == family), None)
        if plane is None:
            return
        override = next(
            (
                item
                for item in self.state.overrides
                if item.user_added and item.hkl in plane.family.equivalents
            ),
            None,
        )
        if override is None:
            self.show_error("Only a user-added family can be removed.")
            return
        self.state = self.state.remove_added_family(override.hkl, plane.family.equivalents)
        self._selected_facet_family = None
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _row_selected(self, index) -> None:
        model = self.table.model()
        if isinstance(model, MorphologyTableModel) and index.isValid():
            family = model.data(model.index(index.row(), 0), MorphologyTableModel.FamilyRole)
            self._selected_facet_family = family
            self._sync_distance_editor()
            self.viewer.select_family(family)
            self.twin_editor.set_selected_family(family)
            self._select_striation_family(family)

    def _family_picked(self, family) -> None:
        model = self.table.model()
        if not isinstance(model, MorphologyTableModel):
            return
        for row in range(model.rowCount()):
            if model.data(model.index(row, 0), MorphologyTableModel.FamilyRole) == family:
                self._selected_facet_family = family
                self.table.selectRow(row)
                self.table.scrollTo(model.index(row, 0))
                self._sync_distance_editor()
                self.twin_editor.set_selected_family(family)
                self._select_striation_family(family)
                return

    def _select_striation_family(self, family) -> None:
        model = self.striation_table.model()
        if not isinstance(model, StriationTableModel):
            return
        for row in range(model.rowCount()):
            if model.data(model.index(row, 0), model.FamilyRole) == family:
                self.striation_table.selectRow(row)
                self.striation_table.scrollTo(model.index(row, 0))
                return

    def _striation_row_selected(self, index) -> None:
        model = self.striation_table.model()
        if not isinstance(model, StriationTableModel) or not index.isValid():
            return
        family = model.data(model.index(index.row(), 0), model.FamilyRole)
        facet_model = self.table.model()
        if isinstance(facet_model, MorphologyTableModel):
            for row in range(facet_model.rowCount()):
                if facet_model.data(facet_model.index(row, 0), facet_model.FamilyRole) == family:
                    self.table.selectRow(row)
                    break
        self.viewer.select_family(family)
        self.twin_editor.set_selected_family(family)

    def _twin_row_selected(self, index) -> None:
        model = self.twin_table.model()
        if not isinstance(model, TwinTableModel) or not index.isValid():
            return
        domain_id = model.data(model.index(index.row(), 0), model.DomainRole)
        select_domain = getattr(self.viewer, "select_domain", None)
        if select_domain is not None:
            select_domain(domain_id)

    def _store_state_and_request(self) -> None:
        if self.document is not None:
            self.document.morphology_state = self.state
        self._request(reset_camera=False)

    def _twin_spec_changed(self, spec) -> None:
        markings = self.state.markings
        if spec is None or spec.kind is not TwinAggregateKind.POLYSYNTHETIC:
            markings = tuple(
                marking
                for marking in markings
                if marking.kind is not SurfaceMarkingKind.TWIN
            )
        self.state = replace(self.state, twin=spec, markings=markings)
        self._store_state_and_request()

    def _striation_edit_requested(self, edit: StriationEdit) -> None:
        previous = next(
            (
                marking
                for marking in self.state.markings
                if edit.marking is not None
                and marking.target_family == edit.family_hkl
                and marking.kind is edit.marking.kind
            ),
            None,
        )
        style_only = (
            previous is not None
            and edit.marking is not None
            and previous.density == edit.marking.density
            and previous.line_width != edit.marking.line_width
            and self.current_calculation is not None
        )
        state = self.state
        for kind in SurfaceMarkingKind:
            state = state.remove_marking(edit.family_hkl, kind)
        if edit.marking is not None:
            state = state.with_marking(edit.marking)
        self.state = state
        if style_only and self.current_calculation is not None:
            if self.document is not None:
                self.document.morphology_state = state
                self._signature = (
                    self.document.id,
                    self.document.content_identity(),
                    state,
                    False,
                )
            self.install_result(replace(self.current_calculation, state=state), reset_camera=False)
            return
        self._store_state_and_request()

    def _selected_marking_family(self):
        model = self.striation_table.model()
        index = self.striation_table.currentIndex()
        if isinstance(model, StriationTableModel) and index.isValid():
            return model.data(model.index(index.row(), 0), model.FamilyRole)
        return self._selected_family()

    def _apply_selected_marking(self) -> None:
        family = self._selected_marking_family()
        if family is None:
            self.marking_status.setText("Select a family in the Facets or Striation table.")
            return
        raw_kind = self.marking_kind.currentData()
        state = self.state
        for kind in SurfaceMarkingKind:
            state = state.remove_marking(family, kind)
        if raw_kind != "none":
            try:
                marking = SurfaceMarking(
                    family,
                    SurfaceMarkingKind(raw_kind),
                    self.marking_density.value(),
                    self.marking_line_width.value(),
                )
                state = state.with_marking(marking)
            except (TypeError, ValueError) as error:
                self.marking_status.setText(str(error))
                return
        self.state = state
        self.marking_status.setText("Marking updated.")
        self._store_state_and_request()

    def close_requests(self, timeout_ms: int = 100) -> bool:
        return self._requests.close(timeout_ms)


__all__ = ["MorphologyWorkspace"]
