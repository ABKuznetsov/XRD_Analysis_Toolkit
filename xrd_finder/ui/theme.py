from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget


def is_dark_theme(widget: QWidget) -> bool:
    color = widget.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _glass_gradient(color: str, top_alpha: int = 230, bottom_alpha: int = 178) -> str:
    red, green, blue = _hex_to_rgb(color)
    return (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 rgba(255, 255, 255, 86), "
        f"stop:0.18 rgba({min(red + 42, 255)}, {min(green + 42, 255)}, {min(blue + 42, 255)}, {top_alpha}), "
        f"stop:1 rgba({max(red - 18, 0)}, {max(green - 18, 0)}, {max(blue - 18, 0)}, {bottom_alpha}))"
    )


def glass_button_style(
    background: str,
    border: str,
    color: str = "#ffffff",
    padding: str = "7px 14px",
    pressed_padding: str = "8px 14px 6px 14px",
    border_radius: int = 7,
) -> str:
    base = _glass_gradient(background)
    hover = _glass_gradient(background, top_alpha=248, bottom_alpha=205)
    pressed = _glass_gradient(background, top_alpha=190, bottom_alpha=240)
    return (
        "QPushButton {"
        f"background: {base};"
        f"border: 1px solid {border}; color: {color};"
        f"border-radius: {border_radius}px; padding: {padding}; font-weight: 700;"
        "}"
        "QPushButton:hover {"
        f"background: {hover};"
        "border-color: rgba(255, 255, 255, 0.72);"
        "}"
        "QPushButton:pressed {"
        f"background: {pressed};"
        f"padding: {pressed_padding};"
        "}"
        "QPushButton:disabled {"
        "background-color: rgba(100, 116, 139, 0.45); border-color: rgba(148, 163, 184, 0.35); color: rgba(241, 245, 249, 0.70);"
        "}"
    )


def command_button_style(background: str, border: str, color: str = "#ffffff") -> str:
    return glass_button_style(background, border, color)


def action_button_style(background: str, border: str) -> str:
    return glass_button_style(background, border, padding="6px 12px", pressed_padding="7px 12px 5px 12px")


def window_style(dark: bool = False) -> str:
    if dark:
        bg = "#1f2328"
        panel = "#252a31"
        alt = "#2c323a"
        text = "#eef2f7"
        border = "#46515d"
        selected = "#315f92"
        tab = "#303740"
        tab_selected = "#252a31"
        input_bg = "#20252b"
        header = "#333b45"
    else:
        bg = "#f4f6f8"
        panel = "#ffffff"
        alt = "#f3f6fa"
        text = "#111827"
        border = "#cbd5e1"
        selected = "#dbeafe"
        tab = "#e5e7eb"
        tab_selected = "#ffffff"
        input_bg = "#ffffff"
        header = "#e5e7eb"
    return (
        f"QDialog {{ background: {bg}; color: {text}; }}"
        f"QWidget {{ color: {text}; }}"
        f"QLabel {{ color: {text}; }}"
        f"QCheckBox {{ color: {text}; }}"
        f"QTabWidget::pane {{ border: 1px solid {border}; background: {panel}; }}"
        f"QTabBar::tab {{ background: {tab}; color: {text}; padding: 6px 10px; }}"
        f"QTabBar::tab:selected {{ background: {tab_selected}; color: {text}; }}"
        f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {input_bg}; color: {text}; border: 1px solid {border}; padding: 3px; }}"
        f"QTreeWidget, QTableWidget, QTextEdit, QPlainTextEdit {{ background: {panel}; alternate-background-color: {alt}; color: {text}; border: 1px solid {border}; gridline-color: {border}; }}"
        f"QTreeWidget::item {{ color: {text}; }}"
        f"QTableWidget::item {{ color: {text}; }}"
        f"QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {selected}; color: {text}; }}"
        f"QHeaderView::section {{ background: {header}; color: {text}; border: 1px solid {border}; padding: 4px; }}"
        f"QToolButton {{ background: {input_bg}; color: {text}; border: 1px solid {border}; padding: 4px 8px; }}"
        f"QPushButton {{ color: {text}; }}"
        f"QSplitter::handle {{ background: {border}; }}"
        f"QSplitter::handle:hover {{ background: {selected}; }}"
    )


def preprocessing_panel_style(dark: bool = False) -> str:
    if dark:
        panel = "#202124"
        text = "#f1f3f4"
        input_bg = "#2b2f34"
        button_bg = "#33383e"
        border = "#4a5057"
        hover = "#4aa3df"
        slider = "#4a5057"
        tick = "#8c96a3"
    else:
        panel = "#ffffff"
        text = "#111827"
        input_bg = "#f8fafc"
        button_bg = "#e5e7eb"
        border = "#cbd5e1"
        hover = "#2563eb"
        slider = "#d1d5db"
        tick = "#6b7280"
    return (
        f"QWidget#preprocessingPanel {{ background-color: {panel}; border: 1px solid {border}; border-radius: 6px; }}"
        f"QLabel {{ color: {text}; }}"
        f"QComboBox {{ background: {input_bg}; color: {text}; border: 1px solid {border}; padding: 3px; }}"
        f"QPushButton {{ background: {button_bg}; color: {text}; border: 1px solid {border}; border-radius: 4px; padding: 5px 12px; }}"
        f"QPushButton:hover {{ border-color: {hover}; }}"
        f"QSlider::groove:horizontal {{ height: 5px; background: {slider}; border-radius: 2px; }}"
        f"QSlider::handle:horizontal {{ width: 15px; margin: -5px 0; border-radius: 7px; background: {hover}; }}"
        f"QSlider::tick:horizontal {{ background: {tick}; width: 1px; }}"
    )
