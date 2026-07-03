from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from xrd_manager.core.project import Project
from xrd_manager.services.project_service import ProjectService
from xrd_manager.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("XRD Manager")
    app.setOrganizationName("Sci")

    project_service = ProjectService()
    project = Project(name="Untitled XRD Project")

    window = MainWindow(project_service=project_service)
    window.set_project(project)
    window.resize(1500, 900)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

