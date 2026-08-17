# XRD WYSIWYG Layered Plot Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace XRD Phase Finder's scaled-screenshot export with an exact WYSIWYG canvas export that produces layered CorelDRAW-friendly SVG, vector PDF, and directly rendered PNG/TIFF/JPG.

**Architecture:** Keep the live pyqtgraph canvas as the only geometry source. Adapt the proven IR/Raman export modules into an XRD-owned `xrd_finder.plot_export` package, assign semantic metadata to existing `plot_layers` objects, freeze the current scene without resizing or relayout, and export every format from that frozen state. Scientific calculations and ordinary plot construction remain unchanged.

**Tech Stack:** Python 3.11, PySide6 6.7.3, pyqtgraph 0.14.0, Qt SVG/PDF/image painters, standard-library XML and atomic file operations, `unittest` with offscreen Qt.

## Global Constraints

- Match, Gain, profile fitting, phase assignment, quantification, and `.xpff` project behavior must not change.
- The current canvas is authoritative; export must not resize it, auto-range it, increase multi-pattern height, refit legends, move labels, or trigger scientific recalculation.
- Preserve canvas dimensions, aspect ratio, X/Y ranges, transforms, Z order, visibility, positions, colors, fonts, line widths, marker sizes, and legend geometry.
- Support exactly SVG, PDF, PNG, TIFF, and JPG.
- SVG is the authoritative layered CorelDRAW format; PDF remains vector but does not promise toggleable OCG layers.
- PNG, TIFF, and JPG must be painted at final output dimensions; never enlarge `plot.grab()` output.
- Never fall back to a screenshot after an export error.
- Raster DPI range is 72–2400; first-use raster default is 600 dpi.
- SVG text modes are editable text and text converted to curves; first-use format default is SVG.
- Export destinations are written atomically and existing files survive failed exports unchanged.
- All temporary canvas state is restored after success, cancellation, or failure.
- Preserve unrelated dirty and untracked work; stage only the exact files named by each task.

---

## File Structure

- Create `XRD_Finder/xrd_finder/plot_export/__init__.py`: public format, snapshot, render, and export API.
- Create `XRD_Finder/xrd_finder/plot_export/options.py`: formats, dimensions, DPI, quality, and validation.
- Create `XRD_Finder/xrd_finder/plot_export/metadata.py`: XRD semantic layers, item tags, stable SVG IDs, and layer order.
- Create `XRD_Finder/xrd_finder/plot_export/snapshot.py`: frozen canvas context and exact state restoration.
- Create `XRD_Finder/xrd_finder/plot_export/svg_items.py`: guarded Qt/pyqtgraph item-to-SVG adapter.
- Create `XRD_Finder/xrd_finder/plot_export/svg_exporter.py`: named CorelDRAW layer hierarchy and SVG document assembly.
- Create `XRD_Finder/xrd_finder/plot_export/text_outlines.py`: Qt glyph conversion for curve-text SVG mode.
- Create `XRD_Finder/xrd_finder/plot_export/paint_exporter.py`: direct PNG/TIFF/JPG/PDF rendering and atomic output.
- Create `XRD_Finder/xrd_finder/ui/plot_export_dialog.py`: format controls, direct-rendered preview, and persisted options.
- Modify `XRD_Finder/xrd_finder/ui/plot_layer_items.py`: translate existing XRD `plot_layers` into export metadata.
- Modify `XRD_Finder/xrd_finder/ui/match_profile_renderer.py`: attach stable pattern and phase ownership to accepted-profile items.
- Modify `XRD_Finder/xrd_finder/ui/observed_pattern_actions.py`: retain stable pattern ownership on observed curves and per-pattern legends.
- Modify `XRD_Finder/xrd_finder/ui/structure_overlay.py`: identify candidate-preview ownership.
- Modify `XRD_Finder/xrd_finder/ui/reference_preview_renderer.py`: identify reference-preview ownership.
- Modify `XRD_Finder/xrd_finder/ui/peak_marker_renderer.py`: retain pattern/phase ownership on assignment markers and labels.
- Modify `XRD_Finder/xrd_finder/ui/plot_view_actions.py`: tag axes, custom grid, title, and optional cursor.
- Modify `XRD_Finder/xrd_finder/ui/plot_actions.py`: replace the screenshot dialog and `_publication_plot_image()` export path.
- Modify `pyproject.toml`: pin `pyqtgraph==0.14.0`.
- Modify `XRD_Finder/requirements.txt`: pin `pyqtgraph==0.14.0` for the shared Sci runtime.
- Create focused tests under `XRD_Finder/tests/test_plot_export_*.py`.

---

### Task 1: Define Export Options And XRD Semantic Metadata

