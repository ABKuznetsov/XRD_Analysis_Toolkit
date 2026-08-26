from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from crystal_viewer.ui.main_window import MainWindow
from crystal_viewer.ui.theme import application_style


def startup_path(arguments: list[str]) -> Path | None:
    if len(arguments) > 1:
        candidate = Path(arguments[1])
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    os.environ.setdefault("QT_API", "pyside6")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("CRAFT")
    app.setOrganizationName("Scientific Tools")
    app.setStyle("Fusion")
    app.setStyleSheet(application_style())
    window = MainWindow()
    path = startup_path(sys.argv)
    if path is not None:
        window.load_path(path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
