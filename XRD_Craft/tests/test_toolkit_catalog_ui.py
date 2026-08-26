from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from crystal_viewer.services.toolkit_catalog import ToolkitApplication
from crystal_viewer.ui.toolkit_catalog_dialog import (
    ToolkitCatalogDialog,
    announcement_seen,
    mark_announcement_seen,
)


def _application(revision: int = 1) -> ToolkitApplication:
    return ToolkitApplication(
        app_id="xrd_finder",
        name="XRD Phase Finder",
        description="Phase identification.",
        version="1.5.0",
        announcement_revision=revision,
        installer_url="https://example.test/finder.exe",
        installer_filename="finder.exe",
        installer_sha256="a" * 64,
        installer_size_bytes=1024,
    )


def test_craft_catalog_dialog_and_announcement_state(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app = _application()
    settings = QSettings(str(tmp_path / "craft.ini"), QSettings.Format.IniFormat)
    dialog = ToolkitCatalogDialog([app], announcement=True)
    requested: list[ToolkitApplication] = []
    dialog.install_requested.connect(requested.append)

    assert not announcement_seen(settings, app)
    dialog.install_buttons[app.app_id].click()
    mark_announcement_seen(settings, app)

    assert requested == [app]
    assert announcement_seen(settings, app)
    dialog.deleteLater()


def test_craft_main_window_exposes_catalogue_without_finder_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    main_source = (root / "src" / "crystal_viewer" / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    package_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "src" / "crystal_viewer").rglob("*.py")
    )

    assert '"More XRD tools…"' in main_source
    assert "_schedule_toolkit_announcement" in main_source
    assert "xrd_finder" not in package_source
