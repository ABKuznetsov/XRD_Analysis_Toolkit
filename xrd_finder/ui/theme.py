from __future__ import annotations

from pathlib import Path
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QWidget


def is_dark_theme(widget: QWidget) -> bool:
    # Read the application's native palette, not a widget palette already
    # polished by Finder's stylesheet. The latter would lock the old theme.
    app = QApplication.instance()
    palette = app.palette() if app is not None else widget.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


SEMANTIC_COLORS = dict(match='#e5f0fc', gain='#e2f4eb', warning='#fff0cf',
                       error='#fce8ed', semantic_text='#202124')


def theme_colors(dark: bool = False, widget: QWidget | None = None) -> dict[str, str]:
    if widget is not None:
        dark = is_dark_theme(widget)
    if dark:
        return dict(bg='#10141a', panel='#161c24', alt='#1c2430', text='#e3eaf2',
                    muted='#9aaabb', border='#303c4b', selected='#173e38', input='#111821',
                    header='#1c2632', hover='#242f3d', link='#6cdac1', accent='#087f69',
                    cell_border='#415166', **SEMANTIC_COLORS)
    return dict(bg='#f4f7fa', panel='#ffffff', alt='#f7f9fc', text='#334155',
                muted='#64748b', border='#dce3eb', selected='#e0f2ed', input='#ffffff',
                header='#edf2f7', hover='#edf2f7', link='#087f69', accent='#087f69',
                cell_border='#c3cfdc', **SEMANTIC_COLORS)


def _asset(name: str) -> str:
    return (Path(__file__).parent/'assets'/name).resolve().as_posix()


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def glass_button_style(
    background: str,
    border: str,
    color: str = "#ffffff",
    padding: str = "7px 14px",
    pressed_padding: str = "8px 14px 6px 14px",
    border_radius: int = 7,
) -> str:
    # Keep the legacy helper signature for callers; all commands now use a
    # restrained flat treatment, without glossy gradients or a shifting label.
    red, green, blue = _hex_to_rgb(background)
    hover = f'rgb({min(red+12,255)},{min(green+12,255)},{min(blue+12,255)})'
    pressed = f'rgb({max(red-10,0)},{max(green-10,0)},{max(blue-10,0)})'
    return (
        "QPushButton {"
        f"background: {background};"
        f"border: 1px solid {border}; color: {color};"
        f"border-radius: {border_radius}px; padding: {padding}; font-weight: 600;"
        "}"
        "QPushButton:hover {"
        f"background: {hover};"
        f"border-color: {border};"
        "}"
        "QPushButton:pressed {"
        f"background: {pressed};"
        f"padding: {padding};"
        "}"
        "QPushButton:disabled {"
        "background-color: rgba(100, 116, 139, 0.45); border-color: rgba(148, 163, 184, 0.35); color: rgba(241, 245, 249, 0.70);"
        "}"
    )


def command_button_style(background: str, border: str, color: str = "#ffffff") -> str:
    return glass_button_style(background, border, color)


def action_button_style(background: str, border: str) -> str:
    return glass_button_style(background, border, padding="6px 12px", pressed_padding="7px 12px 5px 12px")


SEARCH_MODE_COLORS = {
    'search': ('#087f69', '#119b7f', '#ffffff'),
    'auto': ('#e0ad24', '#f1c34e', '#202124'),
    'peaks': ('#2563c5', '#4a8aeb', '#ffffff'),
}


def search_mode_button_style(selector: str, *, checked: bool = False) -> str:
    suffix = ':checked' if checked else ''
    return ''.join(
        f'{selector}[searchMode="{mode}"]{suffix} {{ background: {background}; '
        f'color: {foreground}; border-color: {border}; font-weight: 600; }}'
        for mode, (background, border, foreground) in SEARCH_MODE_COLORS.items()
    )


