from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import subprocess

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from crystal_viewer.services.toolkit_catalog import (
    ToolkitApplication,
    download_installer,
    load_catalog_payload,
    parse_catalog,
)


def announcement_seen(settings: QSettings, app: ToolkitApplication) -> bool:
    value = settings.value(f"toolkit/announcements/{app.app_id}", 0)
    try:
        return int(value) >= app.announcement_revision
    except (TypeError, ValueError):
        return False


def mark_announcement_seen(settings: QSettings, app: ToolkitApplication) -> None:
    settings.setValue(f"toolkit/announcements/{app.app_id}", app.announcement_revision)
    settings.sync()


class ToolkitCatalogDialog(QDialog):
    install_requested = Signal(object)
    not_now_requested = Signal(object)

    def __init__(
        self,
        applications: Iterable[ToolkitApplication],
        *,
        announcement: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.applications = tuple(applications)
        self.install_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle("More XRD tools")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        heading = QLabel("Extend your XRD workspace")
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(heading)
        layout.addWidget(
            QLabel(
                "Each tool is installed and updated independently. "
                "Nothing is downloaded until you choose Install."
            )
        )
        for app in self.applications:
            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card_layout = QHBoxLayout(card)
            text = QVBoxLayout()
            title = QLabel(f"{app.name}  {app.version}")
            title.setStyleSheet("font-weight: 700;")
            description = QLabel(app.description)
            description.setWordWrap(True)
            text.addWidget(title)
            text.addWidget(description)
            card_layout.addLayout(text, 1)
            button = QPushButton("Install")
            button.clicked.connect(
                lambda _checked=False, selected=app: self.install_requested.emit(selected)
            )
            self.install_buttons[app.app_id] = button
            card_layout.addWidget(button)
            layout.addWidget(card)
        controls = QHBoxLayout()
        controls.addStretch(1)
        if announcement:
            not_now = QPushButton("Not now")
            not_now.clicked.connect(self._not_now)
            controls.addWidget(not_now)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        layout.addLayout(controls)

    def _not_now(self) -> None:
        for app in self.applications:
            self.not_now_requested.emit(app)
        self.reject()


class ToolkitCatalogWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, task: Callable, *, with_progress: bool = False) -> None:
        super().__init__()
        self.task = task
        self.with_progress = with_progress

    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.task(self.progress.emit)
            else:
                result = self.task()
            self.finished.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class BackgroundTaskHandle(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, task: Callable, parent: QObject, *, with_progress: bool = False) -> None:
        super().__init__(parent)
        self.thread = QThread(self)
        self.worker = ToolkitCatalogWorker(task, with_progress=with_progress)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.finished.emit)
        self.worker.failed.connect(self.failed.emit)
        self.worker.progress.connect(self.progress.emit)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.deleteLater)

    def start(self) -> None:
        self.thread.start()


def _bundled_catalog_path() -> Path:
    return Path(__file__).resolve().parents[4] / "toolkit" / "catalog.json"


class ToolkitCatalogController(QObject):
    def __init__(self, window: QMainWindow, settings: QSettings) -> None:
        super().__init__(window)
        self.window = window
        self.settings = settings
        self._tasks: set[BackgroundTaskHandle] = set()

    def schedule_announcement(self) -> None:
        QTimer.singleShot(1200, lambda: self._load(announcement=True, interactive=False))

    def open_catalog(self) -> None:
        self._load(announcement=False, interactive=True)

    def _run(self, task: Callable, success: Callable, failure: Callable, *, with_progress=False):
        handle = BackgroundTaskHandle(task, self, with_progress=with_progress)
        self._tasks.add(handle)

        def finish(result):
            self._tasks.discard(handle)
            success(result)

        def fail(message):
            self._tasks.discard(handle)
            failure(message)

        handle.finished.connect(finish)
        handle.failed.connect(fail)
        handle.start()
        return handle

    def _load(self, *, announcement: bool, interactive: bool) -> None:
        progress = None
        if interactive:
            progress = QProgressDialog("Checking for additional XRD tools...", "", 0, 0, self.window)
            progress.setCancelButton(None)
            progress.setWindowTitle("More XRD tools")
            progress.show()
        self.window.statusBar().showMessage("Checking for additional XRD tools...")

        def task():
            payload = load_catalog_payload(bundled_path=_bundled_catalog_path())
            return parse_catalog(payload, current_app_id="xrd_craft")

        def success(applications):
            if progress:
                progress.close()
            self.window.statusBar().showMessage("Ready")
            offered = tuple(applications)
            if announcement:
                offered = tuple(app for app in offered if not announcement_seen(self.settings, app))
            if not offered:
                if interactive:
                    QMessageBox.information(
                        self.window,
                        "More XRD tools",
                        "No additional XRD tools are available for this system.",
                    )
                return
            dialog = ToolkitCatalogDialog(offered, announcement=announcement, parent=self.window)
            dialog.not_now_requested.connect(lambda app: mark_announcement_seen(self.settings, app))

            def install(app):
                mark_announcement_seen(self.settings, app)
                dialog.accept()
                self._install(app)

            dialog.install_requested.connect(install)
            dialog.exec()

        def failure(message):
            if progress:
                progress.close()
            self.window.statusBar().showMessage(f"Toolkit catalogue: {message}")
            if interactive:
                QMessageBox.warning(self.window, "More XRD tools", message)

        self._run(task, success, failure)

    def _install(self, app: ToolkitApplication) -> None:
        response = QMessageBox.question(
            self.window,
            f"Download {app.name}",
            f"Download the verified {app.name} {app.version} installer?\n\n"
            f"Download size: {app.installer_size_bytes / (1024 * 1024):.1f} MB",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        progress_dialog = QProgressDialog(f"Downloading {app.name}...", "", 0, 100, self.window)
        progress_dialog.setCancelButton(None)
        progress_dialog.setWindowTitle(f"Download {app.name}")
        progress_dialog.show()

        def task(report):
            return download_installer(app, progress=report)

        def success(path):
            progress_dialog.close()
            response = QMessageBox.question(
                self.window,
                f"Install {app.name}",
                f"The verified {app.name} installer is ready. Install now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if response == QMessageBox.StandardButton.Yes:
                try:
                    subprocess.Popen([str(path)])
                except OSError as error:
                    QMessageBox.warning(
                        self.window,
                        f"Install {app.name}",
                        f"Could not start the installer.\n\n{error}\n\n{path}",
                    )

        def failure(message):
            progress_dialog.close()
            response = QMessageBox.warning(
                self.window,
                f"Download {app.name}",
                f"{message}\n\nChoose Retry to try again.",
                QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Retry,
            )
            if response == QMessageBox.StandardButton.Retry:
                QTimer.singleShot(0, lambda: self._install(app))

        handle = self._run(task, success, failure, with_progress=True)

        def update(received: int, total: int) -> None:
            if total > 0:
                progress_dialog.setValue(max(0, min(100, int(received * 100 / total))))

        handle.progress.connect(update)