**Files:**
- Create: `XRD_Finder/xrd_finder/plot_export/__init__.py`
- Create: `XRD_Finder/xrd_finder/plot_export/options.py`
- Create: `XRD_Finder/xrd_finder/plot_export/metadata.py`
- Modify: `pyproject.toml`
- Modify: `XRD_Finder/requirements.txt`
- Test: `XRD_Finder/tests/test_plot_export_options.py`
- Test: `XRD_Finder/tests/test_plot_export_metadata.py`

**Interfaces:**
- Produces `PlotExportFormat(StrEnum)` with `SVG`, `PDF`, `PNG`, `TIFF`, and `JPG`.
- Produces `SvgTextMode(StrEnum)` with `EDITABLE` and `CURVES`.
- Produces immutable `PlotExportOptions(format, width_mm, height_mm, dpi=600, jpeg_quality=95, svg_text_mode=EDITABLE)`.
- Produces `CanvasLayer(StrEnum)` and `CANVAS_LAYER_ORDER`.
- Produces `CanvasItemTag(layer, owner_id, object_id, exportable=True)`.
- Produces `tag_canvas_item()`, `canvas_item_tag()`, and `stable_svg_id()`.

- [ ] **Step 1: Pin the supported pyqtgraph version in both dependency lists**

Replace the unbounded entries with:

```toml
"pyqtgraph==0.14.0",
```

and:

```text
pyqtgraph==0.14.0
```

The item-level SVG adapter validates this version at runtime and reports a clear incompatibility instead of silently producing malformed SVG.

- [ ] **Step 2: Write failing option tests**

Create `PlotExportOptionsTests(unittest.TestCase)` covering the five formats, locked aspect scaling, the 96-ppi 1:1 preset, finite positive dimensions, DPI `72..2400`, JPG quality `1..100`, and raster pixel calculation:

```python
def test_requested_width_preserves_canvas_aspect(self):
    options = PlotExportOptions.for_canvas(
        PlotExportFormat.SVG,
        canvas_width_px=1200,
        canvas_height_px=800,
        width_mm=180.0,
    )
    self.assertEqual(options.width_mm, 180.0)
    self.assertEqual(options.height_mm, 120.0)
    self.assertEqual(options.svg_text_mode, SvgTextMode.EDITABLE)

def test_raster_pixel_size_uses_physical_size_and_dpi(self):
    options = PlotExportOptions(PlotExportFormat.PNG, 180.0, 120.0, dpi=600)
    self.assertEqual(options.pixel_size(), (4252, 2835))
```

- [ ] **Step 3: Run the option test and verify RED**

Run:

```powershell
$env:PYTHONPATH='XRD_Finder'
python -m unittest XRD_Finder.tests.test_plot_export_options -v
```

Expected: import failure because `xrd_finder.plot_export.options` does not exist.

- [ ] **Step 4: Implement format and option validation**

Use frozen slot dataclasses and keep rounding at the final pixel boundary:

```python
def pixel_size(self) -> tuple[int, int]:
    pixels_per_mm = self.dpi / 25.4
    return (
        max(1, round(self.width_mm * pixels_per_mm)),
        max(1, round(self.height_mm * pixels_per_mm)),
    )
```

`for_canvas()` computes height from the original canvas ratio and accepts an optional physical width. Validation raises `ValueError` with the invalid field name.

- [ ] **Step 5: Write failing metadata tests**

Test tag round trips, the exportable flag, exact ordered layers, ASCII-safe IDs for Unicode/punctuation, and collision resistance:

```python
def test_stable_svg_id_is_safe_and_collision_resistant(self):
    first = stable_svg_id('phase', 'BaSiO3 / pattern 1')
    second = stable_svg_id('phase', 'BaSiO3 : pattern 1')
    self.assertRegex(first, r'^[a-z][a-z0-9-]*$')
    self.assertNotEqual(first, second)
```

- [ ] **Step 6: Implement XRD layer metadata**

Define this exact order:

```python
BACKGROUND, GRID, AXES, OBSERVED, CALCULATED_TOTAL, PHASE_PROFILES,
PHYSICAL_BACKGROUND, DIFFERENCE, CANDIDATE_PREVIEW, PHASE_TICKS,
ASSIGNMENT_MARKERS, UNKNOWN_PEAKS, LABELS, CURSOR, LEGENDS
```

`tag_canvas_item()` stores `_xrd_export_tag`, `_xrd_export_layer`, `_xrd_export_owner_id`, and `_xrd_export_object_id` without changing item rendering.

- [ ] **Step 7: Run focused tests and commit**

Run:

```powershell
python -m unittest XRD_Finder.tests.test_plot_export_options XRD_Finder.tests.test_plot_export_metadata -v
```

