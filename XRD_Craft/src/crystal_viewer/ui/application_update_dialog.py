from __future__ import annotations

from pathlib import Path
import subprocess

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from crystal_viewer import __version__
from crystal_viewer.services.application_updates import (
    ApplicationUpdate,
    download_update,
    fetch_update_manifest,
    parse_update_manifest,
)
from crystal_viewer.ui.toolkit_catalog_dialog import BackgroundTaskHandle


class ApplicationUpdateDialog(QDialog):
    download_requested = Signal()

    def __init__(self, update: ApplicationUpdate, parent=None) -> None:
        super().__init__(parent)
        self.update = update
        self.setWindowTitle("CRAFT update available")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        heading = QLabel(f"XRD CRAFT {update.version} is available")
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        notes = QLabel(update.release_notes)
        notes.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(notes)
        controls = QHBoxLayout()
        controls.addStretch(1)
        later = QPushButton("Later")
        later.clicked.connect(self.reject)
        self.download_button = QPushButton("Download update")
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self._request_download)
        controls.addWidget(later)
        controls.addWidget(self.download_button)
        layout.addLayout(controls)

    def _request_download(self) -> None:
        self.download_requested.emit()
        self.accept()


class ApplicationUpdateController(QObject):
    update_available = Signal(object)
    check_failed = Signal(str)
    download_progress = Signal(int, int)
    installer_ready = Signal(Path)

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self._tasks: set[BackgroundTaskHandle] = set()

    def _run(self, task, success, failure, *, with_progress=False) -> BackgroundTaskHandle:
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

    def check_in_background(self, *, interactive: bool = False) -> None:
        self.window.statusBar().showMessage("Checking for CRAFT updates...")

        def task():
            payload = fetch_update_manifest()
            return parse_update_manifest(payload, current_version=__version__)

        def success(update: ApplicationUpdate | None):
            self.window.statusBar().showMessage("Ready")
            if update is None:
                if interactive:
                    QMessageBox.information(
                        self.window,
                        "CRAFT updates",
                        f"XRD CRAFT {__version__} is up to date.",
                    )
                return
            self.update_available.emit(update)
            dialog = ApplicationUpdateDialog(update, self.window)
            dialog.download_requested.connect(lambda: self.download_update(update))
            dialog.exec()

        def failure(message: str):
            self.check_failed.emit(message)
            self.window.statusBar().showMessage(f"CRAFT update check: {message}")
            if interactive:
                QMessageBox.warning(self.window, "CRAFT updates", message)

        self._run(task, success, failure)

    def download_update(self, update: ApplicationUpdate) -> None:
        progress_dialog = QProgressDialog(
            f"Downloading XRD CRAFT {update.version}...",
            "",
            0,
            100,
            self.window,
        )
        progress_dialog.setCancelButton(None)
        progress_dialog.setWindowTitle("CRAFT update")
        progress_dialog.show()

        def task(report):
            return download_update(update, progress=report)

        def success(installer_path):
            progress_dialog.close()
            self.installer_ready.emit(Path(installer_path))
            response = QMessageBox.question(
                self.window,
                "Install CRAFT update",
                f"The verified XRD CRAFT {update.version} installer is ready.\n\n"
                "Install now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if response != QMessageBox.StandardButton.Yes:
                return
            try:
                subprocess.Popen([str(installer_path)])
            except OSError as error:
                QMessageBox.warning(
                    self.window,
                    "Install CRAFT update",
                    f"Could not start the installer.\n\n{error}\n\n{installer_path}",
                )

        def failure(message):
            progress_dialog.close()
            response = QMessageBox.warning(
                self.window,
                "CRAFT update download",
                f"{message}\n\nChoose Retry to try again.",
                QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Retry,
            )
            if response == QMessageBox.StandardButton.Retry:
                QTimer.singleShot(0, lambda: self.download_update(update))

        handle = self._run(task, success, failure, with_progress=True)

        def progress(received: int, total: int) -> None:
            self.download_progress.emit(received, total)
            if total > 0:
                progress_dialog.setValue(max(0, min(100, int(received * 100 / total))))

        handle.progress.connect(progress)
