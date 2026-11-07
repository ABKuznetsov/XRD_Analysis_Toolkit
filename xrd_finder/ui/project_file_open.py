"""Handle Finder/Dock document-open events before and after the window is ready."""
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer


class ProjectFileOpenHandler(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.window = None
        self._paths = []
        self._opening = False
        app.installEventFilter(self)

    def set_window(self, window):
        self.window = window
        QTimer.singleShot(0, self._open_next)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.FileOpen:
            return False
        path = event.file() or event.url().toLocalFile()
        if not path or Path(path).suffix.lower() != '.xpff':
            return False
        path = str(Path(path).expanduser().resolve())
        if path not in self._paths:
            self._paths.append(path)
        event.accept()
        QTimer.singleShot(0, self._open_next)
        return True

    def _open_next(self):
        if self.window is None or self._opening or not self._paths:
            return
        path = self._paths.pop(0)
        self._opening = True
        try:
            current = getattr(self.window.project, 'root_path', '')
            if not current or Path(current).expanduser().resolve() != Path(path):
                self.window._open_project_path(path)
            self.window.setWindowState(self.window.windowState() & ~Qt.WindowState.WindowMinimized)
            self.window.raise_()
            self.window.activateWindow()
        finally:
            self._opening = False
        if self._paths:
            QTimer.singleShot(0, self._open_next)