Expected: PASS.

```powershell
git add -- pyproject.toml XRD_Finder/requirements.txt `
  XRD_Finder/xrd_finder/plot_export/__init__.py `
  XRD_Finder/xrd_finder/plot_export/options.py `
  XRD_Finder/xrd_finder/plot_export/metadata.py `
  XRD_Finder/tests/test_plot_export_options.py `
  XRD_Finder/tests/test_plot_export_metadata.py
git commit -m "feat: add XRD plot export contracts"
```

---

### Task 2: Freeze And Restore The Exact XRD Canvas

**Files:**
- Create: `XRD_Finder/xrd_finder/plot_export/snapshot.py`
- Test: `XRD_Finder/tests/test_plot_export_snapshot.py`

**Interfaces:**
- Consumes a pyqtgraph `PlotWidget` whose content items have `CanvasItemTag` metadata.
- Produces immutable `CanvasItemSnapshot(item, tag, visible, z_value, scene_transform, scene_index)`.
- Produces `FrozenCanvas` context fields `source_rect`, `plot_item_rect`, `canvas_size_px`, `view_range`, `device_pixel_ratio`, `background`, and `items`.
- Produces `freeze_canvas(widget) -> FrozenCanvas`.

- [ ] **Step 1: Write a failing normal-exit restoration test**

Create an offscreen 640×480 `PlotWidget`, set non-default X/Y ranges, tag two items, and change one visibility flag inside `with freeze_canvas(plot)`. After exit, assert exact equality for widget size, ranges, auto-range state, update state, item visibility, and transforms.

- [ ] **Step 2: Write a failing exception-path restoration test**

Raise `RuntimeError('render failed')` inside the context and perform the same assertions after the exception.

- [ ] **Step 3: Run the snapshot tests and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest XRD_Finder.tests.test_plot_export_snapshot -v
```

Expected: import failure because `freeze_canvas()` does not exist.

- [ ] **Step 4: Implement the frozen context**

On entry:

1. process pending Qt events once;
2. record size, scene rectangle, plot rectangle, ViewBox ranges and auto-range flags, background brush, logical/device DPI, tagged item state, and widget update state;
3. disable ViewBox auto-range and widget updates without resizing or redrawing.

On exit, restore recorded values in reverse order in `finally`, make restoration idempotent, and process Qt events once. Never call `autoRange()`.

- [ ] **Step 5: Reject untagged visible plot content**

`export_items()` ignores known structural container types but raises:

```text
Unmarked export item: <fully-qualified class name>
```

for a visible item in `view_box.addedItems` that has neither an export tag nor an explicit non-exportable tag.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m unittest XRD_Finder.tests.test_plot_export_snapshot XRD_Finder.tests.test_plot_export_metadata -v
git add -- XRD_Finder/xrd_finder/plot_export/snapshot.py XRD_Finder/tests/test_plot_export_snapshot.py
git commit -m "feat: freeze XRD canvas for export"
```

---

### Task 3: Map Existing XRD Plot Layers To Export Metadata

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/plot_layer_items.py`
- Modify: `XRD_Finder/xrd_finder/ui/match_profile_renderer.py`
- Modify: `XRD_Finder/xrd_finder/ui/observed_pattern_actions.py`
- Modify: `XRD_Finder/xrd_finder/ui/structure_overlay.py`
- Modify: `XRD_Finder/xrd_finder/ui/reference_preview_renderer.py`
- Modify: `XRD_Finder/xrd_finder/ui/peak_marker_renderer.py`
- Modify: `XRD_Finder/xrd_finder/ui/plot_view_actions.py`
- Test: `XRD_Finder/tests/test_plot_export_layer_tags.py`

**Interfaces:**
- Consumes existing `plot_layers: dict[str, list]`, `_xrd_pattern_id`, and new `_xrd_phase_id`/`_xrd_candidate_id` ownership attributes.
- Produces `tag_xrd_plot_item(item, *, pattern_id=None, phase_id=None, candidate_id=None, object_id=None)`.
- Produces `sync_plot_export_tags(plot, plot_layers, *, grid_item=None, cursor_item=None, legend_item=None) -> None`.
- Does not replace existing `plot_layers` visibility or removal behavior.

- [ ] **Step 1: Write the failing layer-map test**

Construct one item in every current XRD layer and call `sync_plot_export_tags()`. Assert this exact mapping:

