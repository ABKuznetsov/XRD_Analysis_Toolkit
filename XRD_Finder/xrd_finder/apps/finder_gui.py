from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.project_io import load_project_manifest
from xrd_finder.ui.analysis_windows import PhaseFinderWindow


def build_local_project(pattern_paths: list[str], cif_paths: list[str]) -> Project:
    project = Project(name="XRD Phase Finder Project")
    for path in pattern_paths:
        source = Path(path)
        project.patterns.append(Pattern.create(name=source.stem, source_path=str(source)))
    for path in cif_paths:
        try:
            phase, structure = create_phase_from_cif(path)
        except Exception:
            continue
        project.phases.append(phase)
        project.structures.append(structure)
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description="XRD Phase Finder GUI")
    parser.add_argument("--pattern", action="append", default=[], help="Observed XRD pattern file")
    parser.add_argument("--cif", action="append", default=[], help="Candidate CIF file")
    parser.add_argument("--project", help="XRD Phase Finder File (.xpff) to open")
    parser.add_argument("project_file", nargs="?", help=argparse.SUPPRESS)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("XRD Phase Finder")
    app.setApplicationDisplayName("XRD Phase Finder")
    app.setOrganizationName("XRD Phase Finder")
    app.setOrganizationDomain("xrdphasefinder.local")
    icon_path = Path(__file__).resolve().parents[2] / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    project_path = args.project or args.project_file
    load_error = ""
    project_loaded = False
    if project_path:
        try:
            project = load_project_manifest(project_path)
            project_loaded = True
        except Exception as exc:
            project = build_local_project(args.pattern, args.cif)
            load_error = f"Could not open XRD Phase Finder File:\n{project_path}\n\n{exc}"
    else:
        project = build_local_project(args.pattern, args.cif)
    window = PhaseFinderWindow(project)
    if project_loaded:
        window._after_project_loaded()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.setWindowTitle(f"XRD Phase Finder - {project.name}")
    prepared_file = os.environ.get("XRD_FINDER_PREPARED_FILE")
    if prepared_file:
        try:
            Path(prepared_file).write_text("prepared", encoding="utf-8")
        except OSError:
            pass
    show_signal_file = os.environ.get("XRD_FINDER_SHOW_SIGNAL_FILE")
    if show_signal_file:
        signal_path = Path(show_signal_file)
        deadline = time.monotonic() + 180.0
        while not signal_path.exists() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)
    window.show()
    if load_error:
        QTimer.singleShot(0, lambda: QMessageBox.warning(window, "Open project failed", load_error))
    app.processEvents()
    ready_file = os.environ.get("XRD_FINDER_READY_FILE")
    if ready_file:
        try:
            Path(ready_file).write_text("ready", encoding="utf-8")
        except OSError:
            pass
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
