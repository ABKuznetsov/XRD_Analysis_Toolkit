# Runtime Resilience and Performance Diagnostics — Design

## Goal

XRD Phase Finder must remain usable after an imported file's original drive is disconnected, and it must produce a compact diagnostic log that reveals slow operations and uncaught failures on user computers without materially slowing the application.

This work has two ordered parts:

1. add low-overhead runtime diagnostics so real bottlenecks can be measured;
2. detach imported XRD data from external source paths and avoid repeated parsing.

The implementation cycle covers both parts in ordered commits. Diagnostics land first so the storage and cache changes can be measured with the same instrumentation.

## Confirmed Root Cause

New XRD imports are validated with `load_xy()`, but the parsed array is discarded and `Pattern.source_path` continues to point at the original file. Plot refreshes, crop setup, preprocessing, Match/Gain preparation and context views call `load_xy()` again. A redraw can therefore reread and reparse the same text file several times. Slow removable storage makes the UI stall; disconnecting that storage makes later operations lose their input.

CIF imports already move into the local phase cache, and saved `.xpff` projects already embed their XRD/CIF assets. The missing boundary is the interval between importing an XRD file and saving a portable project.

## Runtime Diagnostics

### Log Location and Rotation

The Windows launcher passes `XRD_FINDER_LOG_DIR=%LocalAppData%\Sci\logs`. Other launchers provide their platform-specific Sci log directory. A source checkout without that variable falls back to a `logs` directory beside the configured application data root.

Each application process writes one UTF-8 session file named `xrd_finder-YYYYMMDD-HHMMSS-PID.log`. Startup removes old application session logs, retaining the newest ten. Setup and launcher logs are not removed by this rotation.

### Non-blocking Writer

A dedicated diagnostics module owns Python's logging configuration. Application threads submit records through `logging.handlers.QueueHandler`; one `QueueListener` thread formats and writes them. Normal GUI work never performs a file flush directly.

Shutdown drains the queue for a bounded interval and then closes the listener. Logging failures are ignored after a best-effort message to standard error; diagnostics must never prevent application startup or shutdown.

### Recorded Events

Every session records:

- application version and session identifier;
- operating system, Python version, process architecture and available physical memory when obtainable;
- startup and clean shutdown;
- uncaught main-thread and worker-thread exceptions with tracebacks;
- Qt warning/critical messages without duplicating routine debug output;
- operations that fail, regardless of duration;
- operations whose elapsed time is at least 300 ms.

Initial timed operations are:

- importing individual files and dropped folders;
- parsing XRD and CIF files;
- opening, extracting, saving and compressing `.xpff` projects;
- restoring project state;
- loading and drawing one or many observed patterns;
- preprocessing, background calculation and crop application;
- Match candidate search and profile calculation;
- Gain ranking and profile calculation;
- candidate database/cache queries;
- publication preview and export.

Each timing record includes operation name, elapsed milliseconds, success/failure, pattern count, point count, phase/candidate count and source category where applicable. It does not contain XRD intensities, CIF contents, API keys or complete user directory paths. File records use the basename plus a category such as `local`, `removable`, `network`, `portable-project` or `managed-cache`.

### Instrumentation API

The diagnostics module exposes one context manager, conceptually:

```python
with trace_operation("plot.observed", patterns=len(patterns), points=point_count):
    ...
```

It uses `time.perf_counter()` and logs only slow or failed operations. Nested operations are allowed and carry a correlation identifier so an outer `project.load` can be connected to inner extraction, parsing and redraw timings.

No timing or logging logic is placed in Match, Gain or rendering algorithms themselves beyond a context-manager boundary. This keeps scientific behavior unchanged.

### User Access

The Help menu gains `Open diagnostic logs folder`. If the folder cannot be opened, the application shows its absolute path and a short error. A later support workflow may package logs, but automatic upload is out of scope.

## Managed XRD Imports

### Local Asset Store

Before a new XRD pattern is added to the project, the importer:

1. reads the source once while copying it to a temporary local file and calculating its SHA-256 digest;
2. moves the completed temporary file atomically under `XRD_FINDER_DATA_DIR/imports/xrd/<digest-prefix>/`;
3. parses the managed local copy once and primes the in-memory cache;
4. sets `Pattern.source_path` to the managed local copy;
5. adds the pattern to the project only after all previous steps succeed.