def window_style(dark: bool = False) -> str:
    c = theme_colors(dark)
    caret = _asset('chevron-light.svg' if dark else 'chevron-dark.svg')
    up_caret = _asset('chevron-up-light.svg' if dark else 'chevron-up-dark.svg')
    tick, partial = _asset('check.svg'), _asset('partial.svg')
    return f'''
        QDialog {{ background: {c['bg']}; color: {c['text']}; font-size: 13px; }}
        QWidget {{ color: {c['text']}; }}
        QLabel {{ background: transparent; }}
        QLabel[uiRole="sectionTitle"] {{ color: {c['text']}; font-weight: 600; padding: 4px 0; }}
        QLabel[uiRole="muted"], QLabel#processingPlaceholder {{ color: {c['muted']}; }}
        QWidget#projectSidebar, QWidget#compositionElements, QWidget#compositionControls {{
            background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 9px;
        }}
        QWidget#finderPlotControlBar {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QLabel#cursorReadout {{ background: {c['input']}; color: {c['muted']}; border: 0;
            border-radius: 5px; padding: 4px 7px; font-size: 12px; }}
        QLabel#backgroundStatus {{ color: {c['muted']}; background: transparent; padding: 3px 8px; }}
        QTabWidget::pane {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QTabBar::tab {{ background: transparent; color: {c['muted']}; border: 0;
            border-bottom: 2px solid transparent; padding: 9px 12px; margin-right: 2px; }}
        QTabBar::tab:selected {{ background: {c['panel']}; color: {c['text']};
            border-bottom: 2px solid #22aa8b; font-weight: 600; }}
        QTabBar::tab:hover:!selected {{ background: {c['hover']}; color: {c['text']}; }}
        QToolButton#editLayoutButton:checked {{ background: #a62e45; color: #ffffff; border: 1px solid #d05b70; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {{ background: {c['input']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: 6px; min-height: 24px; padding: 3px 8px; selection-background-color: {c['selected']}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus {{ border-color: #22aa8b; }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateTimeEdit:disabled {{ color: {c['muted']}; background: {c['bg']}; }}
        QComboBox {{ padding-right: 23px; }}
        QComboBox::drop-down {{ width: 21px; border: 0; }}
        QComboBox::down-arrow {{ image: url("{caret}"); width: 11px; height: 11px; }}
        QSpinBox, QDoubleSpinBox, QDateTimeEdit {{ padding-right: 27px; }}
        QSpinBox::up-button, QDoubleSpinBox::up-button, QDateTimeEdit::up-button {{
            subcontrol-origin: border; subcontrol-position: top right; width: 22px;
            border-left: 1px solid {c['border']}; border-bottom: 1px solid {c['border']};
            border-top-right-radius: 5px; background: {c['alt']}; }}
        QSpinBox::down-button, QDoubleSpinBox::down-button, QDateTimeEdit::down-button {{
            subcontrol-origin: border; subcontrol-position: bottom right; width: 22px;
            border-left: 1px solid {c['border']}; border-bottom-right-radius: 5px; background: {c['alt']}; }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateTimeEdit::up-arrow {{
            image: url("{up_caret}"); width: 10px; height: 10px; }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateTimeEdit::down-arrow {{
            image: url("{caret}"); width: 10px; height: 10px; }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QDateTimeEdit::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover, QDateTimeEdit::down-button:hover {{ background: {c['hover']}; }}
        QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed, QDateTimeEdit::up-button:pressed,
        QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed, QDateTimeEdit::down-button:pressed {{ background: {c['selected']}; }}
        QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['selected']}; }}
        QPushButton, QToolButton {{ background: {c['alt']}; color: {c['text']}; border: 1px solid {c['border']};
            border-radius: 6px; padding: 6px 10px; font-weight: 500; }}
        QPushButton:hover, QToolButton:hover {{ background: {c['hover']}; border-color: #22aa8b; }}
        QPushButton:pressed, QToolButton:pressed {{ background: {c['selected']}; }}
        QPushButton:focus, QToolButton:focus {{ border-color: #22aa8b; }}
        QPushButton:disabled, QToolButton:disabled {{ color: {c['muted']}; background: {c['bg']}; }}
        QPushButton[uiRole="primary"] {{ background: #087f69; color: #ffffff; border-color: #119b7f; font-weight: 600; }}
        QPushButton[uiRole="primary"]:hover {{ background: #09967b; }}
        QCheckBox {{ spacing: 6px; padding: 2px 0; }}
        QCheckBox::indicator, QTreeView::indicator {{ width: 14px; height: 14px; border: 1px solid {c['muted']};
            border-radius: 4px; background: {c['input']}; }}
        QCheckBox::indicator:checked, QTreeView::indicator:checked {{ background: #087f69;
            border-color: #119b7f; image: url("{tick}"); }}
        QCheckBox::indicator:indeterminate, QTreeView::indicator:indeterminate {{ background: #087f69;
            border-color: #119b7f; image: url("{partial}"); }}
        QCheckBox::indicator:hover {{ border-color: #22aa8b; }}
        QCheckBox:disabled {{ color: {c['muted']}; }}
        QTreeWidget, QTableView, QTableWidget, QTextEdit, QPlainTextEdit {{ background: {c['panel']}; alternate-background-color: {c['alt']};
            color: {c['text']}; border: 1px solid {c['border']}; border-radius: 7px;
            gridline-color: {c['cell_border']}; selection-background-color: {c['selected']}; outline: 0; }}
        QTreeWidget#projectTree {{ border: 0; background: transparent; }}
        QTreeWidget::item {{ padding: 5px 3px; }}
        QTableView::item, QTableWidget::item {{ padding: 5px 7px; border-bottom: 1px solid {c['cell_border']}; border-right: 1px solid {c['cell_border']}; }}
        QTreeWidget::item:selected, QTableView::item:selected, QTableWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
        QHeaderView::section {{ background: {c['header']}; color: {c['muted']}; border: 0;
            border-bottom: 1px solid {c['cell_border']}; border-right: 1px solid {c['cell_border']}; padding: 8px 7px; font-size: 12px; font-weight: 600; }}
        QTableCornerButton::section {{ background: {c['header']}; border: 0; }}
        QSplitter::handle {{ background: transparent; }}
        QSplitter::handle:hover {{ background: {c['border']}; }}
        QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: #159c80; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: #22aa8b; width: 13px; margin: -5px 0; border-radius: 6px; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0 2px; }}
        QScrollBar::handle {{ background: {c['border']}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
        QScrollBar::handle:hover {{ background: {c['muted']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        QMenu {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
        QMenu::item {{ padding: 7px 22px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {c['selected']}; }}
        QMenu::item:disabled {{ color: {c['muted']}; }}
        QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
    ''' + search_mode_button_style('QPushButton')


