from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

from xrd_finder import __version__
from xrd_finder.services.runtime_diagnostics import (
    configure_diagnostics,
    diagnostics_enabled,
    install_exception_hooks,
    restore_exception_hooks,
    trace_operation,
)


def build_local_project(pattern_paths: list[str], cif_paths: list[str]) -> Project:
    from xrd_finder.core.pattern import Pattern
    from xrd_finder.core.project import Project

    project = Project(name="XRD Phase Finder Project")
    for path in pattern_paths:
        source = Path(path)
        project.patterns.append(Pattern.create(name=source.stem, source_path=str(source)))
    for path in cif_paths:
        try:
            from xrd_finder.io.cif_loader import create_phase_from_cif
            phase, structure = create_phase_from_cif(path)
        except Exception:
            continue
        project.phases.append(phase)
        project.structures.append(structure)
    return project


def _run_gui() -> int:
    parser = argparse.ArgumentParser(description="XRD Phase Finder GUI")
    parser.add_argument("--pattern", action="append", default=[], help="Observed XRD pattern file")
    parser.add_argument("--cif", action="append", default=[], help="Candidate CIF file")
    parser.add_argument("--project", help="XRD Phase Finder File (.xpff) to open")
    parser.add_argument("project_file", nargs="?", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # Start diagnostics before importing Qt and the scientific/UI modules.
    # Otherwise a slow cold import is invisible in the startup log.
    with trace_operation('startup.import_qt', slow_ms=0):
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import Qt, QTimer, QEventLoop
        from PySide6.QtWidgets import QApplication, QMessageBox
    with trace_operation('startup.import_ui', slow_ms=0):
        from xrd_finder.io.project_io import load_project_manifest
        from xrd_finder.ui.app_settings import configure_app_settings_storage
        from xrd_finder.ui.analysis_windows import PhaseFinderWindow

    configure_app_settings_storage()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    with trace_operation('startup.qt', slow_ms=0):
        app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("XRD Phase Finder")
    app.setApplicationDisplayName("XRD Phase Finder")
    app.setOrganizationName("XRD Phase Finder")
    app.setOrganizationDomain("xrdphasefinder.local")
    from xrd_finder.ui.project_file_open import ProjectFileOpenHandler
    file_open_handler = ProjectFileOpenHandler(app)
    icon_path = Path(__file__).resolve().parents[2] / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    from xrd_finder.ui.startup_library_refresh import offer_startup_library_refresh
    if not offer_startup_library_refresh():
        return 0
    project_path = args.project or args.project_file
    load_error = ""
    project_loaded = False
    if project_path:
        try:
            with trace_operation("project.load", project_path=project_path):
                project = load_project_manifest(project_path)
            project_loaded = True
        except Exception as exc:
            project = build_local_project(args.pattern, args.cif)
            load_error = f"Could not open XRD Phase Finder File:\n{project_path}\n\n{exc}"
    else:
        project = build_local_project(args.pattern, args.cif)
    with trace_operation('startup.window', patterns=len(project.patterns), slow_ms=0):
        window = PhaseFinderWindow(project, defer_initial_plot=bool(project.patterns) or project_loaded)
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
    window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    window.showNormal()
    window.raise_()
    window.activateWindow()
    QTimer.singleShot(250, window.raise_)
    QTimer.singleShot(250, window.activateWindow)
    if load_error:
        QTimer.singleShot(0, lambda: QMessageBox.warning(window, "Open project failed", load_error))
    with trace_operation('startup.first_paint', slow_ms=0):
        app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    ready_file = os.environ.get("XRD_FINDER_READY_FILE")
    if ready_file:
        try:
            Path(ready_file).write_text("ready", encoding="utf-8")
        except OSError:
            pass
    from xrd_finder.ui.startup_tasks import schedule_startup_tasks
    restore = (window._after_project_loaded if project_loaded else
               window._refresh_observed_pattern_plot if project.patterns else None)
    schedule_startup_tasks(window, restore=restore,
                           ready=lambda: file_open_handler.set_window(window))
    return int(app.exec())


def main() -> int:
    # The platform launcher captures stdout before Python imports the UI.
    if sys.stdout is not None:
        print(f'event=startup.entry wall_time={time.time():.3f}', flush=True)
    diagnostic_started = time.perf_counter()
    session = configure_diagnostics(__version__) if diagnostics_enabled() else None
    if sys.stdout is not None:
        print(f'event=startup.diagnostics elapsed_ms={(time.perf_counter()-diagnostic_started)*1000:.1f}', flush=True)
    if session is not None:
        install_exception_hooks()
    try:
        with trace_operation("application.run"):
            return _run_gui()
    finally:
        if session is not None:
            restore_exception_hooks()
            session.stop(timeout=1.0)


if __name__ == "__main__":
    raise SystemExit(main())
