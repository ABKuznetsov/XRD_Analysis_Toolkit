from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import subprocess

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.services.toolkit_catalog import ToolkitApplication


def _announcement_key(app: ToolkitApplication) -> str:
    return f"toolkit/announcements/{app.app_id}"


def announcement_seen(settings: QSettings, app: ToolkitApplication) -> bool:
    value = settings.value(_announcement_key(app), 0)
    try:
        stored_revision = int(value)
    except (TypeError, ValueError):
        stored_revision = 0
    return stored_revision >= app.announcement_revision


def mark_announcement_seen(settings: QSettings, app: ToolkitApplication) -> None:
    settings.setValue(_announcement_key(app), app.announcement_revision)
    settings.sync()


def launch_installer_with_confirmation(
    parent: QWidget | None,
    app: ToolkitApplication,
    installer_path: Path,
    *,
    process_launcher: Callable[[list[str]], object] = subprocess.Popen,
) -> bool:
    response = QMessageBox.question(
        parent,
        f"Install {app.name}",
        f"The verified {app.name} {app.version} installer is ready.\n\n"
        "Close the application if requested by the installer. Install now?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if response != QMessageBox.StandardButton.Yes:
        return False
    process_launcher([str(installer_path)])
    return True


class ToolkitCatalogDialog(QDialog):
    install_requested = Signal(object)
    not_now_requested = Signal(object)

    def __init__(
        self,
        applications: Iterable[ToolkitApplication],
        *,
        announcement: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.applications = tuple(applications)
        self.install_buttons: dict[str, QPushButton] = {}
        self.not_now_button: QPushButton | None = None
        self.setWindowTitle("More XRD tools")
        self.setModal(True)
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
            text_layout = QVBoxLayout()
            name = QLabel(f"{app.name}  {app.version}")
            name.setStyleSheet("font-weight: 700;")
            description = QLabel(app.description)
            description.setWordWrap(True)
            text_layout.addWidget(name)
            text_layout.addWidget(description)
            card_layout.addLayout(text_layout, 1)
            button = QPushButton("Install")
            button.clicked.connect(
                lambda _checked=False, selected=app: self.install_requested.emit(selected)
            )
            self.install_buttons[app.app_id] = button
            card_layout.addWidget(button)
            layout.addWidget(card)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if announcement:
            self.not_now_button = QPushButton("Not now")
            self.not_now_button.clicked.connect(self._not_now)
            buttons.addWidget(self.not_now_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _not_now(self) -> None:
        for app in self.applications:
            self.not_now_requested.emit(app)
        self.reject()
