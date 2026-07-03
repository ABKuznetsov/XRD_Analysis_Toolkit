from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from xrd_manager.core.pattern import Pattern
from xrd_manager.core.project import Project
from xrd_manager.io.cif_loader import create_phase_from_cif
from xrd_manager.ui.analysis_windows import PhaseFinderWindow


def build_local_project(pattern_paths: list[str], cif_paths: list[str]) -> Project:
    project = Project(name="Standalone Finder Project")
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
    parser = argparse.ArgumentParser(description="Standalone Finder GUI")
    parser.add_argument("--pattern", action="append", default=[], help="Observed XRD pattern file")
    parser.add_argument("--cif", action="append", default=[], help="Candidate CIF file")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    project = build_local_project(args.pattern, args.cif)
    window = PhaseFinderWindow(project)
    window.setWindowTitle(f"XRD Finder - {project.name}")
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
