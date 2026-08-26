from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from xrd_finder.services.toolkit_catalog import ToolkitApplication
from xrd_finder.ui.toolkit_catalog_dialog import (
    ToolkitCatalogDialog,
    announcement_seen,
    launch_installer_with_confirmation,
    mark_announcement_seen,
)


def _application(revision: int = 1) -> ToolkitApplication:
    return ToolkitApplication(
        app_id="xrd_craft",
        name="XRD CRAFT",
        description="Crystal structure analysis.",
        version="1.0.1",
        announcement_revision=revision,
        installer_url="https://example.test/craft.exe",
        installer_filename="craft.exe",
        installer_sha256="a" * 64,
        installer_size_bytes=1024,
    )


def test_catalog_dialog_emits_install_and_not_now_requests() -> None:
    QApplication.instance() or QApplication([])
    application = _application()
    dialog = ToolkitCatalogDialog([application], announcement=True)
    install_requests: list[ToolkitApplication] = []
    not_now_requests: list[ToolkitApplication] = []
    dialog.install_requested.connect(install_requests.append)
    dialog.not_now_requested.connect(not_now_requests.append)

    dialog.install_buttons[application.app_id].click()
    dialog.not_now_button.click()

    assert install_requests == [application]
    assert not_now_requests == [application]
    dialog.deleteLater()


def test_announcement_revision_is_suppressed_until_it_changes(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    revision_one = _application(1)
    revision_two = _application(2)

    assert not announcement_seen(settings, revision_one)
    mark_announcement_seen(settings, revision_one)

    assert announcement_seen(settings, revision_one)
    assert not announcement_seen(settings, revision_two)


def test_installer_launch_requires_final_confirmation(monkeypatch, tmp_path: Path) -> None:
    application = _application()
    installer = tmp_path / application.installer_filename
    installer.write_bytes(b"installer")
    launched: list[list[str]] = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    assert not launch_installer_with_confirmation(
        None,
        application,
        installer,
        process_launcher=lambda command: launched.append(command),
    )
    assert launched == []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    assert launch_installer_with_confirmation(
        None,
        application,
        installer,
        process_launcher=lambda command: launched.append(command),
    )
    assert launched == [[str(installer)]]


def test_finder_sources_expose_permanent_catalogue_and_background_work() -> None:
    root = Path(__file__).resolve().parents[1] / "xrd_finder" / "ui"
    menu_source = (root / "phase_finder_menu.py").read_text(encoding="utf-8")
    actions_source = (root / "toolkit_catalog_actions.py").read_text(encoding="utf-8")
    window_source = (root / "analysis_windows.py").read_text(encoding="utf-8")

    assert '"More XRD tools…"' in menu_source
    assert "owner._open_toolkit_catalog" in menu_source
    assert "BackgroundTaskHandle" in actions_source
    assert "_schedule_toolkit_announcement" in window_source
