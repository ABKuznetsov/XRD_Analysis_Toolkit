from __future__ import annotations

from pathlib import Path


COLORS = {
    "window": "#edf2f7",
    "panel": "#ffffff",
    "panel_alt": "#f3f6fa",
    "input": "#f8fafc",
    "border": "#ccd6e2",
    "text": "#172033",
    "muted": "#68788b",
    "accent": "#2678c8",
    "accent_dark": "#2f80c9",
    "green": "#3ccf91",
    "orange": "#ffad5c",
}


def application_style() -> str:
    c = COLORS
    checkmark = (Path(__file__).with_name("assets") / "checkmark.svg").as_posix()
    return f"""
    QMainWindow, QDialog {{
        background: {c["window"]};
        color: {c["text"]};
    }}
    QWidget {{
        color: {c["text"]};
        font-size: 13px;
    }}
    QToolBar {{
        background: {c["panel"]};
        border-bottom: 1px solid {c["border"]};
        spacing: 3px;
        padding: 2px 4px;
    }}
    QToolBar QToolButton {{
        padding: 5px 8px;
        border-radius: 6px;
    }}
    QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {{
        background: {c["panel"]};
        border: 0;
    }}
    QWidget#sidePanel, QFrame#card {{
        background: {c["panel"]};
        border: 1px solid {c["border"]};
        border-radius: 10px;
    }}
    QFrame#summaryBar {{
        background: {c["panel"]};
        border: 1px solid {c["border"]};
        border-radius: 6px;
    }}
    QFrame#dashboardCard {{
        background: {c["panel"]};
        border-left: 1px solid {c["border"]};
    }}
    QLabel#metricTitle {{
        color: {c["muted"]};
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#metricValue {{
        color: {c["text"]};
        font-size: 12px;
        font-weight: 650;
    }}
    QLabel#selectedTitle {{
        color: {c["accent"]};
        font-size: 15px;
        font-weight: 750;
    }}
    QLabel#localEnvironment {{
        background: #f7faff;
        border: 1px solid {c["border"]};
        border-radius: 7px;
        padding: 8px;
        font-size: 11px;
    }}
    QLabel#eyebrow {{
        color: {c["accent"]};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#title {{
        font-size: 21px;
        font-weight: 750;
    }}
    QLabel#muted {{
        color: {c["muted"]};
    }}
    QPushButton, QToolButton {{
        background: {c["input"]};
        border: 1px solid {c["border"]};
        border-radius: 7px;
        padding: 7px 11px;
        font-weight: 600;
    }}
    QPushButton:hover, QToolButton:hover {{
        border-color: {c["accent"]};
        background: #e7f1fb;
    }}
    QPushButton#accent {{
        background: {c["accent_dark"]};
        border-color: {c["accent"]};
        color: #ffffff;
    }}
    QListWidget, QTreeWidget, QTableWidget, QTextBrowser {{
        background: transparent;
        border: 0;
        outline: 0;
    }}
    QTableView {{
        background: {c["panel"]};
        alternate-background-color: {c["panel_alt"]};
        color: {c["text"]};
        gridline-color: {c["border"]};
        border: 1px solid {c["border"]};
        outline: 0;
        selection-background-color: #dcecfb;
        selection-color: {c["text"]};
    }}
    QTableView::item {{
        padding: 5px 7px;
    }}
    QTableView::item:selected {{
        background: #dcecfb;
        color: {c["text"]};
    }}
    QTreeView#comparisonTree, QTreeView#comparisonFrozenTree {{
        background: {c["panel"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        outline: 0;
        selection-background-color: #dcecfb;
        selection-color: {c["text"]};
    }}
    QTreeView#comparisonTree::item, QTreeView#comparisonFrozenTree::item {{
        padding: 5px 7px;
    }}
    QTreeView#comparisonTree::item:selected, QTreeView#comparisonFrozenTree::item:selected {{
        background: #dcecfb;
        color: {c["text"]};
    }}
    QListWidget::item {{
        border-radius: 7px;
        padding: 9px 10px;
        margin: 2px 0;
        color: {c["muted"]};
    }}
    QListWidget::item:selected {{
        background: #dcecfb;
        color: {c["text"]};
    }}
    QTreeWidget::item {{
        padding: 4px 2px;
    }}
    QTreeWidget::item:selected {{
        background: #dcecfb;
    }}
    QHeaderView::section {{
        background: {c["panel_alt"]};
        color: {c["muted"]};
        border: 0;
        border-bottom: 1px solid {c["border"]};
        padding: 6px;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {c["input"]};
        border: 1px solid {c["border"]};
        border-radius: 6px;
        padding: 5px 7px;
    }}
    QComboBox QAbstractItemView {{
        background: {c["panel"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        selection-background-color: #dcecfb;
        selection-color: {c["text"]};
        outline: 0;
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {c["border"]};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        margin: -5px 0;
        background: {c["accent"]};
        border-radius: 7px;
    }}
    QSplitter::handle {{
        background: {c["window"]};
    }}
    QTabWidget::pane {{
        border: 1px solid {c["border"]};
        background: {c["panel"]};
    }}
    QTabWidget QWidget {{
        background: {c["panel"]};
    }}
    QTabBar::tab {{
        background: {c["panel_alt"]};
        border: 1px solid {c["border"]};
        border-bottom: 0;
        padding: 7px 13px;
    }}
    QTabBar::tab:selected {{
        background: {c["panel"]};
        color: {c["accent"]};
        font-weight: 700;
    }}
    QTabBar#hierarchyScale::tab {{
        padding: 6px 8px;
        font-size: 11px;
    }}
    QStatusBar {{
        background: {c["panel"]};
        color: {c["muted"]};
    }}
    QMenuBar, QMenu {{
        background: {c["panel"]};
        color: {c["text"]};
    }}
    QMenu::item:selected {{
        background: #dcecfb;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        background: {c["panel"]};
        border: 1px solid {c["border"]};
        border-radius: 4px;
    }}
    QCheckBox::indicator:hover {{
        background: #e7f1fb;
        border-color: #087cc8;
    }}
    QCheckBox::indicator:checked {{
        background: #087cc8;
        border-color: #087cc8;
        image: url(\"{checkmark}\");
    }}
    QCheckBox::indicator:disabled {{
        background: {c["panel_alt"]};
        border-color: {c["border"]};
    }}
    """