Files with identical content reuse one managed copy. The original basename is preserved in the managed filename after unsafe characters are removed. The original absolute path is kept only as local diagnostic context and is not embedded in a shared `.xpff` manifest; the pattern name and original basename remain available to the user.

The same flow applies to file-picker import, drag-and-drop import and folder/series import. CIF handling continues to use `LocalPhaseCache`.

### Parsed XRD Cache

`load_xy()` remains the single parsing gateway and gains a bounded in-memory cache keyed by the managed file's resolved path, size and modification time. A successful import primes this cache, so the first plot does not parse the file again.

Cached arrays are treated as immutable. Callers that modify data must already create derived arrays, as the existing normalization, crop and preprocessing paths do. The cache is bounded by total array bytes, not only file count, and evicts least-recently-used entries when it exceeds 256 MiB. The limit is conservative enough for low-memory computers and can be revised using diagnostic evidence.

Cache misses, parsing duration, evictions and current cache bytes are diagnostic fields. The cache is process-local and requires no invalidation across application launches.

### Portable Projects and Removed Drives

Saving `.xpff` embeds the managed XRD files through the existing portable-project writer. Opening `.xpff` continues to extract assets into a local private directory before restoring the UI. Once loading completes, reading or plotting must not depend on the location of the `.xpff` archive.

If the original `.xpff` path becomes unavailable before Save, Save must not terminate the application. It reports that the destination is unavailable and immediately offers Save As to a local path. The already loaded project remains usable.

If a managed cache file is unexpectedly missing, operations report the affected pattern by name and keep all other patterns usable. They do not silently remove the pattern from the project.

## Error Boundaries

GUI commands that cross filesystem, archive, network or scientific-calculation boundaries catch expected exceptions at their top-level action handler, log the complete exception, and show a concise user message. Lower-level code raises typed exceptions rather than displaying dialogs.

Multi-pattern operations continue after a failure in one pattern when the operation is meaningful for the remaining patterns. The diagnostic record identifies skipped patterns and the final partial-success count.

No broad exception handler may silently discard an error. Existing `except Exception: continue/return` sites touched by this work must at least emit a diagnostic warning with operation and object identity.

## Performance Constraints

- Logging an event from the GUI thread should normally take less than 1 ms because it only enqueues a record.
- Repeated redraw of unchanged managed XRD files must perform no filesystem reads or text parsing after the cache is warm.
- Disconnecting the source drive after import must not affect plotting, preprocessing, Match, Gain or project saving to another destination.
- Diagnostic files must be bounded by ten session files and 10 MiB per file.
- Scientific arrays, results and scoring logic are unchanged by this work.

## Tests

### Diagnostics

- Slow successful operations are logged with elapsed time and fields; fast successful operations are omitted.
- Failed operations are logged even below 300 ms and include a traceback.
- Queue startup/shutdown is bounded and does not hang when the writer fails.
- Rotation retains only the newest ten application logs and does not remove setup logs.
- Sensitive values and complete user paths are absent from representative records.
- Correlation identifiers connect nested operations.

### Managed Imports

- Import from a simulated removable directory, delete the source, then plot, preprocess, Match and save `.xpff` successfully.
- File-picker, drag-and-drop and folder-series imports all use managed local paths.
- Identical files reuse one content-addressed copy.
- A failed copy or parse leaves the project unchanged and removes any partial file.
- Repeated `load_xy()` calls parse once while the file identity is unchanged.
- Changing a non-managed source file invalidates its cached array.
- LRU eviction respects the configured byte limit.
- Opening `.xpff` from a removable directory, deleting the archive after load, and exporting a plot still succeeds.
- Saving to a removed destination requests Save As and preserves project state.

### Regression

- Existing `.xpff` projects remain readable.
- Existing CIF phase-library behavior is unchanged.
- Match, Gain, normalization, crop and multi-pattern marker tests produce the same scientific results.
- The application can start when the log directory is read-only; it falls back to standard error without failing startup.

## Delivery Order

1. diagnostics foundation, session metadata, exception hooks and log-folder action;
2. instrumentation at the import, project, plot, preprocessing, Match, Gain and export boundaries;
3. managed XRD asset store and unified import path;
4. bounded parsed-array cache;
5. removed-drive Save/Save As handling and partial-failure messages;
6. run targeted regression tests, then collect a real user session log before further optimization.

The real log from the user's normal workflow is the evidence for the next optimization cycle. Algorithms or UI code outside measured bottlenecks are not refactored speculatively.
