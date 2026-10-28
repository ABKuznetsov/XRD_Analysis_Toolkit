"""Keep non-native settings dialogs usable in compact/high-DPI workspaces."""
from PySide6.QtWidgets import QDialog, QScrollArea, QVBoxLayout, QWidget

def scrollable_dialog_body(dialog):
    content = QWidget(dialog)
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(content)
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(6, 6, 6, 6)
    outer.addWidget(scroll)
    return QVBoxLayout(content)

class ScreenBoundDialog(QDialog):

    def showEvent(self, event):
        parent = self.parentWidget()
        density = getattr(parent.window(), '_ui_density_factor', 1.0) if parent is not None else 1.0
        if getattr(self, '_dialog_density_factor', None) != density:
            from xrd_finder.ui.ui_density import UiDensity
            if not hasattr(self, '_dialog_density'):
                self._dialog_density = UiDensity()
                self._dialog_original_size = self.size()
                self._dialog_original_minimum = self.minimumSize()
            self._dialog_density_factor = density
            self._ui_density_factor = density
            self._dialog_density.apply(self, density)
            self.setMinimumSize(round(self._dialog_original_minimum.width() * density), round(self._dialog_original_minimum.height() * density))
            self.resize(round(self._dialog_original_size.width() * density), round(self._dialog_original_size.height() * density))
        available = self.screen().availableGeometry()
        parent = self.parentWidget()
        width, height = (available.width() - 24, available.height() - 48)
        if parent is not None:
            width = min(width, parent.window().width() - 16)
            height = min(height, parent.window().height() - 40)
        width, height = (max(320, width), max(240, height))
        self.setMinimumSize(min(self.minimumWidth(), width), min(self.minimumHeight(), height))
        self.resize(min(self.width(), width), min(self.height(), height))
        super().showEvent(event)
