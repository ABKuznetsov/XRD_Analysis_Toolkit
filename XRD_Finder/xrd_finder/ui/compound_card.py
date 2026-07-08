from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QGridLayout,
    QHeaderView,
    QFrame,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.services.ccdc_service import extract_doi


class CompoundCardWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.labels: dict[str, QLabel] = {}
        self.atom_table: QTableWidget | None = None
        self.diffraction_table: QTableWidget | None = None
        self._build_ui()

    def set_candidate(self, candidate: Mapping[str, object] | None) -> None:
        data = dict(candidate or {})
        if "Links" not in data:
            data["Links"] = self._links_html(data)

        aliases = {
            "Name": data.get("Phase", ""),
            "Mineral Name": data.get("Phase", ""),
            "Sample Name": data.get("Entry", ""),
            "Quality": self._quality_text(data),
            "Publication": self._publication_text(data),
            "Remarks": self._remarks_text(data),
            "Source of entry": data.get("Source", "") or data.get("Qual.", ""),
            "Link to orig. entry": data.get("Entry", ""),
            "Crystal system": data.get("Crystal system", ""),
            "Cell parameters": data.get("Cell", ""),
        }
        data.update({key: value for key, value in aliases.items() if key not in data or not data.get(key)})

        for key, label in self.labels.items():
            text = str(data.get(key, "") or "")
            label.setText(text if text else "-")

        self._set_table_rows(self.atom_table, data.get("_AtomRows"))
        self._set_table_rows(self.diffraction_table, data.get("_DiffractionRows"))

    def _build_ui(self) -> None:
        colors = self._theme_colors()
        self.setStyleSheet(f"CompoundCardWidget {{ background: {colors['bg']}; color: {colors['text']}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {colors['bg']}; border: 0; }}")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {colors['bg']}; color: {colors['text']};")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Selected compound")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(self._section_style())
        layout.addWidget(title)

        layout.addWidget(self._section_title("Phase classification"))
        layout.addLayout(
            self._field_grid(
                [
                    ("Name", "Name"),
                    ("Mineral Name", "Mineral Name"),
                    ("Formula", "Formula"),
                    ("I/Ic*", "I/Ic*"),
                    ("Sample Name", "Sample Name"),
                    ("Quality", "Quality"),
                ]
            )
        )

        layout.addWidget(self._section_title("References"))
        layout.addLayout(
            self._field_grid(
                [
                    ("Publication", "Publication"),
                    ("Remarks", "Remarks / conditions"),
                    ("Source of entry", "Source of entry"),
                    ("Link to orig. entry", "Link to orig. entry"),
                ]
            )
        )
        self.labels["Links"] = QLabel("-")
        self.labels["Links"].setWordWrap(True)
        self.labels["Links"].setOpenExternalLinks(True)
        self.labels["Links"].setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.labels["Links"].setStyleSheet(
            f"color: {colors['link']}; padding: 2px 4px; background: {colors['bg']};"
        )
        layout.addWidget(self.labels["Links"])

        layout.addWidget(self._section_title("Crystal structure"))
        layout.addLayout(
            self._field_grid(
                [
                    ("Space group", "Space group"),
                    ("Crystal system", "Crystal system"),
                    ("Cell parameters", "Cell parameters"),
                ]
            )
        )

        self.atom_table = self._table(["Site", "El", "x", "y", "z", "Occ.", "B"], stretch_columns={0, 6})
        self.atom_table.setMinimumHeight(170)
        self.atom_table.setMaximumHeight(310)
        layout.addWidget(self.atom_table)

        layout.addWidget(self._section_title("Diffraction data"))
        self.diffraction_table = self._table(["d [A]", "2theta", "Int.", "h", "k", "l", "Mult."], stretch_columns={2, 6})
        self.diffraction_table.setMinimumHeight(160)
        self.diffraction_table.setMaximumHeight(300)
        layout.addWidget(self.diffraction_table)
        layout.addStretch(1)

    def _field_grid(self, rows: list[tuple[str, str]]) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        for row_index, (key, caption) in enumerate(rows):
            name = QLabel(caption)
            name.setStyleSheet(
                "background: #282c31; border-left: 3px solid #e9328f; "
                "color: #d4dde7; font-weight: 700; padding: 4px 7px;"
            )
            value = QLabel("-")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            colors = self._theme_colors()
            value.setStyleSheet(f"background: {colors['bg']}; color: {colors['text']}; padding: 4px 6px;")
            self.labels[key] = value
            grid.addWidget(name, row_index, 0)
            grid.addWidget(value, row_index, 1)
        grid.setColumnStretch(1, 1)
        return grid

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(self._section_style())
        return label

    def _section_style(self) -> str:
        return (
            "background: #3a3f45; border: 1px solid #515860; border-radius: 3px; "
            "color: #f1f3f4; font-weight: 700; padding: 5px 7px;"
        )

    def _table(self, headers: list[str], stretch_columns: set[int] | None = None) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(44)
        header.setStretchLastSection(False)
        self._apply_table_column_modes(table, stretch_columns)
        colors = self._theme_colors()
        table.setStyleSheet(
            f"QTableWidget {{ background: {colors['panel']}; alternate-background-color: {colors['alt']}; color: {colors['text']}; gridline-color: {colors['border']}; }}"
            f"QTableWidget::item {{ color: {colors['text']}; }}"
            f"QTableWidget::item:selected {{ background: {colors['selected']}; color: {colors['text']}; }}"
            "QHeaderView::section { background: #33383e; color: #f1f3f4; padding: 4px; }"
        )
        return table

    def _apply_table_column_modes(self, table: QTableWidget, stretch_columns: set[int] | None = None) -> None:
        columns = table.columnCount()
        stretch = set(stretch_columns or {columns - 1})
        header = table.horizontalHeader()
        for column in range(columns):
            mode = QHeaderView.ResizeMode.Stretch if column in stretch else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)

    def _theme_colors(self) -> dict[str, str]:
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        if dark:
            return {
                "bg": "#1f2328",
                "panel": "#252a31",
                "alt": "#2c323a",
                "text": "#eef2f7",
                "border": "#46515d",
                "selected": "#315f92",
                "link": "#8ab4f8",
            }
        return {
            "bg": "#f4f6f8",
            "panel": "#ffffff",
            "alt": "#f3f6fa",
            "text": "#111827",
            "border": "#cbd5e1",
            "selected": "#dbeafe",
            "link": "#0b63ce",
        }

    def _set_table_rows(self, table: QTableWidget | None, rows) -> None:
        if table is None:
            return
        table_rows = rows if isinstance(rows, list) else []
        table.setRowCount(len(table_rows))
        for row_index, row in enumerate(table_rows):
            values = row if isinstance(row, (list, tuple)) else []
            for col_index, value in enumerate(values[: table.columnCount()]):
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        header = table.horizontalHeader()
        for column in range(table.columnCount()):
            if header.sectionResizeMode(column) == QHeaderView.ResizeMode.ResizeToContents:
                table.resizeColumnToContents(column)

    def _quality_text(self, candidate: Mapping[str, object]) -> str:
        source = str(candidate.get("Source", "") or candidate.get("Qual.", "") or "")
        if source == "RRUFF":
            return "measured reference"
        if source:
            return f"{source} entry"
        return ""

    def _split_notes(self, candidate: Mapping[str, object]) -> tuple[str, str]:
        notes = str(candidate.get("Notes", "") or "").strip()
        if not notes:
            return "", ""
        normalized = notes.replace("\r", "\n")
        lines = [line.strip() for line in normalized.split("\n") if line.strip()]
        remarks: list[str] = []
        publication: list[str] = []
        remark_markers = ("sample", "temperature", "pressure", "condition", "measured", "anneal", "synthesis")
        for line in lines:
            clean = line.strip(" ;")
            lower = clean.lower()
            is_remark = line.startswith(";") or any(marker in lower for marker in remark_markers)
            if is_remark and not publication:
                remarks.append(clean)
            else:
                publication.append(clean)
        if not publication and remarks:
            return "", "\n".join(remarks)
        return "\n".join(publication), "\n".join(remarks)

    def _publication_text(self, candidate: Mapping[str, object]) -> str:
        publication, _remarks = self._split_notes(candidate)
        return publication

    def _remarks_text(self, candidate: Mapping[str, object]) -> str:
        _publication, remarks = self._split_notes(candidate)
        return remarks

    def _links_html(self, candidate: Mapping[str, object]) -> str:
        links = []
        source = str(candidate.get("Source", "") or candidate.get("Qual.", "") or "")
        entry = str(candidate.get("Entry", "") or "")
        notes = str(candidate.get("Notes", "") or "")
        explicit_doi = str(candidate.get("DOI", "") or "")

        if source == "COD" and entry:
            links.append(f'<a href="https://www.crystallography.net/cod/{entry}.html">COD {entry}</a>')
            links.append(f'<a href="https://www.crystallography.net/cod/{entry}.cif">CIF</a>')
        elif source == "MP" and entry:
            links.append(f'<a href="https://materialsproject.org/materials/{entry}">Materials Project {entry}</a>')
        elif source == "RRUFF" and entry:
            links.append(f'<a href="https://rruff.info/{entry}">RRUFF {entry}</a>')

        doi = explicit_doi or extract_doi(" ".join([entry, notes]))
        if doi:
            links.append(f'<a href="https://doi.org/{doi}">DOI {doi}</a>')

        return " &nbsp; ".join(links)
