from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from crystal_viewer.services.application_updates import ApplicationUpdate
from crystal_viewer.ui.application_update_dialog import ApplicationUpdateDialog


def _update() -> ApplicationUpdate:
    return ApplicationUpdate(
        version="0.2.0",
        release_notes="Faster startup.\nMore reliable loading.",
        installer_url="https://example.test/craft.exe",
        installer_filename="craft.exe",
        installer_size_bytes=1024,
        installer_sha256="a" * 64,
    )


def test_update_dialog_requires_explicit_download_request() -> None:
    QApplication.instance() or QApplication([])
    dialog = ApplicationUpdateDialog(_update())
    requested: list[bool] = []
    dialog.download_requested.connect(lambda: requested.append(True))

    dialog.download_button.click()

    assert requested == [True]
    dialog.deleteLater()


def test_craft_sources_schedule_background_and_manual_update_checks() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "crystal_viewer"
    main_source = (root / "ui" / "main_window.py").read_text(encoding="utf-8")
    controller_source = (root / "ui" / "application_update_dialog.py").read_text(
        encoding="utf-8"
    )

    assert '"Check for updates…"' in main_source
    assert "_schedule_application_update_check" in main_source
    assert "check_in_background(interactive=False)" in main_source
    assert "BackgroundTaskHandle" in controller_source
    assert "subprocess.Popen" in controller_source
