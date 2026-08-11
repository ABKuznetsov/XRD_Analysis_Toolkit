# Runtime Resilience and Performance Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make XRD Phase Finder produce actionable low-overhead performance logs and remain independent of removable source media immediately after XRD import.

**Architecture:** Add a focused asynchronous diagnostics service and instrument only operation boundaries, leaving scientific algorithms unchanged. Add a content-addressed local XRD asset store, then make `load_xy()` the bounded process-local parsed-array cache used by all existing consumers. Portable projects continue to embed their assets, while unavailable Save destinations fall back to Save As without discarding loaded state.

**Tech Stack:** Python 3.11–3.12, standard-library `logging`, `queue`, `threading`, `hashlib`, `pathlib`, NumPy, PySide6, existing `unittest` suite.

## Global Constraints

- Windows diagnostic logs live under `%LocalAppData%\Sci\logs`; other launchers pass their platform-specific Sci log directory through `XRD_FINDER_LOG_DIR`.
- Retain the newest ten XRD Phase Finder session logs; never rotate or delete setup and launcher logs.
- Record successful operations only when elapsed time is at least 300 ms; record every failed operation.
- Never write XRD intensities, CIF contents, API keys or complete user directory paths to diagnostics.
- Cap each diagnostic session file at 10 MiB and keep GUI-thread enqueue time normally below 1 ms.
- Store imported XRD files under `XRD_FINDER_DATA_DIR/imports/xrd/` by SHA-256 content identity.
- Bound the parsed XRD array cache to 256 MiB and evict least-recently-used entries by total array bytes.
- Do not change Match, Gain, normalization, crop or phase-profile scientific results.
- Preserve compatibility with existing `.xpff` files and existing CIF `LocalPhaseCache` behavior.

Use this shell setup for every Python command below when running from the repository root:

```powershell
$py = "$env:LOCALAPPDATA\Sci\env\Scripts\python.exe"
$env:PYTHONPATH = (Resolve-Path "XRD_Finder").Path
```

Fail immediately with a clear runtime-repair message if `$py` does not exist or cannot start; do not silently fall back to an unrelated system Python.

---

## File Structure

- Create `XRD_Finder/xrd_finder/services/runtime_diagnostics.py`: session logging, queue writer, path sanitization, timed-operation context manager and exception hooks.
- Create `XRD_Finder/xrd_finder/services/xrd_asset_store.py`: atomic content-addressed XRD copies and source classification.
- Modify `XRD_Finder/xrd_finder/services/cache_paths.py`: canonical import-cache and diagnostic-log roots.
- Modify `XRD_Finder/xrd_finder/io/xy_loader.py`: bounded immutable NumPy array cache and cache-control API.
- Modify `XRD_Finder/xrd_finder/apps/finder_gui.py`: configure/stop diagnostics around the application lifecycle and import command-line XRD through the asset store.
- Modify `XRD_Finder/xrd_finder/ui/background_task.py`: log worker failures with operation context.
- Modify `XRD_Finder/xrd_finder/ui/phase_finder_menu.py`: expose `Open diagnostic logs folder`.
- Modify `XRD_Finder/xrd_finder/ui/analysis_windows.py`: managed import integration, project I/O timing, background-task names and removed-destination Save As fallback.
- Modify `XRD_Finder/xrd_finder/ui/candidate_search_actions.py`: Match/search operation timing.
- Modify `XRD_Finder/xrd_finder/ui/observed_pattern_actions.py`: observed-data load/draw timing.
- Modify `XRD_Finder/xrd_finder/ui/preprocessing_actions.py`: preprocessing timing.
- Modify `XRD_Finder/xrd_finder/ui/plot_actions.py`: publication preview/export timing.
- Modify `XRD_Finder/xrd_finder/io/project_io.py`: portable archive save/load/extraction timing.
- Modify Windows/macOS launchers to pass `XRD_FINDER_LOG_DIR`.
- Create `XRD_Finder/tests/test_runtime_diagnostics.py`, `test_xrd_asset_store.py`, and `test_xy_loader_cache.py`.
- Extend `XRD_Finder/tests/test_scientific_folder_import.py` and `test_portable_project_io.py` for removable-source behavior.

