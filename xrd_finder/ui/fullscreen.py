"""Native full-screen mode with the platform shortcut and reversible window state."""
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QKeySequence


class FullscreenController(QObject):
    def __init__(self, window, menu):
        super().__init__(window)
        self.window = window
        self._previous_state = Qt.WindowState.WindowNoState
        if sys.platform == 'darwin':
            # QDialog's type bits survive `flags | Qt.Window`. Cocoa creates an
            # auxiliary NSPanel for that type and excludes it from fullscreen
            # primary windows. Replace the type, preserving the other hints.
            flags = window.windowFlags() & ~Qt.WindowType.WindowType_Mask
            window.setWindowFlags(flags | Qt.WindowType.Window
                                  | Qt.WindowType.WindowFullscreenButtonHint)
        self.action = QAction('Full screen', window)
        self.action.setCheckable(True)
        self.action.setShortcuts([QKeySequence('Meta+Ctrl+F')] if sys.platform == 'darwin'
                                 else QKeySequence.keyBindings(QKeySequence.StandardKey.FullScreen))
        self.action.setToolTip('Fill the screen without the window frame. Press Esc to return.')
        self.action.toggled.connect(self.set_fullscreen)
        window.addAction(self.action)
        menu.addAction(self.action)
        window.installEventFilter(self)
        self._sync_action()

    def set_fullscreen(self, enabled):
        if enabled and not self.window.isFullScreen():
            self.window.showFullScreen()
        elif not enabled and self.window.isFullScreen():
            if self._previous_state & Qt.WindowState.WindowMaximized:
                self.window.showMaximized()
            else:
                self.window.showNormal()

    def _sync_action(self):
        blocked = self.action.blockSignals(True)
        self.action.setChecked(self.window.isFullScreen())
        self.action.blockSignals(blocked)

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Type.WindowStateChange:
            if self.window.isFullScreen() and not event.oldState() & Qt.WindowState.WindowFullScreen:
                self._previous_state = event.oldState()
            self._sync_action()
        return False
