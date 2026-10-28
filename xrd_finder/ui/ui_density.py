"""Scale native widget metrics from one reference density, without scaling data."""
import re
from PySide6.QtCore import QMargins, QSize, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QToolButton, QWidget, QLayout, QGridLayout, QFormLayout
_PIXEL = re.compile('(?<![\\w.])([0-9]+(?:\\.[0-9]+)?)px')

def scaled_style(style, factor):
    return _PIXEL.sub(lambda match: f'{(max(1, round(float(match.group(1)) * factor)) if float(match.group(1)) else 0)}px', style)

class UiDensity:

    def __init__(self):
        self._styles = {}
        self._metrics = {}
        self._layouts = {}
        self._fonts = {}
        self._tables = {}
        self._grid_spacings = {}

    def apply(self, root, factor):
        excluded = {getattr(root, name, None) for name in ('match_plot', 'plot_canvas', 'plot_area', 'center', 'center_splitter', 'candidate_panel', 'cursor_status_panel', '_workspace_strip', 'main_splitter')}
        controls = getattr(getattr(root, 'cursor_status_panel', None), '_controls', None)
        excluded.add(controls)
        plot = getattr(root, 'match_plot', None)
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            if plot is not None and (widget is plot or plot.isAncestorOf(widget)):
                continue
            style = widget.styleSheet()
            if style:
                cached = self._styles.get(widget)
                base = style if cached is None or style != cached[1] else cached[0]
                scaled = scaled_style(base, factor)
                if scaled != style:
                    widget.setStyleSheet(scaled)
                self._styles[widget] = (base, scaled)
            if widget is not root and widget not in excluded:
                if widget not in self._metrics:
                    self._metrics[widget] = (widget.minimumSize(), widget.maximumSize())
                minimum, maximum = self._metrics[widget]
                widget.setMinimumSize(round(minimum.width() * factor), round(minimum.height() * factor))
                widget.setMaximumSize(*(round(value * factor) if value < 16777215 else value for value in (maximum.width(), maximum.height())))
                if isinstance(widget, QToolButton):
                    widget.setIconSize(QSize(max(8, round(20 * factor)), max(8, round(20 * factor))))
            layout = widget.layout()
            if layout is not None and (widget not in excluded or widget is controls):
                if layout not in self._layouts:
                    margins = layout.contentsMargins()
                    self._layouts[layout] = (tuple((margins.left(), margins.top(), margins.right(), margins.bottom())), layout.spacing())
                margins, spacing = self._layouts[layout]
                layout.setContentsMargins(*(round(value * factor) for value in margins))
                if spacing >= 0:
                    layout.setSpacing(round(spacing * factor))
            if isinstance(widget, QAbstractItemView) and hasattr(widget, 'verticalHeader'):
                if widget not in self._tables:
                    self._tables[widget] = (widget.verticalHeader().defaultSectionSize(), [widget.columnWidth(i) for i in range(widget.model().columnCount())])
                height, widths = self._tables[widget]
                widget.verticalHeader().setDefaultSectionSize(max(10, round(height * factor)))
                widget.horizontalHeader().setMinimumSectionSize(max(6, round(20 * factor)))
                if callable(getattr(widget, '_resize_columns', None)):
                    widget._resize_columns()
                else:
                    for index, width in enumerate(widths):
                        if widget.horizontalHeader().sectionResizeMode(index) != QHeaderView.ResizeMode.Stretch:
                            widget.setColumnWidth(index, max(6, round(width * factor)))
        managed = {getattr(root, name, None) for name in ('match_plot', 'plot_canvas', 'cursor_status_panel')}
        skipped = {widget.layout() for widget in managed if widget is not None and widget.layout() is not None}
        for layout in root.findChildren(QLayout):
            if layout in skipped:
                continue
            if isinstance(layout, (QGridLayout, QFormLayout)):
                if layout not in self._grid_spacings:
                    self._grid_spacings[layout] = (layout.horizontalSpacing(), layout.verticalSpacing())
                horizontal, vertical = self._grid_spacings[layout]
                if horizontal >= 0:
                    layout.setHorizontalSpacing(max(0, round(horizontal * factor)))
                if vertical >= 0:
                    layout.setVerticalSpacing(max(0, round(vertical * factor)))
            if layout not in self._layouts:
                margins = layout.contentsMargins()
                self._layouts[layout] = ((margins.left(), margins.top(), margins.right(), margins.bottom()), layout.spacing())
            margins, spacing = self._layouts[layout]
            layout.setContentsMargins(*(round(value * factor) for value in margins))
            if spacing >= 0 and (not isinstance(layout, (QGridLayout, QFormLayout))):
                layout.setSpacing(max(0, round(spacing * factor)))