---

### Task 1: Asynchronous Runtime Diagnostics Core

**Files:**
- Create: `XRD_Finder/xrd_finder/services/runtime_diagnostics.py`
- Modify: `XRD_Finder/xrd_finder/services/cache_paths.py`
- Test: `XRD_Finder/tests/test_runtime_diagnostics.py`

**Interfaces:**
- Produces: `DiagnosticSession`, `configure_diagnostics(app_version: str, log_dir: Path | None = None, slow_ms: float = 300.0) -> DiagnosticSession`.
- Produces: `trace_operation(name: str, **fields: object) -> AbstractContextManager[None]`.
- Produces: `diagnostic_logger() -> logging.Logger`, `classify_source_path(path: str | Path) -> str`, and `safe_file_label(path: str | Path) -> str`.
- Produces: `default_diagnostic_log_root() -> Path` in `cache_paths.py`.

- [ ] **Step 1: Write failing diagnostics tests**

```python
class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_slow_and_failed_operations_are_logged_without_full_paths(self) -> None:
        with TemporaryDirectory() as directory:
            session = configure_diagnostics("test", Path(directory), slow_ms=0.0)
            with trace_operation("plot.observed", file_path=Path(directory) / "private" / "sample.xy", patterns=2):
                pass
            try:
                with trace_operation("gain.rank", slow_ms=10_000.0):
                    raise RuntimeError("broken")
            except RuntimeError:
                pass
            session.stop(timeout=1.0)
            text = session.path.read_text(encoding="utf-8")
            self.assertIn("operation=plot.observed", text)
            self.assertIn("operation=gain.rank", text)
            self.assertIn("status=failed", text)
            self.assertIn("sample.xy", text)
            self.assertNotIn(str(Path(directory)), text)

    def test_fast_success_is_omitted(self) -> None:
        with TemporaryDirectory() as directory:
            session = configure_diagnostics("test", Path(directory), slow_ms=10_000.0)
            with trace_operation("fast.operation"):
                pass
            session.stop(timeout=1.0)
            self.assertNotIn("fast.operation", session.path.read_text(encoding="utf-8"))
```

Add tests that create twelve old `xrd_finder-*.log` files and assert only the newest ten remain, `setup.log` remains, nested operations share one correlation ID, and a 10 MiB handler stops accepting records after writing one truncation marker.

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_runtime_diagnostics -v
```

Expected: import failure for `xrd_finder.services.runtime_diagnostics`.

- [ ] **Step 3: Add canonical log-root helpers**

Add to `cache_paths.py`:

```python
LOG_DIR_ENV = "XRD_FINDER_LOG_DIR"

