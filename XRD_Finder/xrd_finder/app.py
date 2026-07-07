from __future__ import annotations

import sys

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from xrd_finder.core.project import Project
from xrd_finder.services.project_service import ProjectService
from xrd_finder.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("XRD Phase Finder")
    app.setOrganizationName("Sci")
    icon_path = Path(__file__).resolve().parents[1] / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    project_service = ProjectService()
    project = Project(name="XRD Phase Finder Project")

    window = MainWindow(project_service=project_service)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.set_project(project)
    window.resize(1500, 900)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
