"""Keep non-native settings dialogs usable in compact/high-DPI workspaces."""
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import QDialog, QScrollArea, QVBoxLayout, QWidget

def scrollable_dialog_body(dialog, *, body_name=''):
    content = QWidget(dialog)
    if body_name:
        content.setObjectName(body_name)
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(content)
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(6, 6, 6, 6)
    outer.addWidget(scroll)
    return QVBoxLayout(content)

class ScreenBoundDialog(QDialog):

    def _content_size(self, maximum_width, maximum_height):
        """Include scroll contents: QScrollArea's own hint is intentionally capped."""
        self.ensurePolished()
        if self.layout() is not None:
            self.layout().activate()
        hint = self.sizeHint().expandedTo(self.minimumSize()).expandedTo(self.size())
        for area in self.findChildren(QScrollArea):
            if area.window() is not self or area.widget() is None:
                continue
            ancestor = area.parentWidget()
            while ancestor is not None and ancestor is not self and not isinstance(ancestor, QScrollArea):
                ancestor = ancestor.parentWidget()
            if ancestor is not self:
                continue  # Only the outer scroll area contributes to the window.
            body = area.widget()
            body.ensurePolished()
            body_layout = body.layout()
            if body_layout is not None:
                body_layout.activate()
            body_hint = body.sizeHint().expandedTo(body.minimumSizeHint()).expandedTo(body.minimumSize())
            chrome = self.sizeHint() - area.sizeHint() + QSize(2 * area.frameWidth() + 2, 2 * area.frameWidth() + 2)
            width = min(maximum_width, max(hint.width(), body_hint.width() + chrome.width()))
            if body_layout is not None and body_layout.hasHeightForWidth():
                # Keep the current preferred height too: an already visible
                # scrollbar narrows wrapping labels until enough height is
                # available to hide it. Using only the wider future viewport
                # can otherwise leave that scrollbar permanently visible.
                body_hint.setHeight(max(body_hint.height(),
                    body_layout.totalHeightForWidth(max(1, width - chrome.width()))))
            required = body_hint + chrome
            if required.height() > maximum_height:
                required.setWidth(required.width() + area.verticalScrollBar().sizeHint().width())
            hint = hint.expandedTo(required)
        return hint

    def showEvent(self, event):
        parent = self.parentWidget()
        bounds = getattr(self, '_bounds_window', None)
        if bounds is None and parent is not None:
            bounds = parent.window()
        density = getattr(bounds, '_ui_density_factor', 1.0)
        density_changed = getattr(self, '_dialog_density_factor', None) != density
        if density_changed:
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
        if bounds is not None:
            width = min(width, bounds.width() - 16)
            height = min(height, bounds.height() - 40)
        width, height = (max(320, width), max(240, height))
        self.setMinimumSize(min(self.minimumWidth(), width), min(self.minimumHeight(), height))
        size = (self._content_size(width, height) if density_changed or not getattr(self, '_dialog_content_fitted', False)
                else self.size())
        self.resize(min(size.width(), width), min(size.height(), height))
        self._dialog_content_fitted = True
        # Resizing after Qt chose an initial position must not push the frame
        # outside this monitor's work area (including its menu bar and Dock).
        frame = self.frameGeometry()
        left = max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
        top = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
        self.move(self.pos() + QPoint(left - frame.left(), top - frame.top()))
        super().showEvent(event)
