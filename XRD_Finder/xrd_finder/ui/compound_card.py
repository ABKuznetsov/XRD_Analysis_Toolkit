from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QGridLayout,
    QHeaderView,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.services.ccdc_service import extract_doi


class CompoundCardWidget(QWidget):
    pawleyFitRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.labels: dict[str, QLabel] = {}
        self.sample_labels: dict[str, QLabel] = {}
        self.sample_title: QLabel | None = None
        self.reference_title: QLabel | None = None
        self.tabs: QTabWidget | None = None
        self.sample_phase_table: QTableWidget | None = None
        self.atom_table: QTableWidget | None = None
        self.diffraction_table: QTableWidget | None = None
        self._build_ui()

    def set_sample(
        self,
        pattern: object | None,
        phase_rows: list[list[str]] | None = None,
    ) -> None:
        data = self._sample_values(pattern)
        if self.sample_title is not None:
            title = str(data.get("Sample Name", "") or "")
            self.sample_title.setText(title if title else "No sample selected")
        for key, label in self.sample_labels.items():
            text = str(data.get(key, "") or "")
            label.setText(text if text else "-")
        self._set_table_rows(self.sample_phase_table, phase_rows)
        if pattern is not None and self.tabs is not None:
            self.tabs.setCurrentIndex(0)

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

        if self.reference_title is not None:
            title = str(data.get("Name", "") or data.get("Phase", "") or "")
            self.reference_title.setText(title if title else "No reference selected")

        for key, label in self.labels.items():
            text = str(data.get(key, "") or "")
            label.setText(text if text else "-")

        self._set_table_rows(self.atom_table, data.get("_AtomRows"))
        self._set_table_rows(self.diffraction_table, data.get("_DiffractionRows"))
        if candidate is not None and self.tabs is not None:
            self.tabs.setCurrentIndex(1)

    def _build_ui(self) -> None:
        colors = self._theme_colors()
        self.setStyleSheet(
            f"CompoundCardWidget {{ background: {colors['bg']}; color: {colors['text']}; }}"
            "QTabWidget::pane { border: 1px solid #46515d; top: -1px; }"
            "QTabBar::tab { background: #252a31; color: #eef2f7; padding: 6px 10px; }"
            "QTabBar::tab:selected { background: #34404c; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        self.tabs.addTab(self._sample_tab(colors), "Sample")
        self.tabs.addTab(self._reference_tab(colors), "Reference")

    def _sample_tab(self, colors: dict[str, str]) -> QWidget:
        scroll = self._scroll_area(colors)
        content = QWidget()
        content.setStyleSheet(f"background: {colors['bg']}; color: {colors['text']};")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.sample_title = self._section_title("No sample selected")
        layout.addWidget(self.sample_title)
        fit_button = QPushButton("Pawley cell fit")
        fit_button.setToolTip("Refine unit-cell parameters for assigned phases from observed peak positions.")
        fit_button.clicked.connect(self.pawleyFitRequested)
        layout.addWidget(fit_button)
        layout.addWidget(self._section_title("Sample provenance and measurement"))
        layout.addLayout(
            self._field_grid(
                [
                    ("Sample Name", "Sample name"),
                    ("Sample File", "Source file"),
                    ("Sample Method", "Method"),
                    ("Sample Wavelength", "Wavelength"),
                    ("Sample Units", "Axes"),
                    ("Sample Processing", "Processing"),
                    ("Sample Phases", "Assigned phases"),
                ],
                target=self.sample_labels,
            )
        )

        layout.addWidget(self._section_title("Assigned phases"))
        self.sample_phase_table = self._table(
            [
                "Phase",
                "Formula",
                "Sp. gr.",
                "a",
                "b",
                "c",
                "alpha",
                "beta",
                "gamma",
                "V",
                "Quant. (%)",
                "I/Ic",
                "Cell scale",
                "FWHM",
                "eta",
            ],
            stretch_columns={0},
        )
        self.sample_phase_table.setMinimumHeight(220)
        layout.addWidget(self.sample_phase_table, 2)
        layout.addStretch(1)
        return scroll

    def _reference_tab(self, colors: dict[str, str]) -> QWidget:
        scroll = self._scroll_area(colors)
        content = QWidget()
        content.setStyleSheet(f"background: {colors['bg']}; color: {colors['text']};")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.reference_title = self._section_title("No reference selected")
        layout.addWidget(self.reference_title)
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
        self.atom_table.setMinimumHeight(260)
        layout.addWidget(self.atom_table, 2)

        layout.addWidget(self._section_title("Diffraction data"))
        self.diffraction_table = self._table(["d [A]", "2theta", "Int.", "h", "k", "l", "Mult."], stretch_columns={2, 6})
        self.diffraction_table.setMinimumHeight(300)
        layout.addWidget(self.diffraction_table, 3)
        return scroll

    def _scroll_area(self, colors: dict[str, str]) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {colors['bg']}; border: 0; }}")
        return scroll
    def _field_grid(self, rows: list[tuple[str, str]], *, target: dict[str, QLabel] | None = None) -> QGridLayout:
        target_labels = target if target is not None else self.labels
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
            target_labels[key] = value
            grid.addWidget(name, row_index, 0)
            grid.addWidget(value, row_index, 1)
        grid.setColumnStretch(1, 1)
        return grid

    def _sample_values(self, pattern: object | None) -> dict[str, str]:
        if pattern is None:
            return {}
        name = str(getattr(pattern, "name", "") or "")
        source_path = str(getattr(pattern, "source_path", "") or "")
        source_name = Path(source_path).name if source_path else ""
        wavelength = getattr(pattern, "wavelength", None)
        try:
            wavelength_text = f"{float(wavelength):.5g} A" if wavelength else ""
        except (TypeError, ValueError):
            wavelength_text = str(wavelength or "")
        x_unit = str(getattr(pattern, "x_unit", "") or "2theta")
        y_unit = str(getattr(pattern, "y_unit", "") or "intensity")
        processed_label = str(getattr(pattern, "processed_label", "") or "")
        background_removed = bool(getattr(pattern, "processed_background_removed", False))
        processing_parts: list[str] = []
        if processed_label:
            processing_parts.append(processed_label)
        if background_removed:
            processing_parts.append("background removed")
        processed_points = getattr(pattern, "processed_points", None)
        if isinstance(processed_points, list) and processed_points:
            processing_parts.append(f"{len(processed_points)} processed points")
        linked_phase_ids = getattr(pattern, "linked_phase_ids", None)
        phase_count = len(linked_phase_ids) if isinstance(linked_phase_ids, list) else 0
        return {
            "Sample Name": name,
            "Sample File": source_name or source_path,
            "Sample Method": "XRD",
            "Sample Wavelength": wavelength_text,
            "Sample Units": f"{x_unit} / {y_unit}",
            "Sample Processing": "; ".join(processing_parts) if processing_parts else "original",
            "Sample Phases": str(phase_count) if phase_count else "none",
        }

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
