# XRD WYSIWYG Layered Plot Export Design

**Date:** 2026-08-17

**Status:** Approved for implementation planning

## Goal

Replace the screenshot-based XRD Phase Finder figure export with the WYSIWYG layered export architecture already proven in IR/Raman Toolkit. The exporter must preserve the exact canvas assembled by the user, produce publication-quality raster and vector files, and make SVG scientific objects independently editable in CorelDRAW.

The work is limited to figure export. Match, Gain, profile fitting, phase assignment, quantification, project storage, and ordinary on-screen rendering remain unchanged.

## User Contract

The current XRD canvas is the sole source of exported geometry and presentation state. Export preserves:

- canvas width, height, aspect ratio, and current view ranges;
- axis positions, ticks, labels, units, frame, and grid;
- every visible observed pattern and its stack position;
- calculated totals, phase profiles, physical background, and difference curves;
- candidate preview profiles and sticks;
- accepted-phase ticks, assignment markers, unknown peaks, and labels;
- line widths, colors, dash styles, marker sizes, opacity, and Z order;
- per-pattern legends, their content, placement, size, and visibility;
- title, cursor, and other explicitly enabled figure elements.

Export does not resize the live plot, increase multi-pattern canvas height, refit legends, recompute label placement, invoke auto-range, or rebuild the plot. A multi-pattern export therefore matches the current on-screen composition exactly.

Interactive state that is not part of the figure, including hover feedback, selection handles, focus frames, and context menus, is excluded. The cursor is included only when its plot setting is enabled.

## Chosen Approach

The IR/Raman exporter is adapted into an XRD-owned package rather than imported as a runtime dependency or moved immediately into a shared library. This gives XRD the proven export behavior without coupling application installation, versioning, or internal plot models.

The new package is `xrd_finder.plot_export` and contains:

- `metadata.py` — XRD semantic layers, stable item tags, and safe SVG identifiers;
- `snapshot.py` — frozen canvas capture and guaranteed state restoration;
- `options.py` — validated format, physical dimensions, DPI, JPEG quality, and SVG text mode;
- `paint_exporter.py` — direct raster rendering, vector PDF output, atomic file replacement, and output validation;
- `svg_exporter.py` — named, CorelDRAW-compatible semantic SVG layers;
- `svg_items.py` — serialization of supported Qt and pyqtgraph items;
- `text_outlines.py` — optional conversion of SVG text to vector paths.

The XRD export dialog remains in the UI layer and consumes this package through a small public interface. The exporter does not depend on analysis-window state or scientific calculation objects.

## Semantic Layers

Every exportable graphics item receives metadata when it is added to the plot:

- semantic `layer`;
- stable `owner_id`, normally a pattern ID or phase ID;
- stable `object_id` within the owner when needed;
- an `exportable` flag.

The existing `plot_layers` registry remains the source used to associate XRD items with export layers. Tagging augments the existing objects and does not replace layer visibility management.

The SVG group hierarchy is:

```text
Canvas
  Background
  Grid
  Axes
  Observed
    <pattern owner>
  Calculated total
    <pattern owner>
  Phase profiles
    <pattern owner>
      <phase owner>
  Physical background
    <pattern owner>
  Difference
    <pattern owner>
  Candidate preview
    Profiles
    Peak sticks
    Links
    HKL labels
  Phase ticks
    <pattern owner>
      <phase owner>
  Assignment markers
    <pattern owner>
  Unknown peaks
    <pattern owner>
  Labels
    Peak labels
    HKL labels
  Cursor
  Legends
    <pattern owner>
```

Hidden and empty groups are omitted. Document order follows canvas Z order. Each group receives a stable XML ID plus a human-readable CorelDRAW/Inkscape label. Repeated internal SVG IDs and references are namespaced so several items cannot collide.

Axes, grid, canvas background, and legends created internally by pyqtgraph are tagged explicitly after plot construction. Temporary interactive objects are tagged as non-exportable.

## Frozen Canvas

Before export, pending Qt layout and paint events are processed once. The frozen snapshot records:

- canvas and plot rectangles;
- view ranges and transforms;
- device pixel ratio and logical DPI;
- background brush;
- item visibility, transforms, Z values, semantic tags, and scene order;
- fonts required by visible text.

Auto-range and animated updates are suspended while the snapshot is exported. Restoration is performed in `finally` and is idempotent. It restores visibility, ranges, auto-range state, widget size, and update state after success, cancellation, or failure.

The exporter rejects an untagged visible item in the XRD view box instead of silently omitting it. The error reports the item type so the missing semantic tag can be corrected.

## Output Formats

### SVG

SVG is the recommended CorelDRAW format. It has one `viewBox` matching the frozen canvas and explicit physical width and height from the export dialog. Scientific objects are serialized into named semantic groups without embedded raster images.