```python
EXPECTED = {
    'observed': CanvasLayer.OBSERVED,
    'total_profile': CanvasLayer.CALCULATED_TOTAL,
    'phase_profiles': CanvasLayer.PHASE_PROFILES,
    'background': CanvasLayer.PHYSICAL_BACKGROUND,
    'difference': CanvasLayer.DIFFERENCE,
    'calculated_profile': CanvasLayer.CANDIDATE_PREVIEW,
    'preview_profile': CanvasLayer.CANDIDATE_PREVIEW,
    'preview_peak_positions': CanvasLayer.CANDIDATE_PREVIEW,
    'preview_peak_links': CanvasLayer.CANDIDATE_PREVIEW,
    'preview_hkl': CanvasLayer.CANDIDATE_PREVIEW,
    'peak_positions': CanvasLayer.CANDIDATE_PREVIEW,
    'peak_links': CanvasLayer.CANDIDATE_PREVIEW,
    'phase_ticks': CanvasLayer.PHASE_TICKS,
    'coverage_markers': CanvasLayer.ASSIGNMENT_MARKERS,
    'candidate_markers': CanvasLayer.ASSIGNMENT_MARKERS,
    'unknown_peaks': CanvasLayer.UNKNOWN_PEAKS,
    'peak_labels': CanvasLayer.LABELS,
    'hkl': CanvasLayer.LABELS,
    'pattern_legends': CanvasLayer.LEGENDS,
    'legend_info': CanvasLayer.LEGENDS,
}
```

- [ ] **Step 2: Implement the central tag synchronizer**

For every registry list, tag items by mapped layer. Use `_xrd_pattern_id` as the primary owner. For phase layers, compose owner hierarchy as `pattern_id/phase_id`; for candidate preview use `pattern_id/candidate_id`. Assign deterministic object IDs from layer name and registry ordinal only when the item has no more specific ID.

Tag plot background, four axes and their label children, title, custom `StyledGridItem`, optional cursor, the main legend, and per-pattern legends explicitly. Mark ViewBox/layout containers and hover-only items non-exportable.

- [ ] **Step 3: Add stable ownership where items are created**

Extend the existing helper without changing calculations:

```python
def _tag_plot_item(item, pattern_id=None, *, phase_id=None, candidate_id=None, object_id=None):
    item._xrd_pattern_id = pattern_id
    item._xrd_phase_id = phase_id
    item._xrd_candidate_id = candidate_id
    item._xrd_export_object_id = object_id
    return item
```

Use the existing candidate key for `phase_id` in accepted phase profiles/ticks and for `candidate_id` in previews. Preserve the current pattern ID on observed curves, backgrounds, markers, labels, and legends.

- [ ] **Step 4: Tag structural plot items after view setup**

At the end of the current axis/grid application path, tag the four axes, title, `_plot_grid_item`, `cursor_position_line`, and `legend_item`. Do not create replacement graphics items.

- [ ] **Step 5: Test multi-pattern and multi-phase ownership**

Build two patterns sharing one phase and one pattern containing two phases. Assert observed groups remain separate by pattern, the same phase ID is retained beneath each pattern, and per-pattern legends follow their pattern owner.

- [ ] **Step 6: Run focused regressions and commit**

Run:

```powershell
python -m unittest `
  XRD_Finder.tests.test_plot_export_layer_tags `
  XRD_Finder.tests.test_incremental_profile_rendering `
  XRD_Finder.tests.test_observed_pattern_selection `
  XRD_Finder.tests.test_peak_assignment_markers `
  XRD_Finder.tests.test_plot_view_axes_grid -v
```

Expected: export tag tests pass and existing plotting tests remain unchanged.

```powershell
git add -- XRD_Finder/xrd_finder/ui/plot_layer_items.py `
  XRD_Finder/xrd_finder/ui/match_profile_renderer.py `
  XRD_Finder/xrd_finder/ui/observed_pattern_actions.py `
  XRD_Finder/xrd_finder/ui/structure_overlay.py `
  XRD_Finder/xrd_finder/ui/reference_preview_renderer.py `
  XRD_Finder/xrd_finder/ui/peak_marker_renderer.py `
  XRD_Finder/xrd_finder/ui/plot_view_actions.py `
  XRD_Finder/tests/test_plot_export_layer_tags.py
git commit -m "feat: tag XRD plot layers for export"
```

---

### Task 4: Render PNG, TIFF, JPG, And Vector PDF Directly

**Files:**
- Create: `XRD_Finder/xrd_finder/plot_export/paint_exporter.py`
- Modify: `XRD_Finder/xrd_finder/plot_export/__init__.py`
- Test: `XRD_Finder/tests/test_plot_export_paint.py`

**Interfaces:**
- Consumes `FrozenCanvas`, `PlotExportOptions`, and destination `Path`.
- Produces `render_raster(snapshot, options, *, target_pixels=None) -> QImage`.
- Produces `render_preview(snapshot, max_size: QSize) -> QImage`.
- Produces `write_vector_pdf(snapshot, options, device: QIODevice) -> None`.
- Produces `export_frozen_canvas(snapshot, options, destination) -> None`.

