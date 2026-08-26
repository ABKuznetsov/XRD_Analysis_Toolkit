from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from xrd_finder.services.toolkit_catalog import (
    ToolkitApplication,
    download_installer,
    load_catalog_payload,
    parse_catalog,
)
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.toolkit_catalog_dialog import (
    ToolkitCatalogDialog,
    announcement_seen,
    launch_installer_with_confirmation,
    mark_announcement_seen,
)


def _bundled_catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "toolkit" / "catalog.json"


class PhaseFinderToolkitCatalogActionsMixin:
    """Window actions for discovering independently installed XRD tools."""

    def _schedule_toolkit_announcement(self) -> None:
        QTimer.singleShot(
            1200,
            lambda: self._load_toolkit_catalog(announcement=True, interactive=False),
        )

    def _open_toolkit_catalog(self) -> None:
        self._load_toolkit_catalog(announcement=False, interactive=True)

    def _load_toolkit_catalog(self, *, announcement: bool, interactive: bool) -> None:
        def task():
            payload = load_catalog_payload(bundled_path=_bundled_catalog_path())
            return parse_catalog(payload, current_app_id="xrd_finder")

        def loaded(applications) -> None:
            offered = tuple(applications)
            if announcement:
                offered = tuple(
                    app for app in offered if not announcement_seen(self.settings, app)
                )
            if not offered:
                if interactive:
                    QMessageBox.information(
                        self,
                        "More XRD tools",
                        "No additional XRD tools are available for this system.",
                    )
                return
            dialog = ToolkitCatalogDialog(
                offered,
                announcement=announcement,
                parent=self,
            )
            dialog.not_now_requested.connect(
                lambda app: mark_announcement_seen(self.settings, app)
            )

            def install(app: ToolkitApplication) -> None:
                mark_announcement_seen(self.settings, app)
                dialog.accept()
                self._install_toolkit_application(app)

            dialog.install_requested.connect(install)
            dialog.exec()

        def failed(message: str, _details: str) -> None:
            if interactive:
                QMessageBox.warning(self, "More XRD tools", message)

        self._run_background_task(
            "More XRD tools",
            "Checking for additional XRD tools...",
            task,
            loaded,
            on_error=failed,
            operation_name="toolkit.catalog.fetch",
            show_progress_dialog=interactive,
        )

    def _install_toolkit_application(self, app: ToolkitApplication) -> None:
        response = QMessageBox.question(
            self,
            f"Download {app.name}",
            f"Download the verified {app.name} {app.version} installer?\n\n"
            f"Download size: {app.installer_size_bytes / (1024 * 1024):.1f} MB",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response != QMessageBox.StandardButton.Yes:
            return

        def task(progress_signal):
            return download_installer(
                app,
                progress=lambda received, total: progress_signal(
                    f"Downloading {app.name}...", received, total
                ),
            )

        def ready(installer_path: Path) -> None:
            try:
                launch_installer_with_confirmation(self, app, Path(installer_path))
            except OSError as error:
                QMessageBox.warning(
                    self,
                    f"Install {app.name}",
                    f"Could not start the installer.\n\n{error}\n\n{installer_path}",
                )

        def failed(message: str, _details: str) -> None:
            response = QMessageBox.warning(
                self,
                f"Download {app.name}",
                f"{message}\n\nChoose Retry to try again.",
                QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Retry,
            )
            if response == QMessageBox.StandardButton.Retry:
                QTimer.singleShot(0, lambda: self._install_toolkit_application(app))

        self._run_background_task(
            f"Download {app.name}",
            f"Downloading {app.name}...",
            task,
            ready,
            on_error=failed,
            with_progress=True,
            operation_name=f"toolkit.download.{app.app_id}",
            show_progress_dialog=True,
        )
