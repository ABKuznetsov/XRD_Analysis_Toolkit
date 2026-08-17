# SVG-backed Raster Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render PNG and JPEG publication figures from the same layered SVG representation used by SVG export while leaving PDF and TIFF on their existing paths.

**Architecture:** A focused `svg_rasterizer.py` module converts a frozen canvas to curve-text SVG and rasterizes it with `resvg_py`. `paint_exporter.py` routes only PNG and JPEG through that module, then uses the existing `QImageWriter` path to attach DPI metadata and encode the requested file type.

**Tech Stack:** Python 3.11/3.12, PySide6 6.7.3, `resvg_py` 0.3.3, unittest.

## Global Constraints

- PDF remains an independent vector output.
- TIFF retains the existing direct Qt scene-rendering path.
- Saved SVG files continue to respect the user's editable/curves text option.
- PNG and JPEG use curve text internally so raster export does not depend on fonts installed on the target computer.
- Missing or broken `resvg_py` produces an explicit export error and never silently falls back to direct Qt scene rendering.

---

### Task 1: Package and validate the SVG rasterizer dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `XRD_Finder/requirements.txt`
- Modify: `toolkit/check_sci_runtime.py`
- Test: `XRD_Finder/tests/test_runtime_diagnostics.py`

**Interfaces:**
- Produces: importable `resvg_py==0.3.3` in every supported runtime.
- Produces: `CORE_MODULES["resvg-py"] == "resvg_py"` for binary import validation.

- [ ] **Step 1: Write the failing dependency policy test**

Add a test that loads `pyproject.toml`, `XRD_Finder/requirements.txt`, and `toolkit.check_sci_runtime.CORE_MODULES`, then asserts all three contain `resvg_py==0.3.3` / `resvg-py` consistently.

- [ ] **Step 2: Run the dependency test and confirm failure**

Run from `XRD_Finder`:

```powershell
python -m unittest tests.test_runtime_diagnostics.RuntimeDiagnosticsTests.test_resvg_is_a_validated_runtime_dependency -v
```

Expected: FAIL because the dependency and runtime import mapping are absent.

- [ ] **Step 3: Add the pinned dependency and runtime import probe**

Add `resvg_py==0.3.3` to both dependency lists and add:

```python
"resvg-py": "resvg_py",
```

to `CORE_MODULES`.

- [ ] **Step 4: Run the dependency policy test**

Expected: PASS without changing or repairing the existing Sci environment.

- [ ] **Step 5: Commit the dependency policy**

```powershell
git add pyproject.toml XRD_Finder/requirements.txt toolkit/check_sci_runtime.py XRD_Finder/tests/test_runtime_diagnostics.py
git commit -m "build: add resvg raster dependency"
```

---

### Task 2: Implement deterministic SVG-to-QImage rasterization

**Files:**
- Create: `XRD_Finder/xrd_finder/plot_export/svg_rasterizer.py`
- Test: `XRD_Finder/tests/test_plot_export_svg_rasterizer.py`

**Interfaces:**
- Consumes: `FrozenCanvas`, `PlotExportOptions`, `LayeredSvgExporter.render()`.
- Produces: `render_svg_raster(snapshot, options, target_pixels=None) -> QImage`.

- [ ] **Step 1: Write failing rasterizer tests**

Cover these behaviours:

```python
image = render_svg_raster(snapshot, png_options)
assert (image.width(), image.height()) == png_options.pixel_size()
assert image.dotsPerMeterX() == round(png_options.dpi / 0.0254)
```

Patch `resvg_py.svg_to_bytes` in a separate test to capture arguments and assert that the supplied SVG is rendered with `PlotExportFormat.SVG`, `SvgTextMode.CURVES`, the configured background, and an effective DPI derived from the requested target width.

Patch `resvg_py.svg_to_bytes` to raise `RuntimeError("broken renderer")` and assert the public error contains `SVG rasterization failed` and the original reason.

- [ ] **Step 2: Run the new test module and confirm failure**

```powershell
python -m unittest tests.test_plot_export_svg_rasterizer -v
```

Expected: ERROR because `svg_rasterizer.py` does not exist.

- [ ] **Step 3: Implement `render_svg_raster`**

Implementation requirements:

```python
svg_options = replace(
    options,
    format=PlotExportFormat.SVG,
    svg_text_mode=SvgTextMode.CURVES,
)
svg_bytes = LayeredSvgExporter().render(snapshot, svg_options)
effective_dpi = width / options.width_mm * 25.4
png_bytes = resvg_py.svg_to_bytes(
    svg_string=svg_bytes.decode("utf-8"),
    background=snapshot.background.color().name(),
    dpi=float(effective_dpi),
    skip_system_fonts=True,
)
image = QImage.fromData(png_bytes, "PNG")
```

Validate positive dimensions, reject a null/incorrectly sized image, attach the requested DPI metadata, and wrap import/render errors in a clear `RuntimeError`.

- [ ] **Step 4: Run the rasterizer tests**

Expected: all tests PASS.

- [ ] **Step 5: Commit the rasterizer**

```powershell
git add XRD_Finder/xrd_finder/plot_export/svg_rasterizer.py XRD_Finder/tests/test_plot_export_svg_rasterizer.py
git commit -m "feat: rasterize publication SVG with resvg"
```

---

### Task 3: Route PNG and JPEG through SVG while preserving TIFF/PDF behaviour

**Files:**
- Modify: `XRD_Finder/xrd_finder/plot_export/paint_exporter.py`
- Modify: `XRD_Finder/tests/test_plot_export_paint.py`

**Interfaces:**
- Consumes: `render_svg_raster(snapshot, options, target_pixels=None) -> QImage` from Task 2.
- Preserves: `render_preview()` and TIFF use `_render_image()`.
- Preserves: PDF uses `write_vector_pdf()` and SVG uses `LayeredSvgExporter` directly.

- [ ] **Step 1: Write the failing route-selection tests**

Patch `paint_exporter.render_svg_raster` and `_render_image`, then assert:

- PNG/JPEG call `render_svg_raster` and do not call `_render_image`.
- TIFF calls `_render_image` and does not call `render_svg_raster`.
- JPEG output still uses the requested `jpeg_quality`.

- [ ] **Step 2: Run the focused paint exporter tests and confirm failure**

```powershell
python -m unittest tests.test_plot_export_paint -v
```

Expected: route-selection tests FAIL because all raster formats still use `_render_image`.

- [ ] **Step 3: Change `render_raster` routing**

Use:

```python
if options.format in {PlotExportFormat.PNG, PlotExportFormat.JPG}:
    return render_svg_raster(snapshot, options, target_pixels=target_pixels)
if options.format is PlotExportFormat.TIFF:
    # existing direct scene path
```

Do not change preview, PDF, SVG, atomic temporary-file replacement, suffix validation, or output magic validation.

- [ ] **Step 4: Run focused export tests**

```powershell
python -m unittest tests.test_plot_export_svg_rasterizer tests.test_plot_export_paint tests.test_plot_export_svg -v
```

Expected: PASS.

- [ ] **Step 5: Compare a real 600 dpi export**

Export the same frozen XRD canvas to SVG, PNG, and JPEG. Confirm PNG/JPEG dimensions match the selected physical size and DPI and visually compare layout, legend, markers, text, and line widths against SVG. Also export one 300 dpi PNG and confirm the same proportions.

- [ ] **Step 6: Commit the integration**

```powershell
git add XRD_Finder/xrd_finder/plot_export/paint_exporter.py XRD_Finder/tests/test_plot_export_paint.py
git commit -m "fix: match raster publication exports to SVG"
```