- [ ] **Step 1: Write failing direct-render raster tests**

For 180×120 mm at 600 dpi, assert `4252×2835` pixels and approximately 600-dpi metadata. Patch `QWidget.grab` and `QImage.scaled` to raise during final export; rendering must still succeed, proving the final image is painted directly.

- [ ] **Step 2: Implement scene painting at final size**

Allocate the final `QImage` before `QPainter`, set the live logical DPI during paint, fill the frozen background, and call:

```python
snapshot.scene.render(
    painter,
    QRectF(0.0, 0.0, float(width), float(height)),
    snapshot.source_rect,
    Qt.AspectRatioMode.IgnoreAspectRatio,
)
```

Enable antialiasing, text antialiasing, and smooth pixmap transform. After painting, write requested dots-per-metre metadata.

- [ ] **Step 3: Add PNG/TIFF/JPG writer tests**

Assert PNG and TIFF decode at exact dimensions, TIFF accepts both little- and big-endian signatures, JPG uses requested quality, and suffix/format mismatches raise `ValueError`.

- [ ] **Step 4: Write and implement bounded preview rendering**

`render_preview()` computes a target no larger than the supplied `QSize`, preserves aspect ratio, and paints the frozen scene directly at that bounded size. It may not call `grab()` and is independent of final DPI.

- [ ] **Step 5: Write failing vector PDF tests and implement QPdfWriter output**

Configure an exact millimetre `QPageSize`, zero margins, and the live logical DPI. Paint the same frozen scene into the complete page. Assert the PDF signature, physical page dimensions, and absence of a single page-sized raster image.

- [ ] **Step 6: Implement atomic dispatch and output validation**

Write to `.<name>.<uuid>.tmp`, close and flush the writer, validate non-zero size and magic bytes, then call `os.replace()`. Remove only the temporary file in `finally`. Never alter an earlier destination after failure.

- [ ] **Step 7: Run focused tests and commit**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest XRD_Finder.tests.test_plot_export_paint XRD_Finder.tests.test_plot_export_snapshot -v
git add -- XRD_Finder/xrd_finder/plot_export/paint_exporter.py `
  XRD_Finder/xrd_finder/plot_export/__init__.py `
  XRD_Finder/tests/test_plot_export_paint.py
