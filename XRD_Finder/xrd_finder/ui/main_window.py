from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMainWindow, QMessageBox, QSplitter

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.project_io import save_project_manifest
from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.services.project_service import ProjectService
from xrd_finder.ui.analysis_windows import PhaseFinderWindow, RefinementWindow, StructureWindow, ThermalWindow
from xrd_finder.ui.context_viewer import ContextViewer
from xrd_finder.ui.project_tree import ProjectTree
from xrd_finder.ui.right_panel import RightPanel


class MainWindow(QMainWindow):
    def __init__(self, project_service: ProjectService) -> None:
        super().__init__()
        self.project_service = project_service
        self.local_phase_cache = LocalPhaseCache()
        self.project: Project | None = None
        self.project_file_path: Path | None = None
        self.analysis_windows: list[object] = []

        self.setWindowTitle("XRD Phase Finder")

        self.project_tree = ProjectTree()
        self.context_viewer = ContextViewer()
        self.right_panel = RightPanel()
        self.project_tree.object_open_requested.connect(self._open_project_object)
        self.project_tree.pattern_selection_changed.connect(lambda _ids: self._apply_pattern_display())
        self.project_tree.phase_selection_changed.connect(lambda _ids: self._apply_pattern_display())
        self.right_panel.pattern_display_changed.connect(self._apply_pattern_display)

        center_splitter = QSplitter(Qt.Orientation.Horizontal)
        center_splitter.addWidget(self.project_tree)
        center_splitter.addWidget(self.context_viewer)
        center_splitter.addWidget(self.right_panel)
        center_splitter.setStretchFactor(0, 0)
        center_splitter.setStretchFactor(1, 1)
        center_splitter.setStretchFactor(2, 0)
        center_splitter.setSizes([280, 940, 280])

        self.setCentralWidget(center_splitter)
        self._build_menu()

    def set_project(self, project: Project) -> None:
        self.project = project
        self.project_tree.set_project(project)
        self.context_viewer.show_project_overview(project)
        self.right_panel.set_project(project)
        self.right_panel.set_notes(project.notes)
        self.setWindowTitle(f"XRD Phase Finder - {project.name}")
        self._apply_pattern_display()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        file_menu.addAction(self._action("New project", self._new_project))
        file_menu.addAction(self._action("Open project"))
        file_menu.addAction(self._action("Save", self._save_project))
        file_menu.addAction(self._action("Save as", self._save_project_as))

        import_menu = menu_bar.addMenu("Import")
        import_menu.addAction(self._action("XRD pattern", self._import_xrd_pattern))
        import_menu.addAction(self._action("CIF phase", self._import_cif_phase))
        import_menu.addAction(self._action("Results table"))

        analysis_menu = menu_bar.addMenu("Analysis")
        analysis_menu.addAction(self._action("Phase Finder", self._open_match_window))
        analysis_menu.addAction(self._action("Refinement (Le Bail / Rietveld)", self._open_refinement_window))
        analysis_menu.addAction(self._action("Structure analysis", self._open_structure_window))
        analysis_menu.addAction(self._action("Thermal / composition series", self._open_thermal_window))

        calculate_menu = menu_bar.addMenu("Calculate")
        calculate_menu.addAction(self._action("Run current"))
        calculate_menu.addAction(self._action("Recalculate selected"))
        calculate_menu.addAction(self._action("Batch process"))

        export_menu = menu_bar.addMenu("Export")
        export_menu.addAction(self._action("Figure"))
        export_menu.addAction(self._action("Table"))
        export_menu.addAction(self._action("Report"))
        export_menu.addAction(self._action("Project package"))

    def _action(self, text: str, callback: object | None = None) -> QAction:
        action = QAction(text, self)
        action.setEnabled(callback is not None)
        if callback is not None:
            action.triggered.connect(callback)
        return action

    def _new_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "New project", "Project name:")
        if not accepted:
            return
        project_name = name.strip() or "Untitled XRD Project"
        self.project_file_path = None
        self.set_project(Project(name=project_name))

    def _save_project(self) -> None:
        if self.project is None:
            return
        if self.project_file_path is None:
            self._save_project_as()
            return
        save_project_manifest(self.project, self.project_file_path)
        self.statusBar().showMessage(f"Saved {self.project_file_path}", 4000)

    def _save_project_as(self) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save XRD project manifest",
            f"{self.project.name}.json",
            "XRD project manifest (*.json)",
        )
        if not path:
            return
        self.project_file_path = Path(path)
        self._save_project()

    def _import_xrd_pattern(self) -> None:
        if self.project is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import XRD patterns",
            "",
            "XRD data (*.xy *.xye *.dat *.txt *.csv);;All files (*.*)",
        )
        if not paths:
            return
        for path in paths:
            source = Path(path)
            pattern = Pattern.create(name=source.stem, source_path=str(source))
            self.project_service.add_pattern(self.project, pattern)
        self._refresh_project()
        self.statusBar().showMessage(f"Imported XRD patterns: {len(paths)}", 4000)

    def _import_cif_phase(self) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import CIF phase",
            "",
            "CIF files (*.cif);;All files (*.*)",
        )
        if not path:
            return
        try:
            phase, structure = create_phase_from_cif(path)
        except Exception as exc:
            QMessageBox.critical(self, "CIF import failed", str(exc))
            return
        self.project_service.add_phase(self.project, phase)
        self.project_service.add_structure(self.project, structure)
        try:
            self.local_phase_cache.add_user_cif(path)
        except Exception as exc:
            self.statusBar().showMessage(f"CIF imported, user library indexing failed: {exc}", 6000)
        else:
            self.statusBar().showMessage(f"Imported CIF phase and indexed user library: {Path(path).name}", 4000)
            self._refresh_project()
            return
        self._refresh_project()
        self.statusBar().showMessage(f"Imported CIF phase: {Path(path).name}", 4000)

    def _refresh_project(self) -> None:
        if self.project is None:
            return
        self.project_tree.set_project(self.project)
        self.context_viewer.show_project_overview(self.project)
        self.right_panel.set_project(self.project)
        self._apply_pattern_display()

    def _open_project_object(self, object_type: str, object_id: str) -> None:
        self.context_viewer.open_project_object(object_type, object_id)

    def _apply_pattern_display(self) -> None:
        if self.project is None:
            return
        options = self.right_panel.pattern_view_options()
        selected = self.project_tree.checked_pattern_ids()
        selected_phases = self.project_tree.checked_phase_ids()
        self.context_viewer.set_pattern_display(
            str(options["mode"]),
            selected,
            str(options["offset_mode"]),
            float(options["custom_offset"]),
            selected_phases,
            bool(options["show_observed"]),
            bool(options["show_calculated"]),
            bool(options["show_hkl"]),
        )

    def _open_match_window(self) -> None:
        self._open_analysis_window(PhaseFinderWindow)

    def _open_refinement_window(self) -> None:
        self._open_analysis_window(RefinementWindow)

    def _open_structure_window(self) -> None:
        self._open_analysis_window(StructureWindow)

    def _open_thermal_window(self) -> None:
        self._open_analysis_window(ThermalWindow)

    def _open_analysis_window(self, window_class: type[object]) -> None:
        if self.project is None:
            return
        window = window_class(self.project)
        if hasattr(window, "project_changed"):
            window.project_changed.connect(self._refresh_project)
        self.analysis_windows.append(window)
        window.show()