Two text modes are available:

- **Editable text** preserves text, font family, style, size, alignment, position, and rotation;
- **Text as curves** converts glyphs through Qt font outlines for maximum visual fidelity when the destination computer lacks the font.

The exporter reports fonts used by the figure and warns when editable text requests a font that cannot be resolved locally.

### PDF

PDF is painted as vector graphics from the same frozen scene onto an exact millimetre page with zero margins. Matching the live logical DPI during painting preserves pyqtgraph-generated axis text geometry. PDF Optional Content Groups are not required; SVG remains the authoritative layered format.

### PNG, TIFF, And JPG

Raster formats are painted directly into a final-size `QImage`. A captured screen bitmap is never enlarged. The live logical DPI is used during painting so dynamically generated text keeps the same layout, then the requested publication DPI is written to image metadata.

- PNG and TIFF are lossless;
- JPG is explicitly marked as lossy and has a quality setting;
- default raster resolution is 600 dpi;
- valid resolution range is 72–2400 dpi.

## Export Dialog

The XRD export dialog retains a figure preview, but the preview is rendered from the frozen scene rather than taken from `plot.grab()`.

The dialog contains:

- format: SVG, PDF, PNG, TIFF, or JPG;
- physical width and locked height in millimetres;
- raster DPI;
- JPG quality when JPG is selected;
- SVG text mode when SVG is selected;
- calculated output pixel dimensions for raster formats;
- a **1:1 canvas size** reset based on 96 pixels per inch;
- guidance that SVG is recommended for CorelDRAW.

The first-use default is SVG. The last successful export options are remembered for later sessions. Changing size or DPI applies one uniform scale to the complete frozen composition and does not alter layout.

The file dialog changes its extension and filter with the selected format. Export output is external and is not embedded in `.xpff`.

## Export Flow

1. The user invokes **Export image**.
2. The live XRD canvas is frozen without resizing or relayout.
3. The export dialog renders a bounded preview from the snapshot.
4. The user selects format and output settings.
5. The destination is selected with the correct suffix and filter.
6. The selected exporter paints or serializes the same snapshot.
7. The temporary destination is validated and atomically replaces the requested file.
8. The live canvas state is restored even if export fails.

Cancellation writes no file and leaves no temporary artifact.

## Failure Handling

- There is no fallback to `grab()`, screenshots, or post-capture scaling.
- Invalid physical dimensions, DPI, quality, suffixes, and non-finite geometry are rejected before writing.
- Unsupported or untagged items fail with their layer and item type.
- Missing fonts in curve mode fail before replacing the destination.
- Output is written to a sibling temporary file and validated by format signature and non-zero size.
- An existing destination survives any failed export unchanged.
- User-facing errors identify the failed format and the underlying cause.

## Compatibility And Migration

The current screenshot-based `PlotExportDialog`, `_publication_plot_image()`, and scaling path are removed after the new exporter is connected. Existing TIFF support is retained. No project migration is required because export files are external deliverables and export options are ordinary application settings.

The new implementation follows XRD Phase Finder naming and package boundaries. Source files from IR/Raman are adapted rather than imported from the attached archive at runtime.

## Verification

### Pure Tests

- option validation and physical-to-pixel conversions;
- stable semantic IDs and deterministic layer order;
- hidden and non-exportable item filtering;
- atomic replacement and preservation after failure;
- output suffix and format-signature validation.

### Qt Integration Tests

Using a small deterministic XRD plot:

- snapshot and restore all canvas state;
- verify final PNG and TIFF pixel dimensions and DPI metadata;
- verify PDF page dimensions and vector output;
- verify SVG viewBox, physical dimensions, colors, clipping, transforms, and Z order;
- verify pattern, phase, preview, marker, label, and legend groups;
- verify editable-text and text-as-curves modes;
- verify SVG contains no embedded raster image;
- verify an untagged visible plot item produces a clear failure;
- verify preview and final export come from the same frozen geometry.

### Manual Acceptance

Open a representative multi-pattern SVG in CorelDRAW and confirm:

- composition and aspect ratio match the XRD canvas;
- patterns and their legends can be selected independently;
- phase profiles and marker layers can be selected independently;
- text stays editable when the font is installed;
- curve text retains exact placement;
- no axes, labels, peaks, legends, or clipping boundaries shift.

The acceptance figure includes multiple observed patterns, at least two phases, overlapping assignment markers, candidate preview sticks, accepted-phase ticks, labels, individual legends, and non-default view ranges.

## Scope Boundaries

This work does not create CDR or EPS files, layered PDF OCGs, automatic captions, panel letters, or a separate publication-layout editor. It does not change plot styling, automatic label placement, scientific calculations, or project persistence. CorelDRAW-specific SVG compatibility issues are corrected in the XRD SVG serializer rather than by introducing a second plot renderer.
