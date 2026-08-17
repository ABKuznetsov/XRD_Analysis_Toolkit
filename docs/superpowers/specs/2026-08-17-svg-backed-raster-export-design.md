# SVG-backed raster export design

## Goal

Make PNG and JPEG publication exports visually match the application's SVG export at any requested resolution. PDF remains an independent vector output and is not used as an intermediate raster source.

## Architecture

The layered SVG exporter is the single authoritative renderer for SVG, PNG, and JPEG. PNG and JPEG export first creates the same SVG representation used by the SVG option, then rasterizes it with `resvg_py`. This replaces direct high-resolution `QGraphicsScene.render()` for those two formats.

The resulting PNG bytes are decoded into a `QImage`. PNG is written losslessly with the requested DPI metadata. JPEG is written from the same image with the selected quality, an opaque configured background, and the requested DPI metadata. TIFF and PDF retain their existing paths in this change.

## Behaviour

- SVG, PNG, and JPEG preserve the same layout, font proportions, legend size, marker size, line widths, visibility, and layer ordering.
- Requested physical size and DPI determine the raster dimensions.
- Transparent SVG content is composited onto the selected export background before JPEG encoding.
- A missing or failed `resvg_py` renderer produces a clear export error; it does not silently fall back to the inconsistent Qt scene renderer.
- `resvg_py` becomes a required packaged runtime dependency and is included in the runtime validation/install lists.

## Boundaries

- PDF stays a standalone vector export.
- PDF-to-image conversion is not added.
- Existing SVG editability options remain unchanged for saved SVG files.
- Raster conversion uses an SVG representation suitable for deterministic rendering; it does not alter the user's saved SVG preference.

## Verification

- A focused test verifies that PNG/JPEG raster content is produced from the SVG renderer rather than the live scene path.
- Existing dimension, DPI, PNG, and JPEG writer tests remain in place.
- A real exported XRD figure is compared across SVG, PNG, and JPEG for matching proportions and layer visibility.
- Export is checked at the default 600 dpi and at one lower resolution.

