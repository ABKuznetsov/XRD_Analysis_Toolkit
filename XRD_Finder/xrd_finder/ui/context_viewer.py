from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import numpy as np
import pyqtgraph as pg

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.io.xy_loader import load_xy
from xrd_finder.services.calculated_pattern_service import CalculatedPatternService
from xrd_finder.ui.pattern_plot_helpers import (
    add_right_side_labels,
    calculate_profile_for_structure,
    ensure_right_legend,
    estimate_background,
    estimate_profile_fwhm,
    plot_hkl_sticks,
    plot_profile,
    right_label_y,
    scale_profile_to_reference,
)
from xrd_finder.ui.xrd_plot import create_xrd_plot_widget


class ContextViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.pattern_mode = "single"
        self.active_pattern_ids: list[str] = []
        self.active_phase_ids: list[str] = []
        self.offset_mode = "Pattern height"
        self.custom_offset = 1000.0
        self.show_observed = True
        self.show_calculated = False
        self.show_hkl = False
        self.calculated_pattern_service = CalculatedPatternService()

        self.context_tabs = QTabBar()
        self.context_tabs.setExpanding(False)
        self.context_tabs.addTab("Pattern")
        self.context_tabs.addTab("Structure")
        self.context_tabs.addTab("Refinement")
        self.context_tabs.addTab("Thermal")
        self.context_tabs.addTab("Series")
        self.context_tabs.currentChanged.connect(self._on_context_changed)

        self.visual_area = QLabel("Active context")
        self.visual_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.visual_area.setObjectName("visualArea")
        self.visual_area.setStyleSheet(
            "#visualArea { background: #f7f8fa; border: 1px solid #d5d8dc; font-size: 22px; }"
        )

        self.pattern_plot = create_xrd_plot_widget()
        self.pattern_plot.setLabel("bottom", "2theta")
        self.pattern_plot.setLabel("left", "Intensity")

        self.visual_stack = QStackedWidget()
        self.visual_stack.addWidget(self.visual_area)
        self.visual_stack.addWidget(self.pattern_plot)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Field", "Value"])

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.visual_stack)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([650, 220])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.context_tabs)
        layout.addWidget(splitter)

    def show_project_overview(self, project: Project) -> None:
        self.project = project
        if not self.active_pattern_ids and project.patterns:
            self.active_pattern_ids = [project.patterns[0].id]
        self.context_tabs.setCurrentIndex(0)
        self._show_pattern_context(project)

    def open_project_object(self, object_type: str, object_id: str) -> None:
        if self.project is None:
            return
        if object_type == "pattern":
            self.context_tabs.setCurrentIndex(0)
            self.pattern_mode = "single"
            self.active_pattern_ids = [object_id]
            self._show_pattern_context(self.project)

    def set_pattern_display(
        self,
        mode: str,
        selected_pattern_ids: list[str],
        offset_mode: str = "Pattern height",
        custom_offset: float = 1000.0,
        selected_phase_ids: list[str] | None = None,
        show_observed: bool = True,
        show_calculated: bool = False,
        show_hkl: bool = False,
    ) -> None:
        self.pattern_mode = mode
        self.active_pattern_ids = list(selected_pattern_ids)
        if selected_phase_ids is not None:
            self.active_phase_ids = list(selected_phase_ids)
        self.offset_mode = offset_mode
        self.custom_offset = custom_offset
        self.show_observed = show_observed
        self.show_calculated = show_calculated
        self.show_hkl = show_hkl
        if self.project is not None:
            self.context_tabs.setCurrentIndex(0)
            self._show_pattern_context(self.project)

    def _on_context_changed(self, index: int) -> None:
        if self.project is None:
            return

        context = self.context_tabs.tabText(index)
        if context == "Pattern":
            self._show_pattern_context(self.project)
        elif context == "Structure":
            self._show_structure_context(self.project)
        elif context == "Refinement":
            self._show_refinement_context(self.project)
        elif context == "Thermal":
            self._show_thermal_context(self.project)
        elif context == "Series":
            self._show_series_context(self.project)

    def _show_pattern_context(self, project: Project) -> None:
        self.pattern_plot.clear()
        ensure_right_legend(self.pattern_plot, clear=True)
        patterns = self._patterns_to_show(project)
        selected_phases = self._phases_to_show(project)
        patterns, selected_phases = self._apply_layer_mode(patterns, selected_phases)
        if patterns or (self.show_calculated and selected_phases):
            self.visual_stack.setCurrentWidget(self.pattern_plot)
            loaded: list[tuple[Pattern, object]] = []
            errors: list[tuple[Pattern, Exception]] = []
            if self.show_observed:
                for pattern in patterns:
                    try:
                        data = load_xy(pattern.source_path)
                        if data.ndim == 1 or data.shape[1] < 2:
                            raise ValueError("XY file must contain at least two columns")
                        loaded.append((pattern, data))
                    except Exception as exc:
                        errors.append((pattern, exc))

            if loaded or (self.show_calculated and selected_phases):
                colors = ["#202124", "#d93025", "#188038", "#1a73e8", "#f9ab00", "#8e24aa"]
                y_offset = 0.0
                layer_number = 1
                right_labels = []
                for index, (pattern, data) in enumerate(loaded):
                    y = data[:, 1]
                    if self.pattern_mode == "multi":
                        y = y + y_offset
                        y_offset += self._pattern_offset(data)
                    label = f"{layer_number:02d} obs: {pattern.name}"
                    color = colors[index % len(colors)]
                    plot_profile(self.pattern_plot, data[:, 0], y, color, label)
                    right_labels.append((label, float(data[:, 0].max()), right_label_y(data[:, 0], y), color))
                    layer_number += 1
                x_grid = self._calculated_x_grid(loaded)
                calc_count = 0
                if self.show_calculated:
                    calc_count, y_offset, layer_number, calc_labels = self._plot_calculated_profiles(
                        project,
                        selected_phases,
                        x_grid,
                        loaded,
                        y_offset,
                        layer_number,
                    )
                    right_labels.extend(calc_labels)
                if self.pattern_mode == "multi" and self.offset_mode == "Pattern height":
                    add_right_side_labels(self.pattern_plot, right_labels)
                displayed_count = len(loaded) + calc_count
                title = (
                    loaded[0][0].name
                    if self.pattern_mode == "single" and loaded and calc_count == 0
                    else f"{displayed_count} pattern layers"
                )
                self.pattern_plot.setTitle(title, color="#111111", size="13pt")
                first_data = loaded[0][1] if loaded else None
                rows = [
                    ("Mode", self.pattern_mode.title()),
                    ("Observed displayed", str(len(loaded))),
                    ("Calculated displayed", str(calc_count)),
                    ("Selected", ", ".join(pattern.name for pattern, _data in loaded)),
                    ("Calculated phases", ", ".join(phase.name for phase in selected_phases)),
                    ("Offset mode", self.offset_mode if self.pattern_mode == "multi" else "n/a"),
                    ("Custom offset", f"{self.custom_offset:.4g}" if self.pattern_mode == "multi" else "n/a"),
                ]
                if loaded and first_data is not None:
                    rows.extend([
                        ("First source", loaded[0][0].source_path),
                        ("First points", str(first_data.shape[0])),
                        ("First X range", f"{first_data[:, 0].min():.4g} .. {first_data[:, 0].max():.4g}"),
                    ])
                if errors:
                    rows.append(("Ignored patterns", str(len(errors))))
            else:
                self.visual_stack.setCurrentWidget(self.visual_area)
                self.visual_area.setText("Pattern import exists, but plotting failed")
                rows = [
                    ("Plot error", "; ".join(f"{pattern.name}: {exc}" for pattern, exc in errors)),
                ]
        else:
            self.visual_stack.setCurrentWidget(self.visual_area)
            self.visual_area.setText("Pattern context\n\nImport an XRD pattern to show observed data")
            rows = [
                ("Available patterns", "0"),
                ("Primary visual object", "Observed pattern"),
                ("Expected overlays", "calculated, difference, phase contributions, HKL"),
                ("Bottom table", "metadata / peak list"),
            ]
        self._set_rows(rows)

    def _patterns_to_show(self, project: Project) -> list[Pattern]:
        if not project.patterns:
            return []
        by_id = {pattern.id: pattern for pattern in project.patterns}
        selected = [by_id[pattern_id] for pattern_id in self.active_pattern_ids if pattern_id in by_id]
        if self.pattern_mode == "multi":
            return selected
        return selected[:1]

    def _phases_to_show(self, project: Project):
        if not project.phases:
            return []
        by_id = {phase.id: phase for phase in project.phases}
        return [by_id[phase_id] for phase_id in self.active_phase_ids if phase_id in by_id]

    def _apply_layer_mode(self, patterns: list[Pattern], phases):
        if self.pattern_mode == "multi":
            return patterns, phases
        if self.show_observed and patterns:
            return patterns[:1], []
        if self.show_calculated and phases:
            return [], phases[:1]
        return [], []

    def _calculated_x_grid(self, loaded: list[tuple[Pattern, object]]):
        if loaded:
            return loaded[0][1][:, 0]
        return np.linspace(5.0, 120.0, 5000)

    def _plot_calculated_profiles(
        self,
        project: Project,
        phases,
        x_grid,
        loaded,
        y_offset: float,
        layer_number: int,
    ) -> tuple[int, float, int, list[tuple[str, float, float, str]]]:
        structures = {structure.id: structure for structure in project.structures}
        observed_max = max((float(data[:, 1].max()) for _pattern, data in loaded), default=100.0)
        profile_fwhm = self._profile_fwhm_from_loaded(loaded)
        count = 0
        right_labels = []
        for index, phase in enumerate(phases):
            structure = structures.get(phase.structure_id or "")
            if structure is None:
                continue
            try:
                x, y, peaks = calculate_profile_for_structure(
                    self.calculated_pattern_service,
                    structure,
                    x_grid,
                    fwhm=profile_fwhm,
                )
            except Exception:
                continue
            y = scale_profile_to_reference(y, observed_max)
            if self.pattern_mode == "multi":
                y = y + y_offset
                y_offset += self._pattern_offset(np.column_stack((x, y)))
            color = ["#d93025", "#1a73e8", "#188038", "#f9ab00", "#8e24aa"][index % 5]
            label = f"{layer_number:02d} calc: {phase.name}"
            plot_profile(self.pattern_plot, x, y, color, label)
            right_labels.append((label, float(np.nanmax(x)), right_label_y(x, y), color))
            if self.show_hkl:
                baseline = 0.0
                top = observed_max * 0.18
                plot_hkl_sticks(self.pattern_plot, peaks, color, baseline, top, label=f"hkl: {phase.name}")
            count += 1
            layer_number += 1
        return count, y_offset, layer_number, right_labels

    def _profile_fwhm_from_loaded(self, loaded) -> float:
        if not loaded:
            return 0.18
        _pattern, data = loaded[0]
        try:
            background = estimate_background(data[:, 0], data[:, 1])
            corrected = np.clip(data[:, 1] - background, 0.0, None)
            return estimate_profile_fwhm(data[:, 0], corrected)
        except Exception:
            return 0.18

    def _pattern_offset(self, data) -> float:
        y = data[:, 1]
        ymin = float(y.min())
        ymax = float(y.max())
        height = max(ymax - ymin, 1.0)
        if self.offset_mode == "Custom":
            return max(float(self.custom_offset), 0.0)
        if self.offset_mode == "Above noise":
            noise = self._noise_level(y)
            return max(noise * 6.0, height * 0.08, 1.0)
        return height * 1.15

    def _noise_level(self, y) -> float:
        if len(y) < 3:
            return max(float(y.max() - y.min()), 1.0)
        diff = y[1:] - y[:-1]
        sorted_abs = sorted(abs(float(value)) for value in diff)
        median = sorted_abs[len(sorted_abs) // 2] if sorted_abs else 0.0
        return max(median * 1.4826, 1.0)

    def _show_structure_context(self, project: Project) -> None:
        self.visual_stack.setCurrentWidget(self.visual_area)
        self.visual_area.setText("Structure context\n\nOriginal and refined structures")
        rows = [
            ("Available structures", str(len(project.structures))),
            ("Primary visual object", "Crystal structure"),
            ("Expected overlays", "atoms, bonds, polyhedra, cell axes, labels"),
            ("Bottom table", "cell / atoms / bonds / polyhedra"),
        ]
        self._set_rows(rows)

    def _show_refinement_context(self, project: Project) -> None:
        self.visual_stack.setCurrentWidget(self.visual_area)
        self.visual_area.setText("Refinement context\n\nObserved / calculated / difference / HKL")
        rows = [
            ("Available refinements", str(len(project.refinements))),
            ("Primary visual object", "Refinement plot"),
            ("Expected overlays", "obs, calc, diff, phase contributions, HKL ticks"),
            ("Bottom table", "parameters / phase fractions / residuals"),
        ]
        self._set_rows(rows)

    def _show_thermal_context(self, project: Project) -> None:
        self.visual_stack.setCurrentWidget(self.visual_area)
        thermal_count = sum(1 for item in project.series if item.kind == "temperature")
        self.visual_area.setText("Thermal context\n\nCell parameters and thermal expansion")
        rows = [
            ("Temperature series", str(thermal_count)),
            ("Primary visual object", "a(T), c(T), V(T), alpha(T) plots"),
            ("Expected overlays", "points, fit, residuals, ellipsoid"),
            ("Bottom table", "T, a, c, V, alpha11, alpha33, alphaV"),
        ]
        self._set_rows(rows)

    def _show_series_context(self, project: Project) -> None:
        self.visual_stack.setCurrentWidget(self.visual_area)
        self.visual_area.setText("Series context\n\nComposition, pressure, time, or custom trends")
        rows = [
            ("All series analyses", str(len(project.series))),
            ("Primary visual object", "parameter trends"),
            ("Expected overlays", "points, fit, confidence, residuals"),
            ("Bottom table", "variable, parameters, fitted values"),
        ]
        self._set_rows(rows)

    def _set_rows(self, rows: list[tuple[str, str]]) -> None:
        self.table.setRowCount(len(rows))
        for row, (field, value) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(field))
            self.table.setItem(row, 1, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
