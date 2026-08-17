from __future__ import annotations

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.plot_export.options import (
    PlotExportFormat,
    PlotExportOptions,
    SvgTextMode,
)
from xrd_finder.plot_export.paint_exporter import render_preview
from xrd_finder.plot_export.snapshot import FrozenCanvas


class PlotExportDialog(QDialog):
    """Publication export controls with a direct render of the frozen canvas."""

    _SETTINGS_PREFIX = "plot_export/"

    def __init__(
        self,
        snapshot: FrozenCanvas,
        initial_options: PlotExportOptions | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.canvas_size_px = QSize(snapshot.canvas_size_px)
        if self.canvas_size_px.width() <= 0 or self.canvas_size_px.height() <= 0:
            raise ValueError("canvas_size_px must be positive")
        self._aspect_ratio = self.canvas_size_px.width() / self.canvas_size_px.height()
        self.setWindowTitle("Export publication figure — XRD Phase Finder")
        self.resize(920, 720)
        self.setMinimumSize(720, 600)

        default_options = initial_options or self._saved_options()

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(620, 360)
        self.preview.setStyleSheet(
            "QLabel { background: white; border: 1px solid #8f969e; }"
        )

        self.format_combo = QComboBox()
        for format, label in (
            (PlotExportFormat.SVG, "SVG — layered vector (CorelDRAW)"),
            (PlotExportFormat.PDF, "PDF — vector"),
            (PlotExportFormat.PNG, "PNG — lossless raster"),
            (PlotExportFormat.TIFF, "TIFF — publication raster"),
            (PlotExportFormat.JPG, "JPG — compressed raster"),
        ):
            self.format_combo.addItem(label, format)

        self.format_hint = QLabel()
        self.format_hint.setWordWrap(True)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1.0, 2000.0)
        self.width_spin.setDecimals(2)
        self.width_spin.setSuffix(" mm")
        self.width_spin.setValue(default_options.width_mm)

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1.0, 2000.0)
        self.height_spin.setDecimals(2)
        self.height_spin.setSuffix(" mm")
        self.height_spin.setReadOnly(True)
        self.height_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)

        self.one_to_one_button = QPushButton("1:1 canvas size (96 ppi)")
        self.pixel_size_label = QLabel()
        self.pixel_size_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 2400)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(default_options.dpi)
        self.dpi_spin.setSuffix(" dpi")
        self.dpi_controls = self._control_row("Raster resolution", self.dpi_spin)

        self.jpeg_quality_spin = QSpinBox()
        self.jpeg_quality_spin.setRange(1, 100)
        self.jpeg_quality_spin.setValue(default_options.jpeg_quality)
        self.jpeg_quality_spin.setSuffix(" %")
        self.jpeg_controls = self._control_row("JPG quality", self.jpeg_quality_spin)

        self.svg_text_mode_combo = QComboBox()
        self.svg_text_mode_combo.addItem("Keep text editable", SvgTextMode.EDITABLE)
        self.svg_text_mode_combo.addItem("Convert text to curves", SvgTextMode.CURVES)
        text_index = self.svg_text_mode_combo.findData(default_options.svg_text_mode)
        self.svg_text_mode_combo.setCurrentIndex(max(0, text_index))
        self.svg_text_controls = self._control_row("SVG text", self.svg_text_mode_combo)

        form = QFormLayout()
        form.addRow("Format", self.format_combo)
        form.addRow("Width", self.width_spin)
        form.addRow("Height (locked)", self.height_spin)
        form.addRow("", self.one_to_one_button)
        form.addRow("Output", self.pixel_size_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.preview, 1)
        layout.addLayout(form)
        layout.addWidget(self.dpi_controls)
        layout.addWidget(self.jpeg_controls)
        layout.addWidget(self.svg_text_controls)
        layout.addWidget(self.format_hint)
        layout.addWidget(buttons)

        format_index = self.format_combo.findData(default_options.format)
        self.format_combo.setCurrentIndex(max(0, format_index))
        self.format_combo.currentIndexChanged.connect(self._update_controls)
        self.width_spin.valueChanged.connect(self._update_dimensions)
        self.dpi_spin.valueChanged.connect(self._update_output_size)
        self.jpeg_quality_spin.valueChanged.connect(self._update_output_size)
        self.one_to_one_button.clicked.connect(self._restore_canvas_physical_size)
        self._update_dimensions()
        self._update_controls()
        self._refresh_preview()

    @staticmethod
    def _control_row(label: str, control: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        layout.addStretch(1)
        layout.addWidget(control)
        return row

    def _selected_format(self) -> PlotExportFormat:
        return PlotExportFormat(self.format_combo.currentData())

    def _update_dimensions(self) -> None:
        self.height_spin.setValue(self.width_spin.value() / self._aspect_ratio)
        self._update_output_size()

    def _update_output_size(self) -> None:
        options = self.options()
        if options.format in {
            PlotExportFormat.PNG,
            PlotExportFormat.TIFF,
            PlotExportFormat.JPG,
        }:
            width, height = options.pixel_size()
            self.pixel_size_label.setText(
                f"{width} × {height} px; "
                f"{options.width_mm:.1f} × {options.height_mm:.1f} mm"
            )
        else:
            self.pixel_size_label.setText(
                f"{options.width_mm:.1f} × {options.height_mm:.1f} mm; "
                f"canvas {self.canvas_size_px.width()} × {self.canvas_size_px.height()}"
            )

    def _update_controls(self) -> None:
        format = self._selected_format()
        is_raster = format in {
            PlotExportFormat.PNG,
            PlotExportFormat.TIFF,
            PlotExportFormat.JPG,
        }
        self.dpi_controls.setVisible(is_raster)
        self.jpeg_controls.setVisible(format is PlotExportFormat.JPG)
        self.svg_text_controls.setVisible(format is PlotExportFormat.SVG)
        if format is PlotExportFormat.SVG:
            self.format_hint.setText(
                "Recommended for CorelDRAW: the current canvas is preserved and "
                "scientific objects are stored in named layers."
            )
        elif format is PlotExportFormat.PDF:
            self.format_hint.setText(
                "Vector PDF with the current canvas geometry and exact physical page size."
            )
        elif format in {PlotExportFormat.PNG, PlotExportFormat.TIFF}:
            self.format_hint.setText(
                "Lossless raster painted directly at the final publication resolution."
            )
        else:
            self.format_hint.setText(
                "Compressed raster painted directly at the final publication resolution."
            )
        self._update_output_size()

    def _restore_canvas_physical_size(self) -> None:
        self.width_spin.setValue(self.canvas_size_px.width() / 96.0 * 25.4)

    def _refresh_preview(self) -> None:
        available = QSize(
            max(1, self.preview.width() - 12),
            max(1, self.preview.height() - 12),
        )
        image = render_preview(self.snapshot, available)
        self.preview.setPixmap(QPixmap.fromImage(image))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_preview()

    def options(self) -> PlotExportOptions:
        return PlotExportOptions.for_canvas(
            self._selected_format(),
            canvas_width_px=self.canvas_size_px.width(),
            canvas_height_px=self.canvas_size_px.height(),
            width_mm=self.width_spin.value(),
            dpi=self.dpi_spin.value(),
            jpeg_quality=self.jpeg_quality_spin.value(),
            svg_text_mode=SvgTextMode(self.svg_text_mode_combo.currentData()),
        )

    def accept(self) -> None:
        self._save_options(self.options())
        super().accept()

    def _saved_options(self) -> PlotExportOptions:
        settings = QSettings("Xrdfinder", "Standalone")
        prefix = self._SETTINGS_PREFIX
        try:
            format = PlotExportFormat(
                settings.value(f"{prefix}format", PlotExportFormat.SVG.value, type=str)
            )
        except ValueError:
            format = PlotExportFormat.SVG
        try:
            text_mode = SvgTextMode(
                settings.value(
                    f"{prefix}svg_text_mode",
                    SvgTextMode.EDITABLE.value,
                    type=str,
                )
            )
        except ValueError:
            text_mode = SvgTextMode.EDITABLE
        default_width = self.canvas_size_px.width() / 96.0 * 25.4
        width = float(settings.value(f"{prefix}width_mm", default_width))
        return PlotExportOptions.for_canvas(
            format,
            canvas_width_px=self.canvas_size_px.width(),
            canvas_height_px=self.canvas_size_px.height(),
            width_mm=width,
            dpi=int(settings.value(f"{prefix}dpi", 600)),
            jpeg_quality=int(settings.value(f"{prefix}jpeg_quality", 95)),
            svg_text_mode=text_mode,
        )

    def _save_options(self, options: PlotExportOptions) -> None:
        settings = QSettings("Xrdfinder", "Standalone")
        prefix = self._SETTINGS_PREFIX
        settings.setValue(f"{prefix}format", options.format.value)
        settings.setValue(f"{prefix}width_mm", options.width_mm)
        settings.setValue(f"{prefix}dpi", options.dpi)
        settings.setValue(f"{prefix}jpeg_quality", options.jpeg_quality)
        settings.setValue(f"{prefix}svg_text_mode", options.svg_text_mode.value)
