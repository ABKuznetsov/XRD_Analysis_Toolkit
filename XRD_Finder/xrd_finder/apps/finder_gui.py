from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.ui.analysis_windows import PhaseFinderWindow


def build_local_project(pattern_paths: list[str], cif_paths: list[str]) -> Project:
    project = Project(name="XRD Finder Project")
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
    parser = argparse.ArgumentParser(description="XRD Finder GUI")
    parser.add_argument("--pattern", action="append", default=[], help="Observed XRD pattern file")
    parser.add_argument("--cif", action="append", default=[], help="Candidate CIF file")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    icon_path = Path(__file__).resolve().parents[2] / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    project = build_local_project(args.pattern, args.cif)
    window = PhaseFinderWindow(project)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.setWindowTitle("XRD Finder")
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
