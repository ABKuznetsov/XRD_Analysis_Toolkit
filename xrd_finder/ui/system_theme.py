"""Follow OS light/dark mode while retaining Finder's own widget styling."""
from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from xrd_finder.ui.theme import is_dark_theme


class SystemThemeObserver(QObject):
    changed = Signal(bool, bool)

    def __init__(self, window):
        super().__init__(window)
        self._dark = is_dark_theme(window)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh)
        app = QApplication.instance()
        app.installEventFilter(self)
        app.styleHints().colorSchemeChanged.connect(self._schedule)

    def _schedule(self, *_args):
        # Wait until Qt has installed the palette belonging to the new mode.
        self._timer.start(0)

    def eventFilter(self, watched, event):
        if watched is QApplication.instance() and event.type() == QEvent.Type.ApplicationPaletteChange:
            self._schedule()
        return False

    def _refresh(self):
        dark = is_dark_theme(self.parent())
        if dark != self._dark:
            previous, self._dark = self._dark, dark
            self.changed.emit(dark, previous)