git commit -m "feat: render publication raster and PDF"
```

---

### Task 5: Serialize The Frozen Canvas As Layered SVG

**Files:**
- Create: `XRD_Finder/xrd_finder/plot_export/svg_items.py`
- Create: `XRD_Finder/xrd_finder/plot_export/svg_exporter.py`
- Test: `XRD_Finder/tests/test_plot_export_svg.py`

**Interfaces:**
- Consumes `FrozenCanvas`, `CanvasItemSnapshot`, `CanvasLayer`, and `PlotExportOptions`.
- Produces `SvgItemFragment(element, definitions, source_bounds)`.
- Produces `render_item_svg(item_snapshot, *, root_item, canvas_size) -> SvgItemFragment`.
- Produces `namespace_svg_references(element, prefix) -> None`.
- Produces `LayeredSvgExporter.render(snapshot, options) -> bytes`.

- [ ] **Step 1: Write the failing CorelDRAW layer-tree test**

Build a deterministic XRD canvas with two observed patterns, two accepted phases, candidate preview, assignment markers, labels, grid, axes, and per-pattern legends. Parse the SVG and assert the ordered top-level labels:

```python
EXPECTED = [
    'Background', 'Grid', 'Axes', 'Observed', 'Calculated total',
    'Phase profiles', 'Physical background', 'Difference',
    'Candidate preview', 'Phase ticks', 'Assignment markers',
    'Unknown peaks', 'Labels', 'Cursor', 'Legends',
]
```

Hidden and empty layers are absent. Assert explicit millimetre width/height, one canvas `viewBox`, and no `<image>` element.

- [ ] **Step 2: Run the SVG test and verify RED**

```powershell
python -m unittest XRD_Finder.tests.test_plot_export_svg -v
```

Expected: import failure because `LayeredSvgExporter` does not exist.

- [ ] **Step 3: Adapt the guarded IR/Raman item renderer**

Port the behavior of `Vibrational_Finder/vibrational_finder/plot_export/svg_items.py` from the supplied IR/Raman source into the XRD namespace. Keep the upstream Qt/pyqtgraph license notice. Validate pyqtgraph `0.14.0` and required Qt SVG APIs at import; raise `UnsupportedPlotExporterError(detected_version)` on mismatch.

Each supported item is painted once with its frozen scene transform and common root rectangle. Preserve clipping, paths, colors, pen widths, dash arrays, marker geometry, opacity, and rotation. Do not call the full-scene pyqtgraph `SVGExporter`.

- [ ] **Step 4: Handle XRD axes and custom grid without changing geometry**

Serialize `StyledGridItem` into `GRID`. For each visible `AxisItem`, paint axis line, short ticks, tick text, and label children into `AXES`. Use the existing generated geometry and pens; do not toggle visibility or regenerate layout.

- [ ] **Step 5: Assemble named and nested groups**

Create stable `id`, `inkscape:groupmode="layer"`, and human-readable CorelDRAW/Inkscape labels. Sort layers by `CANVAS_LAYER_ORDER` and items by `(z_value, scene_index)`. Nest pattern owners and then phase/candidate owners where metadata provides them.

- [ ] **Step 6: Add reference namespacing and fidelity tests**

Assert repeated clip-path/gradient IDs receive unique prefixes and all `url(#...)`, `href`, and `xlink:href` references are rewritten. Compare source and SVG bounds/transforms for lines, curves, scatter markers, text, ticks, and legends. Unsupported types must report their semantic layer and Python class.

- [ ] **Step 7: Run focused tests and commit**

```powershell
python -m unittest `
  XRD_Finder.tests.test_plot_export_svg `
  XRD_Finder.tests.test_plot_export_snapshot `
  XRD_Finder.tests.test_plot_export_layer_tags -v
git add -- XRD_Finder/xrd_finder/plot_export/svg_items.py `
  XRD_Finder/xrd_finder/plot_export/svg_exporter.py `
  XRD_Finder/tests/test_plot_export_svg.py
git commit -m "feat: export layered XRD SVG"
```

---

### Task 6: Preserve Editable SVG Text Or Convert It To Curves

**Files:**
- Create: `XRD_Finder/xrd_finder/plot_export/text_outlines.py`
- Modify: `XRD_Finder/xrd_finder/plot_export/svg_exporter.py`
- Test: `XRD_Finder/tests/test_plot_export_text.py`

**Interfaces:**
- Produces `FontDescriptor(family, point_size, weight, italic, letter_spacing)`.
- Produces `resolved_font(descriptor) -> QRawFont`.
- Produces `glyph_run_paths(text_item_snapshot) -> list[GlyphPath]`.
- Produces `outline_svg_text(root, text_snapshots) -> None`.

- [ ] **Step 1: Write failing editable-text tests**

Export axis labels, `2theta [deg]`, `d [A]`, Unicode phase names, HKL labels, rotated labels, title, and multiline legends. Assert `<text>` content, family, point size, alignment, transform, and line positions match the frozen Qt items.

- [ ] **Step 2: Implement editable-text preservation**

Keep original SVG text nodes and transforms without recalculating positions. Add the resolved font-family list to SVG metadata. Missing fonts produce a warning returned by the exporter but do not block editable-text output.

- [ ] **Step 3: Write failing curve-text tests**

With `SvgTextMode.CURVES`, assert no visible `<text>` remains, every label becomes a named group of glyph paths, and each converted group matches the source text bounds within `0.5` canvas units.

- [ ] **Step 4: Adapt the Qt glyph-outline implementation**

Use `QTextLayout.glyphRuns()`, `QGlyphRun.rawFont()`, and `QRawFont.pathForGlyph()`. Preserve original baselines, alignment, multiline block layout, item transform, and rotation. Raise `MissingExportFontError(family)` before writing when curves cannot be produced.

- [ ] **Step 5: Compare editable and curve modes**

Require equivalent group centres within `0.25` canvas units and width/height within `0.5` canvas units for all fixture labels.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m unittest XRD_Finder.tests.test_plot_export_text XRD_Finder.tests.test_plot_export_svg -v
git add -- XRD_Finder/xrd_finder/plot_export/text_outlines.py `
  XRD_Finder/xrd_finder/plot_export/svg_exporter.py `
  XRD_Finder/tests/test_plot_export_text.py
git commit -m "feat: preserve XRD SVG text"
```

---

### Task 7: Add The Publication Export Dialog And Preview

**Files:**
- Create: `XRD_Finder/xrd_finder/ui/plot_export_dialog.py`
- Test: `XRD_Finder/tests/test_plot_export_dialog.py`

**Interfaces:**
- Consumes `FrozenCanvas`, optional initial `PlotExportOptions`, and parent widget.
- Produces `PlotExportDialog(snapshot, initial_options=None, parent=None)`.
- Produces `PlotExportDialog.options() -> PlotExportOptions`.
- Produces `PlotExportDialog.destination_filter() -> tuple[str, str]` containing suffix and file-dialog filter.

- [ ] **Step 1: Write failing dialog behavior tests**

Assert:

- order `SVG, PDF, PNG, TIFF, JPG`;
- first-use default SVG and editable text;
- width/height lock to canvas ratio;
- 1:1 reset uses 96 ppi;
- DPI appears for PNG/TIFF/JPG only;
- JPG quality appears for JPG only;
- SVG text mode appears for SVG only;
- output pixels update without resizing the live plot;
- preview is produced by `render_preview()` and never `plot.grab()`.

- [ ] **Step 2: Implement the focused dialog**

The dialog owns only widgets and option conversion. The preview label receives a bounded image from `render_preview(snapshot, QSize(...))`. It does not invoke final export or access analysis-window state.

- [ ] **Step 3: Persist successful export settings**

Add pure helpers:

```python
load_plot_export_options(settings: QSettings, canvas_size: QSize) -> PlotExportOptions
save_plot_export_options(settings: QSettings, options: PlotExportOptions) -> None
```

Use keys `plot_export/format`, `width_mm`, `dpi`, `jpeg_quality`, and `svg_text_mode`. Recompute height from the current canvas ratio when loading. Invalid stored values fall back to first-use defaults.

- [ ] **Step 4: Test suffix/filter selection and validation errors**

Expected filters are `SVG (*.svg)`, `PDF (*.pdf)`, `PNG (*.png)`, `TIFF (*.tif *.tiff)`, and `JPEG (*.jpg *.jpeg)`. The chosen destination receives a valid suffix without duplicating an existing accepted suffix.

- [ ] **Step 5: Run tests and commit**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest XRD_Finder.tests.test_plot_export_dialog XRD_Finder.tests.test_plot_export_options -v
git add -- XRD_Finder/xrd_finder/ui/plot_export_dialog.py XRD_Finder/tests/test_plot_export_dialog.py
git commit -m "feat: add XRD publication export dialog"
```

---

### Task 8: Replace The Screenshot Export Path

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/plot_actions.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Test: `XRD_Finder/tests/test_plot_export_integration.py`

**Interfaces:**
- Consumes `sync_plot_export_tags()`, `freeze_canvas()`, `PlotExportDialog`, and `export_frozen_canvas()`.
- Replaces the old `PlotExportDialog(source_image)`, `_publication_plot_image()`, and scaled `QImage` save flow.
- Retains an internal PNG preview API for `capture_analysis_preview()` without restoring screenshot-based publication export.

- [ ] **Step 1: Write a failing cancellation/state-preservation integration test**

Cancel the dialog after opening it on a multi-pattern plot. Assert unchanged widget size, splitter sizes, view ranges, aspect setting, legend positions/scales, item visibility, selected patterns, and layer contents.

- [ ] **Step 2: Write a failing successful export integration test**

Patch the file dialog to a temporary SVG destination and accept the export dialog. Assert an SVG file is created, current canvas state is byte-for-byte equivalent through a captured state tuple, and no call to `recommended_multi_pattern_export_height()`, `setFixedSize()`, or `_fit_multi_pattern_legends_to_canvas()` occurs.

- [ ] **Step 3: Replace `_export_plot_image()`**

Implement this flow:

```python
sync_plot_export_tags(
    self.match_plot,
    self.plot_layers,
    grid_item=getattr(self, '_plot_grid_item', None),
    cursor_item=getattr(self, 'cursor_position_line', None),
    legend_item=getattr(self, 'legend_item', None),
)
with freeze_canvas(self.match_plot) as snapshot:
    dialog = PlotExportDialog(snapshot, self._last_plot_export_options, self)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    options = dialog.options()
    destination = self._choose_plot_export_path(options)
    if destination is None:
        return
    export_frozen_canvas(snapshot, options, destination)
    self._last_plot_export_options = options
    save_plot_export_options(QSettings(), options)
```

Errors use `QMessageBox.warning(self, 'Export figure', f'Could not export {format}:\n{exc}')` and preserve the destination.

- [ ] **Step 4: Remove obsolete screenshot-scaling code**

Delete the in-file screenshot `PlotExportDialog`, `recommended_multi_pattern_export_height()`, export-only label resizing, scaled `QImage` output, and publication `plot.grab()` path after confirming no caller remains.

Keep `capture_analysis_preview()` working by adding `render_analysis_preview(self.match_plot, self.plot_layers) -> QImage`, which synchronizes tags, freezes the current canvas, and calls bounded direct `render_preview()`. Update the analysis-summary call site to use this helper.

- [ ] **Step 5: Test success, cancellation, and each format failure**

Inject failures for SVG serialization, raster encoding, PDF painting, unsupported item, and atomic replacement. Assert live canvas restoration and unchanged pre-existing destination in every case.

- [ ] **Step 6: Run focused integration regressions and commit**

```powershell
python -m unittest `
  XRD_Finder.tests.test_plot_export_integration `
  XRD_Finder.tests.test_analysis_preview `
  XRD_Finder.tests.test_observed_pattern_selection `
  XRD_Finder.tests.test_incremental_profile_rendering `
  XRD_Finder.tests.test_plot_view_axes_grid -v
python -m py_compile XRD_Finder/xrd_finder/ui/plot_actions.py XRD_Finder/xrd_finder/ui/analysis_windows.py
git add -- XRD_Finder/xrd_finder/ui/plot_actions.py `
  XRD_Finder/xrd_finder/ui/analysis_windows.py `
  XRD_Finder/tests/test_plot_export_integration.py `
  XRD_Finder/tests/test_analysis_preview.py
git commit -m "feat: replace XRD screenshot export"
```

---

### Task 9: Verify Cross-Format And CorelDRAW Fidelity

**Files:**
- Create: `XRD_Finder/tests/test_plot_export_acceptance.py`
- Create: `XRD_Finder/tests/fixtures/plot_export/README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces one deterministic multi-pattern fixture exported from a single frozen state to SVG, PDF, PNG, TIFF, and JPG.

- [ ] **Step 1: Build the representative acceptance canvas**

Include two observed patterns, two accepted phases, one candidate preview, calculated totals, physical backgrounds, difference curves, overlapping assignment markers, unknown peaks, accepted-phase ticks, HKL/peak labels, custom axes/grid, non-default view ranges, and separate per-pattern legends.

- [ ] **Step 2: Export all formats from one snapshot**

Assert all five files share the same aspect ratio and occupied content bounds. Verify PNG/TIFF/JPG dimensions and metadata, PDF page dimensions/vector content, SVG group hierarchy, and absence of an embedded SVG raster.

- [ ] **Step 3: Verify complete state restoration**

Capture a tuple of canvas size, ranges, auto-range flags, splitter sizes, legend geometry, layer visibility, item transforms, and selected-pattern order before export. Require exact equality after all five exports and after an injected failure.

- [ ] **Step 4: Perform the CorelDRAW acceptance check**

Open the representative SVG manually and record:

- CorelDRAW version;
- page size and aspect match;
- independently selectable observed patterns and legends;
- independently selectable phase profiles, preview, ticks, and marker layers;
- editable text remains text with installed fonts;
- curve text preserves exact placement;
- no shifted axes, labels, peaks, clipping boundaries, or legends.

Record the result in `XRD_Finder/tests/fixtures/plot_export/README.md`. Fix serializer compatibility defects and repeat the check before release.

- [ ] **Step 5: Record the feature under an Unreleased changelog section**

Insert this section above the latest numbered release in `CHANGELOG.md`:

```markdown
## Unreleased

### Added

- Added WYSIWYG publication export as layered SVG, vector PDF and directly rendered PNG, TIFF and JPG.
- Added physical output dimensions, raster DPI, SVG text modes and a direct-rendered export preview.

### Changed

- Replaced enlarged plot screenshots with exact frozen-canvas rendering while preserving editable scientific layers for CorelDRAW.
```

- [ ] **Step 6: Run the focused export suite and existing plot regressions**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -s XRD_Finder/tests -p 'test_plot_export_*.py' -v
python -m unittest `
  XRD_Finder.tests.test_analysis_preview `
  XRD_Finder.tests.test_incremental_profile_rendering `
  XRD_Finder.tests.test_observed_pattern_selection `
  XRD_Finder.tests.test_peak_assignment_markers `
  XRD_Finder.tests.test_plot_view_axes_grid -v
python -m py_compile `
  XRD_Finder/xrd_finder/plot_export/__init__.py `
  XRD_Finder/xrd_finder/plot_export/options.py `
  XRD_Finder/xrd_finder/plot_export/metadata.py `
  XRD_Finder/xrd_finder/plot_export/snapshot.py `
  XRD_Finder/xrd_finder/plot_export/paint_exporter.py `
  XRD_Finder/xrd_finder/plot_export/svg_items.py `
  XRD_Finder/xrd_finder/plot_export/svg_exporter.py `
  XRD_Finder/xrd_finder/plot_export/text_outlines.py `
  XRD_Finder/xrd_finder/ui/plot_export_dialog.py
git diff --check
```

Expected: all focused export and plot regression tests pass, compilation exits 0, and whitespace check is clean.

- [ ] **Step 7: Commit acceptance coverage and changelog**

```powershell
git add -- XRD_Finder/tests/test_plot_export_acceptance.py `
  XRD_Finder/tests/fixtures/plot_export/README.md `
  CHANGELOG.md
git commit -m "test: verify XRD publication export fidelity"
```
