from __future__ import annotations

import os
import uuid
from pathlib import Path

from PySide6.QtCore import QByteArray, QFile, QIODevice, QMarginsF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QImage, QImageWriter, QPageLayout, QPageSize, QPainter, QPdfWriter

from .options import PlotExportFormat, PlotExportOptions
from .snapshot import FrozenCanvas


_FORMAT_SUFFIXES = {
    PlotExportFormat.SVG: {".svg"},
    PlotExportFormat.PDF: {".pdf"},
    PlotExportFormat.PNG: {".png"},
    PlotExportFormat.TIFF: {".tif", ".tiff"},
    PlotExportFormat.JPG: {".jpg", ".jpeg"},
}

_MAGIC = {
    PlotExportFormat.SVG: (b"<?xml", b"<svg"),
    PlotExportFormat.PDF: (b"%PDF-",),
    PlotExportFormat.PNG: (b"\x89PNG\r\n\x1a\n",),
    PlotExportFormat.TIFF: (b"II*\x00", b"MM\x00*"),
    PlotExportFormat.JPG: (b"\xff\xd8\xff",),
}


def _paint_scene(snapshot: FrozenCanvas, painter: QPainter, target: QRectF) -> None:
    snapshot.export_items()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    snapshot.scene.render(
        painter,
        target,
        snapshot.source_rect,
        Qt.AspectRatioMode.IgnoreAspectRatio,
    )


def _render_image(snapshot: FrozenCanvas, width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():
        raise MemoryError(f"Could not allocate {width}x{height} export image")
    image.setDotsPerMeterX(round(float(snapshot.logical_dpi_x) / 0.0254))
    image.setDotsPerMeterY(round(float(snapshot.logical_dpi_y) / 0.0254))
    image.fill(snapshot.background.color())
    painter = QPainter(image)
    if not painter.isActive():
        raise RuntimeError("Could not start raster painter")
    try:
        _paint_scene(snapshot, painter, QRectF(0.0, 0.0, float(width), float(height)))
    finally:
        painter.end()
    return image


def render_raster(
    snapshot: FrozenCanvas,
    options: PlotExportOptions,
    *,
    target_pixels: tuple[int, int] | None = None,
) -> QImage:
    if options.format not in {
        PlotExportFormat.PNG,
        PlotExportFormat.TIFF,
        PlotExportFormat.JPG,
    }:
        raise ValueError("render_raster requires PNG, TIFF or JPG options")
    width, height = target_pixels or options.pixel_size()
    if width <= 0 or height <= 0:
        raise ValueError("target_pixels must contain positive dimensions")
    image = _render_image(snapshot, int(width), int(height))
    dots_per_metre = round(options.dpi / 0.0254)
    image.setDotsPerMeterX(dots_per_metre)
    image.setDotsPerMeterY(dots_per_metre)
    return image


def render_preview(snapshot: FrozenCanvas, max_size: QSize) -> QImage:
    max_width = int(max_size.width())
    max_height = int(max_size.height())
    if max_width <= 0 or max_height <= 0:
        raise ValueError("max_size must be positive")
    source_width = max(1, int(snapshot.canvas_size_px.width()))
    source_height = max(1, int(snapshot.canvas_size_px.height()))
    scale = min(max_width / source_width, max_height / source_height)
    width = max(1, round(source_width * scale))
    height = max(1, round(source_height * scale))
    return _render_image(snapshot, width, height)


def _write_raster_image(image: QImage, options: PlotExportOptions, destination: Path) -> None:
    encodings = {
        PlotExportFormat.PNG: b"png",
        PlotExportFormat.TIFF: b"tiff",
        PlotExportFormat.JPG: b"jpg",
    }
    try:
        encoding = encodings[options.format]
    except KeyError as exc:
        raise ValueError("Raster writer requires PNG, TIFF or JPG options") from exc
    writer = QImageWriter(str(destination), QByteArray(encoding))
    if options.format is PlotExportFormat.JPG:
        writer.setQuality(options.jpeg_quality)
    if not writer.write(image):
        raise RuntimeError(
            f"Could not encode {options.format.value.upper()}: {writer.errorString()}"
        )


def write_vector_pdf(snapshot: FrozenCanvas, options: PlotExportOptions, device: QIODevice) -> None:
    if options.format is not PlotExportFormat.PDF:
        raise ValueError("write_vector_pdf requires PDF options")
    snapshot.export_items()
    writer = QPdfWriter(device)
    writer.setResolution(max(72, int(snapshot.logical_dpi_x)))
    page_size = QPageSize(
        QSizeF(options.width_mm, options.height_mm),
        QPageSize.Unit.Millimeter,
        "XRD publication figure",
        QPageSize.SizeMatchPolicy.ExactMatch,
    )
    writer.setPageSize(page_size)
    writer.setPageMargins(
        QMarginsF(0.0, 0.0, 0.0, 0.0),
        QPageLayout.Unit.Millimeter,
    )
    painter = QPainter(writer)
    if not painter.isActive():
        raise RuntimeError("Could not start PDF painter")
    try:
        target = QRectF(0.0, 0.0, float(writer.width()), float(writer.height()))
        painter.fillRect(target, snapshot.background)
        _paint_scene(snapshot, painter, target)
    finally:
        painter.end()
    del writer


def _write_svg(snapshot: FrozenCanvas, options: PlotExportOptions, destination: Path) -> None:
    from .svg_exporter import LayeredSvgExporter

    data = LayeredSvgExporter().render(snapshot, options)
    file = QFile(str(destination))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly | QIODevice.OpenModeFlag.Truncate):
        raise OSError(file.errorString())
    try:
        if file.write(data) != len(data) or not file.flush():
            raise OSError(file.errorString())
    finally:
        file.close()


def _write_pdf(snapshot: FrozenCanvas, options: PlotExportOptions, destination: Path) -> None:
    file = QFile(str(destination))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly | QIODevice.OpenModeFlag.Truncate):
        raise OSError(file.errorString())
    try:
        write_vector_pdf(snapshot, options, file)
        if not file.flush():
            raise OSError(file.errorString())
    finally:
        file.close()


def _validate_output(destination: Path, format: PlotExportFormat) -> None:
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Exporter produced an empty file")
    prefix = destination.read_bytes()[:16].lstrip()
    if not any(prefix.startswith(magic) for magic in _MAGIC[format]):
        raise RuntimeError(f"Exporter produced an invalid {format.value.upper()} file")


def export_frozen_canvas(
    snapshot: FrozenCanvas,
    options: PlotExportOptions,
    destination: str | Path,
) -> None:
    destination = Path(destination)
    if destination.suffix.lower() not in _FORMAT_SUFFIXES[options.format]:
        allowed = ", ".join(sorted(_FORMAT_SUFFIXES[options.format]))
        raise ValueError(
            f"Destination suffix must be {allowed} for {options.format.value.upper()}"
        )
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        if options.format in {
            PlotExportFormat.PNG,
            PlotExportFormat.TIFF,
            PlotExportFormat.JPG,
        }:
            _write_raster_image(render_raster(snapshot, options), options, temporary)
        elif options.format is PlotExportFormat.PDF:
            _write_pdf(snapshot, options, temporary)
        elif options.format is PlotExportFormat.SVG:
            _write_svg(snapshot, options, temporary)
        else:
            raise ValueError(f"Unsupported export format: {options.format}")
        _validate_output(temporary, options.format)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