def settings_panel_style(dark: bool = False) -> str:
    c = theme_colors(dark)
    return f'''
        QScrollArea#plotViewSettings, QWidget#processingBody, QWidget#plotViewSettingsBody {{ background: {c['panel']}; border: 0; }}
        QWidget#viewSection, QWidget#axisCard {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QToolButton#viewSectionHeader, QToolButton#axisCardTitle {{ background: {c['alt']}; color: {c['text']};
            border: 0; border-radius: 7px; padding: 9px 10px; font-weight: 600; text-align: left; }}
        QToolButton#viewSectionHeader:hover, QToolButton#axisCardTitle:hover {{ background: {c['hover']}; }}
        QWidget#viewSectionContent {{ background: transparent; }}
        QLabel#activeProfileLabel {{ background: {c['input']}; border: 1px solid {c['border']};
            border-radius: 6px; padding: 8px; font-weight: 600; }}
        QLabel#lineGroupTitle {{ color: {c['muted']}; padding: 8px 2px 2px; font-weight: 600; }}
        QLabel#processingPlaceholder {{ color: {c['muted']}; padding: 8px; }}
    '''


def preprocessing_panel_style(dark: bool = False) -> str:
    c = theme_colors(dark)
    return window_style(dark) + f'QWidget#preprocessingPanel {{ background: {c["panel"]}; border: 0; }}'