def default_diagnostic_log_root() -> Path:
    configured = os.environ.get(LOG_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    return default_data_root().parent / "logs"

def default_xrd_import_root() -> Path:
    return default_data_root() / "imports" / "xrd"
```

- [ ] **Step 4: Implement the diagnostics service**

Implement a module-level current session, a `_BoundedQueueListener` whose `stop(timeout)` joins for at most the supplied interval, and a `_CappedFileHandler` that accepts at most 10 MiB and writes one `diagnostic_log_truncated=true` marker. Use `QueueHandler(SimpleQueue())` for producers.

The operation context manager must use `time.perf_counter()`, a `ContextVar[str]` correlation ID, and this record format:

```text
2026-08-11T12:34:56.789+07:00 level=INFO event=operation operation=plot.observed status=ok elapsed_ms=412.6 correlation=... patterns=2 file=sample.xy source=removable
```

On exception, emit `logger.exception(...)` and re-raise the original exception. Convert `Path` or fields ending in `_path` to basename plus source classification before formatting.

- [ ] **Step 5: Run diagnostics tests**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_runtime_diagnostics -v
```

Expected: all diagnostics tests pass and the test process exits without a listener thread hang.

- [ ] **Step 6: Commit the diagnostics core**

```powershell
git add XRD_Finder/xrd_finder/services/runtime_diagnostics.py XRD_Finder/xrd_finder/services/cache_paths.py XRD_Finder/tests/test_runtime_diagnostics.py
git commit -m "Add asynchronous runtime diagnostics"
```

---

### Task 2: Application Lifecycle, Exception Hooks and Log Folder Action

**Files:**
- Modify: `XRD_Finder/xrd_finder/apps/finder_gui.py`
- Modify: `XRD_Finder/xrd_finder/ui/background_task.py`
- Modify: `XRD_Finder/xrd_finder/ui/phase_finder_menu.py`
- Modify: `toolkit/launch_xrd_finder_preview.ps1`
- Modify: `XRD_Finder/run_finder.bat`
- Modify: `XRD_Finder/run_finder.command`
- Test: `XRD_Finder/tests/test_runtime_diagnostics.py`

**Interfaces:**
- Consumes: `configure_diagnostics`, `trace_operation`, `diagnostic_logger`, `default_diagnostic_log_root` from Task 1.
- Produces: `install_exception_hooks() -> None` and `restore_exception_hooks() -> None` in `runtime_diagnostics.py`.
- Produces: `BackgroundTaskHandle(..., operation_name: str = "background.task")`.

- [ ] **Step 1: Add failing lifecycle and worker-error tests**

Add tests that patch `sys.excepthook` and `threading.excepthook`, install hooks, call them with a `RuntimeError`, stop the session and assert both tracebacks are logged. Add a test that runs `BackgroundTaskWorker(lambda: 1 / 0, operation_name="match.search").run()` and asserts the existing `failed` signal still emits while the diagnostic logger receives `operation=match.search`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_runtime_diagnostics -v
```

Expected: failures for missing hooks and missing `operation_name`.

- [ ] **Step 3: Wire diagnostics into application startup and shutdown**

In `finder_gui.main()`, configure diagnostics before constructing `QApplication`, install hooks, wrap project loading and window construction in named `trace_operation` contexts, and always stop diagnostics in `finally`:

```python
session = configure_diagnostics(__version__)
install_exception_hooks()
try:
    return _run_gui(args)
finally:
    restore_exception_hooks()
    session.stop(timeout=1.0)
```

Record version, OS, Python, architecture and obtainable physical memory during `configure_diagnostics`. Do not add `psutil`; use standard-library platform APIs and omit memory when unavailable.

- [ ] **Step 4: Log background worker failures without changing signals**

Wrap the worker callable in `trace_operation(self._operation_name)` and retain the current `finished`/`failed` signal contract. Pass meaningful names from `AnalysisWindow._run_background_task`, beginning with `search.auto`, `search.text`, `project.load`, and `project.save` callers.

- [ ] **Step 5: Add the Help action**

Add `Help > Open diagnostic logs folder` calling an owner method that uses `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`. If it returns false, show the path in a warning dialog. This action creates the directory if necessary but does not start a new logger.

- [ ] **Step 6: Pass the log directory from launchers**

Windows launchers set:

```powershell
$startInfo.EnvironmentVariables["XRD_FINDER_LOG_DIR"] = $logsRoot
```

and:

```bat
set "XRD_FINDER_LOG_DIR=%SCI_ROOT%\logs"
```

The macOS launcher exports its existing Sci logs path. Do not change setup log locations.

- [ ] **Step 7: Run tests and commit**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_runtime_diagnostics -v
```

Expected: all tests pass.

```powershell
git add XRD_Finder/xrd_finder/apps/finder_gui.py XRD_Finder/xrd_finder/ui/background_task.py XRD_Finder/xrd_finder/ui/phase_finder_menu.py toolkit/launch_xrd_finder_preview.ps1 XRD_Finder/run_finder.bat XRD_Finder/run_finder.command XRD_Finder/tests/test_runtime_diagnostics.py
git commit -m "Wire diagnostics into application lifecycle"
```

---

### Task 3: Instrument High-value Operation Boundaries

**Files:**
- Modify: `XRD_Finder/xrd_finder/io/project_io.py`
- Modify: `XRD_Finder/xrd_finder/io/cif_loader.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Modify: `XRD_Finder/xrd_finder/ui/candidate_search_actions.py`
- Modify: `XRD_Finder/xrd_finder/ui/observed_pattern_actions.py`
- Modify: `XRD_Finder/xrd_finder/ui/preprocessing_actions.py`
- Modify: `XRD_Finder/xrd_finder/ui/plot_actions.py`
- Test: `XRD_Finder/tests/test_runtime_diagnostics.py`
- Test: `XRD_Finder/tests/test_portable_project_io.py`

**Interfaces:**
- Consumes: `trace_operation(name, **fields)` from Task 1.
- Produces no new scientific interfaces; only named timing boundaries.

- [ ] **Step 1: Add failing operation-name coverage tests**

Patch `runtime_diagnostics.trace_operation` with a recorder and exercise small existing harnesses to assert these stable names are used:

```text
project.load
project.save
project.extract
import.scientific
plot.observed
preprocess.auto
match.search
match.profile
gain.rank
export.figure
```

For `project_io`, save and load a two-point `.xpff` project and assert the timing fields contain patterns, phases and asset count without full paths.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_runtime_diagnostics XRD_Finder.tests.test_portable_project_io -v
```

Expected: operation-name assertions fail because boundaries are not instrumented.

- [ ] **Step 3: Instrument project and scientific-file I/O**

Wrap `save_project_manifest`, `load_project_manifest`, `_save_portable_project`, `_load_portable_project`, `_extract_portable_member`, `load_xy`, and CIF parsing entry points. Fields must be counts, byte sizes, basenames and source categories only.

- [ ] **Step 4: Instrument UI boundaries**

Wrap these existing entry points, not inner numerical loops:

- `AnalysisWindow._import_scientific_paths` as `import.scientific`;
- `PhaseFinderObservedPatternActionsMixin._draw_observed_patterns` as `plot.observed`;
- `_pattern_auto_preprocessing_result` as `preprocess.auto`;
- candidate background task bodies in `_auto_search_candidates`, `_search_pdf2_text` and `_search_from_controls` as `match.search`;
- `_recalculate_match_profile` as `match.profile`;
- the call that builds Gain rows as `gain.rank`;
- `_export_plot_image` preview/render/save stages as `export.figure` with format and output pixel count.

Do not time mouse-move, paint-event or individual-peak loops.

- [ ] **Step 5: Replace silent failure only at touched boundaries**

Where a touched multi-pattern loop currently uses `except Exception: continue`, call:

```python
diagnostic_logger().warning(
    "event=pattern_skipped operation=plot.observed pattern=%s",
    pattern.name,
    exc_info=True,
)
```

Continue processing remaining patterns. Preserve the current visible behavior unless no pattern succeeds.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_runtime_diagnostics XRD_Finder.tests.test_portable_project_io XRD_Finder.tests.test_observed_pattern_selection -v
```

Expected: all tests pass.

```powershell
git add XRD_Finder/xrd_finder/io/project_io.py XRD_Finder/xrd_finder/io/cif_loader.py XRD_Finder/xrd_finder/ui/analysis_windows.py XRD_Finder/xrd_finder/ui/candidate_search_actions.py XRD_Finder/xrd_finder/ui/observed_pattern_actions.py XRD_Finder/xrd_finder/ui/preprocessing_actions.py XRD_Finder/xrd_finder/ui/plot_actions.py XRD_Finder/tests/test_runtime_diagnostics.py XRD_Finder/tests/test_portable_project_io.py
git commit -m "Trace slow XRD Phase Finder operations"
```

---

### Task 4: Content-addressed Managed XRD Asset Store

**Files:**
- Create: `XRD_Finder/xrd_finder/services/xrd_asset_store.py`
- Test: `XRD_Finder/tests/test_xrd_asset_store.py`

**Interfaces:**
- Consumes: `default_xrd_import_root`, `classify_source_path`, `trace_operation`.
- Produces: immutable `ImportedXrdAsset(path: Path, data: np.ndarray, sha256: str, original_name: str, source_category: str)`.
- Produces: `XrdAssetStore(root: Path | None = None).import_file(source: str | Path) -> ImportedXrdAsset`.
- Consumes later: `prime_xy_cache(path: Path, data: np.ndarray)` from Task 6; until Task 6, return parsed data without priming.

- [ ] **Step 1: Write failing atomic-copy and deduplication tests**

```python
class XrdAssetStoreTests(unittest.TestCase):
    def test_import_survives_source_removal_and_reuses_identical_content(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "usb" / "first.xy"
            second = root / "usb" / "renamed.xy"
            first.parent.mkdir()
            first.write_text("10 1\n11 2\n", encoding="utf-8")
            second.write_bytes(first.read_bytes())
            store = XrdAssetStore(root / "managed")
            a = store.import_file(first)
            b = store.import_file(second)
            first.unlink()
            second.unlink()
            self.assertEqual(a.path, b.path)
            self.assertTrue(a.path.is_file())
            np.testing.assert_allclose(a.data[:, :2], [[10, 1], [11, 2]])
```

Add tests for partial-copy cleanup when the source read fails, rejection of an empty/invalid XRD file without publishing a managed asset, sanitized filenames, and source-category preservation.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_xrd_asset_store -v
```

Expected: import failure for `xrd_finder.services.xrd_asset_store`.

- [ ] **Step 3: Implement streaming atomic import**

Copy the source to `root/.incoming/<uuid>.tmp` in 1 MiB blocks while updating SHA-256. Flush and close before parsing. Parse the temporary local file once with the uncached parser. Publish with `os.replace()` to:

```text
<root>/<sha256[0:2]>/<sha256>/<sanitized-first-import-name>
```

If the digest directory already contains a regular file, reuse that file and delete the temporary copy. The first imported basename wins for identical content. Remove the temporary file in `finally` on every failure.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_xrd_asset_store -v
```

Expected: all asset-store tests pass.

```powershell
git add XRD_Finder/xrd_finder/services/xrd_asset_store.py XRD_Finder/tests/test_xrd_asset_store.py
git commit -m "Add managed XRD asset store"
```

---

### Task 5: Route Every XRD Import Through the Managed Store

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Modify: `XRD_Finder/xrd_finder/apps/finder_gui.py`
- Modify: `XRD_Finder/tests/test_scientific_folder_import.py`
- Modify: `XRD_Finder/tests/test_portable_project_io.py`

**Interfaces:**
- Consumes: `XrdAssetStore.import_file()` from Task 4.
- Produces: every newly created `Pattern.source_path` points to a managed local asset.

- [ ] **Step 1: Extend the import harness with a temporary asset store**

Update `_ImportHarness` to set:

```python
self.xrd_asset_store = XrdAssetStore(asset_root)
```

Add tests for file-picker-equivalent `_import_scientific_paths`, dropped single files and dropped folders. After each import, delete all original files and assert every `Pattern.source_path` still exists under the managed root.

- [ ] **Step 2: Add an atomic project-mutation test**

Patch `xrd_asset_store.import_file` to raise `OSError("device removed")`; assert `_import_scientific_paths` returns an error and does not append a `Pattern` or assign it to a series.

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_scientific_folder_import -v
```

Expected: imported pattern paths still point to deleted originals.

- [ ] **Step 4: Integrate the store into GUI imports**

Construct `self.xrd_asset_store = XrdAssetStore()` once in `AnalysisWindow`. Replace the current `load_xy(path)` validation branch with:

```python
asset = self.xrd_asset_store.import_file(path)
pattern = Pattern.create(name=path.stem, source_path=str(asset.path))
```

Append and assign the pattern only after `import_file` succeeds. Keep current per-file error collection so folder imports continue after one bad file.

- [ ] **Step 5: Integrate command-line `--pattern` import**

Change `build_local_project()` to accept an `XrdAssetStore`, import each supplied XRD through it, and report individual failures through diagnostics. Do not create a `Pattern` that still points at the command-line source.

- [ ] **Step 6: Verify portable save after source removal**

Add an integration test that imports from a temporary `usb` directory, removes that directory, saves `.xpff`, reloads it and verifies the extracted XRD values and series membership.

- [ ] **Step 7: Run tests and commit**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_scientific_folder_import XRD_Finder.tests.test_portable_project_io -v
```

Expected: all tests pass.

```powershell
git add XRD_Finder/xrd_finder/ui/analysis_windows.py XRD_Finder/xrd_finder/apps/finder_gui.py XRD_Finder/tests/test_scientific_folder_import.py XRD_Finder/tests/test_portable_project_io.py
git commit -m "Detach imported XRD files from source media"
```

---

### Task 6: Bounded Parsed XRD Array Cache

**Files:**
- Modify: `XRD_Finder/xrd_finder/io/xy_loader.py`
- Modify: `XRD_Finder/xrd_finder/services/xrd_asset_store.py`
- Test: `XRD_Finder/tests/test_xy_loader_cache.py`

**Interfaces:**
- Produces: `load_xy(path: str | Path) -> np.ndarray` with a 256 MiB process cache.
- Produces: `prime_xy_cache(path: str | Path, data: np.ndarray) -> None`, `clear_xy_cache() -> None`, `configure_xy_cache(max_bytes: int) -> None`, `xy_cache_stats() -> dict[str, int]`.
- Consumes: `prime_xy_cache` in `XrdAssetStore.import_file`.

- [ ] **Step 1: Write failing cache tests**

```python
class XyLoaderCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_xy_cache()
        configure_xy_cache(256 * 1024 * 1024)

    def test_unchanged_file_is_parsed_once_and_cached_array_is_read_only(self) -> None:
        with TemporaryDirectory() as directory, patch("pathlib.Path.read_text", wraps=Path.read_text) as read_text:
            path = Path(directory) / "sample.xy"
            path.write_text("10 1\n11 2\n", encoding="utf-8")
            first = load_xy(path)
            second = load_xy(path)
            self.assertIs(first, second)
            self.assertFalse(first.flags.writeable)
            self.assertEqual(read_text.call_count, 1)
```

Add tests for size/mtime invalidation, `prime_xy_cache`, byte-based LRU eviction with a tiny configured limit, and stats fields `hits`, `misses`, `evictions`, `bytes`, `entries`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_xy_loader_cache -v
```

Expected: imports fail for cache-control functions or `read_text.call_count` equals two.

- [ ] **Step 3: Separate parsing from caching**

Extract `_parse_xy_text(path: Path) -> np.ndarray` from the current `load_xy`. Set returned arrays read-only after construction. Use `(normcase(resolve(path)), stat.st_size, stat.st_mtime_ns)` as the cache key and an `OrderedDict` for LRU order.

- [ ] **Step 4: Implement byte-bounded cache and diagnostics**

On hit, move the key to the end. On insert, evict from the beginning until total `array.nbytes <= max_bytes`. Record cache hit/miss/eviction fields through `diagnostic_logger().debug`; these records remain in memory unless the configured log level explicitly includes debug.

`prime_xy_cache` stores the verified immutable array under the managed file identity. `XrdAssetStore.import_file` calls it after publishing the final path, so the first plot is a cache hit.

- [ ] **Step 5: Run cache and import tests**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_xy_loader_cache XRD_Finder.tests.test_xrd_asset_store XRD_Finder.tests.test_scientific_folder_import -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add XRD_Finder/xrd_finder/io/xy_loader.py XRD_Finder/xrd_finder/services/xrd_asset_store.py XRD_Finder/tests/test_xy_loader_cache.py
git commit -m "Cache parsed XRD arrays by file identity"
```

---

### Task 7: Removed Save Destination and Partial-failure Handling

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Modify: `XRD_Finder/xrd_finder/ui/context_viewer.py`
- Modify: `XRD_Finder/xrd_finder/ui/legacy_windows.py`
- Modify: `XRD_Finder/tests/test_portable_project_io.py`
- Create: `XRD_Finder/tests/test_removed_media_resilience.py`

**Interfaces:**
- Consumes managed local `Pattern.source_path` and `trace_operation`.
- Produces: `_write_project(path, *, offer_save_as_on_unavailable: bool = True) -> bool` with one Save As fallback.

- [ ] **Step 1: Write failing removed-destination tests**

Create an `AnalysisWindow` harness with stubbed dialogs. Set `project.root_path` to a removed directory, patch `save_project_manifest` to raise `FileNotFoundError`, call `_save_project()`, and assert `_save_project_as()` is invoked once while the project object, patterns and current root path remain unchanged until the alternative save succeeds.

Add a multi-pattern test where one deliberately missing legacy source is skipped with a diagnostic warning while a managed pattern still loads and plots.

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_removed_media_resilience -v
```

Expected: no Save As fallback or unhandled missing-source path.

- [ ] **Step 3: Implement one-shot Save As fallback**

In `_write_project`, catch `FileNotFoundError`, `NotADirectoryError`, `PermissionError` and removable/network `OSError`. Log `project.save` failure, show one message that the destination is unavailable, and call `_save_project_as()` only when the failing path equals the current `project.root_path`. Pass `offer_save_as_on_unavailable=False` to the second write to prevent recursion.

Do not change `project.root_path` until `save_project_manifest` completes successfully.

- [ ] **Step 4: Surface pattern-specific missing-source warnings**

In context/legacy views and touched plot loaders, preserve partial rendering and log `pattern_skipped` with the pattern name. When the active pattern alone is unavailable, show one concise warning naming it instead of returning an empty graph without explanation.

- [ ] **Step 5: Run resilience and regression tests**

Run:

```powershell
& $py -m unittest XRD_Finder.tests.test_removed_media_resilience XRD_Finder.tests.test_portable_project_io XRD_Finder.tests.test_scientific_folder_import XRD_Finder.tests.test_observed_pattern_selection -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add XRD_Finder/xrd_finder/ui/analysis_windows.py XRD_Finder/xrd_finder/ui/context_viewer.py XRD_Finder/xrd_finder/ui/legacy_windows.py XRD_Finder/tests/test_portable_project_io.py XRD_Finder/tests/test_removed_media_resilience.py
git commit -m "Handle removed project media without losing state"
```

---

### Task 8: Full Verification and Diagnostic Handoff

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Test: all `XRD_Finder/tests/test_*.py`

**Interfaces:**
- Consumes all previous tasks.
- Produces user instructions for locating and sharing diagnostics.

- [ ] **Step 1: Document diagnostics and managed imports**

Add a troubleshooting section stating:

```text
Help > Open diagnostic logs folder opens the per-user Sci logs directory.
Attach the newest xrd_finder-*.log when reporting a freeze or crash.
Imported XRD files are copied to the local application cache, so removable source media can be disconnected after import completes.
```

Document that logs omit raw diffraction/CIF contents and full user paths.

- [ ] **Step 2: Run syntax and JSON checks**

Run:

```powershell
& $py -m py_compile XRD_Finder/xrd_finder/services/runtime_diagnostics.py XRD_Finder/xrd_finder/services/xrd_asset_store.py XRD_Finder/xrd_finder/io/xy_loader.py XRD_Finder/xrd_finder/apps/finder_gui.py XRD_Finder/xrd_finder/ui/analysis_windows.py
& $py -m json.tool XRD_Finder/app.json > $null
& $py -m json.tool toolkit/manifest.json > $null
```

Expected: exit code 0.

- [ ] **Step 3: Run the complete test suite**

Run from `XRD_Finder` with the configured Sci Python:

```powershell
Push-Location XRD_Finder
try {
    & $py -m unittest discover -s tests -p "test_*.py" -v
} finally {
    Pop-Location
}
```

Expected: all tests pass. If an external database/network test is intentionally unavailable, record the exact skipped test and reason; do not treat unexpected errors as skips.

- [ ] **Step 4: Run a removable-media smoke test**

Use a temporary directory representing a removable drive:

1. import at least three XRD files as a series;
2. remove the source directory;
3. switch between single and multi mode;
4. run preprocessing, Match and Gain;
5. save and reopen `.xpff`;
6. export a publication PNG;
7. verify the newest diagnostic log contains operation timings and no source absolute path.

Expected: every step succeeds without reading the removed directory.

- [ ] **Step 5: Review the real diagnostic log**

Confirm the log has session metadata, operation names, elapsed times, counts and any failures; confirm it remains below 10 MiB and the GUI did not visibly pause while logging.

- [ ] **Step 6: Commit documentation and final adjustments**

```powershell
git add README.md CHANGELOG.md
git commit -m "Document diagnostics and resilient XRD imports"
```

- [ ] **Step 7: Prepare the user handoff**

Report:

- exact test command and result;
- location of the newest diagnostic log;
- the slowest measured operations from the smoke test;
- any remaining optimization candidates, ordered by measured elapsed time rather than speculation.
