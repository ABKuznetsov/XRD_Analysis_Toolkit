# SQL-backed Match/Gain Pipeline Implementation Plan

> **For Codex:** Execute this plan task by task. Use test-first changes and run only the focused tests named below unless a broader run is explicitly requested.

**Goal:** Rank structural candidates directly from line sets already stored in SQLite, then add newly downloaded and indexed candidates to the active search in small background batches without blocking the UI.

**Architecture:** Keep the existing managed CIF cache and `LocalPhaseCache` schema. Add an immutable finder-side indexed-line contract, prefer it over CIF calculation in `FinderService`, and isolate download/index orchestration in a small service instead of growing `analysis_windows.py` or `candidate_search_service.py`. Search sessions use monotonic tokens; completed background work is cached globally but updates only matching active sessions.

**Tech Stack:** Python 3.11+, SQLite, NumPy/SciPy, PySide6, existing `FinderService`, `LocalPhaseCache`, CrIStMa adapter, `unittest`.

---

## Scope and Non-goals

This slice changes the data path, not the Match/Gain formula. It does not redesign the SQLite schema, bulk-recalculate existing databases, add radiation-specific indexes, or move refinement logic into Finder.

The source behavior is intentionally split:

- COD, CCDC, MP, AFLOW and OQMD rows become scoreable only after an indexed line set is available.
- USER rows use indexed lines when available and retain the CIF fallback for old projects.
- RRUFF and PDF-2 keep their existing reference-pattern paths because their lines do not depend on downloading and indexing a structural CIF.

## Task 1: Introduce the immutable indexed-line contract

**Files:**

- Create: `XRD_Finder/xrd_finder/finder/reference_lines.py`
- Modify: `XRD_Finder/xrd_finder/finder/models.py`
- Modify: `XRD_Finder/xrd_finder/finder/__init__.py`
- Test: `XRD_Finder/tests/test_indexed_reference_lines.py`

### Step 1: Write failing contract tests

Cover:

- `ReferenceLine` is frozen and stores `d`, cached `two_theta`, normalized/raw intensity, hkl and multiplicity;
- `ReferenceLineSet` is immutable, has `source`, `entry_id`, `derived_version`, provenance and a deterministic fingerprint;
- invalid/empty/non-finite rows are rejected or filtered deterministically;
- line order is stable by `two_theta`, then hkl.

Run:

```bash
cd XRD_Finder
"/Users/artem/Library/Application Support/Sci/env-arm64/bin/python" -m unittest tests.test_indexed_reference_lines -v
```

Expected: FAIL because the contract does not exist.

### Step 2: Implement the minimal model

Use frozen, slotted dataclasses. Keep SQL parsing out of these objects; expose a small constructor such as `ReferenceLineSet.from_records(...)` that accepts neutral mappings and normalizes values. The fingerprint must include candidate identity, derived version and line values used by profile caching.

Extend `FinderCandidateInput` with:

```python
cif_path: str = ""
reference_lines: ReferenceLineSet | None = None
```

Require at least one of `structure`, `reference_lines` or `cif_path` at calculation time, not in `__post_init__`, so old serialized/test inputs remain compatible.

### Step 3: Run the focused contract test

Expected: PASS.

### Step 4: Commit

```bash
git add XRD_Finder/xrd_finder/finder/reference_lines.py XRD_Finder/xrd_finder/finder/models.py XRD_Finder/xrd_finder/finder/__init__.py XRD_Finder/tests/test_indexed_reference_lines.py
git commit -m "feat: define indexed reference line contract"
```

## Task 2: Read current line sets from SQLite without opening CIF files

**Files:**

- Modify: `XRD_Finder/xrd_finder/services/local_phase_cache.py`
- Create: `XRD_Finder/xrd_finder/ui/candidate_line_provider.py`
- Test: `XRD_Finder/tests/test_candidate_line_provider.py`

### Step 1: Write failing repository/provider tests

Create a temporary `LocalPhaseCache`, seed one current entry and one obsolete entry, and assert:

- `peak_records(source, entry_id)` reads ordered rows from `phase_peaks`;
- it returns normalized and raw intensity plus d/h/k/l/multiplicity;
- `CandidateLineProvider` returns a `ReferenceLineSet` only when `derived_version == DERIVED_CACHE_VERSION` and lines exist;
- missing/obsolete entries return a typed `needs_index=True` result instead of silently opening a CIF;
- reading a current line set does not call `create_phase_from_cif`, `CalculatedPatternService`, or CrIStMa.

### Step 2: Add the narrow cache query

Add to `LocalPhaseCache`:

```python
def peak_records(self, source: str, entry_id: str) -> list[dict[str, object]]:
    ...
```

Query `phase_peaks` ordered by `peak_index`. Do not parse `peaks_json` in the hot path and do not add a schema migration.

### Step 3: Implement the UI boundary adapter

`CandidateLineProvider` owns the dependency on both `LocalPhaseCache` and finder models. It resolves `SOURCE:ENTRY`, checks the current derived version, maps neutral SQL records to `ReferenceLineSet`, and reports one of:

```text
READY
MISSING
OBSOLETE
UNSUPPORTED
```

This keeps `LocalPhaseCache` independent of finder-layer types and keeps SQL knowledge out of `FinderService`.

### Step 4: Run the focused provider test

Expected: PASS.

### Step 5: Commit

```bash
git add XRD_Finder/xrd_finder/services/local_phase_cache.py XRD_Finder/xrd_finder/ui/candidate_line_provider.py XRD_Finder/tests/test_candidate_line_provider.py
git commit -m "feat: expose indexed candidate lines from sqlite"
```

## Task 3: Make Finder prefer indexed lines over CIF calculation

**Files:**

- Modify: `XRD_Finder/xrd_finder/finder/profile_calculator.py`
- Modify: `XRD_Finder/xrd_finder/finder/service.py`
- Test: `XRD_Finder/tests/test_finder_indexed_candidate_path.py`

### Step 1: Write failing hot-path tests

Assert:

- a candidate carrying `reference_lines` reaches Match/Gain without `Path.stat`, CIF parsing or CrIStMa;
- SQL lines are converted to the existing `HKLPeak` representation with stable order and intensity;
- profile cache keys include the line-set fingerprint and calculation context;
- an old candidate with only `cif_path` still uses the compatibility path;
- candidate identity remains `SOURCE:ENTRY` in both paths;
- changing selected phases still changes Gain while Match continues to use the full observed signal.

Use mocks that fail loudly if the CIF calculator is touched for a current indexed candidate.

### Step 2: Add indexed-line conversion to `CachedProfileCalculator`

Add a focused method:

```python
def peaks_from_reference_lines(
    self,
    lines: ReferenceLineSet,
    context: CalculationContext,
) -> list[HKLPeak]:
    ...
```

Use cached `two_theta` for the current Cu K-alpha index. Retain `d` in the contract; if the active primary wavelength differs from the index provenance, derive `two_theta` from `d` only when valid and mark that behavior in a succinct comment. Keep K-alpha doublet/profile broadening in the existing `calculated_profile_from_peaks(...)` path.

### Step 3: Change the candidate preparation priority

In `FinderService.run` use this order:

```text
explicit structure override
indexed reference line set
CIF compatibility fallback
skip invalid candidate
```

For indexed candidates, pass `structure=None`. Any logic that previously inferred “indexed cell” from a structure must treat the immutable indexed line set as fixed crystallographic geometry and avoid accidental `cell_scale` fitting.

### Step 4: Run the focused hot-path tests

Expected: PASS.

### Step 5: Commit

```bash
git add XRD_Finder/xrd_finder/finder/profile_calculator.py XRD_Finder/xrd_finder/finder/service.py XRD_Finder/tests/test_finder_indexed_candidate_path.py
git commit -m "perf: rank indexed candidates without cif recalculation"
```

## Task 4: Wire indexed lines into candidate ranking

**Files:**

- Modify: `XRD_Finder/xrd_finder/ui/match_profile_renderer.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Modify: `XRD_Finder/xrd_finder/ui/candidate_structure_actions.py`
- Test: `XRD_Finder/tests/test_indexed_candidate_ui_adapter.py`

### Step 1: Write failing adapter tests

Cover:

- `build_finder_candidate_inputs` accepts a line-provider callback;
- a current indexed candidate is included even when no local CIF path is available;
- an obsolete entry is omitted from immediate scoring and reported for background indexing;
- PDF-2/RRUFF continue through their current line adapters;
- current candidate selection uses the stable key and does not depend on a filesystem path.

### Step 2: Extend `build_finder_candidate_inputs`

Resolve indexed lines before calling `candidate_cif_path`. Only request a CIF fallback when no ready line set exists. Return a third value containing candidates that need indexing, or a small result object with `ready`, `candidate_by_key` and `needs_index` fields.

### Step 3: Add one provider instance to the window

Create `CandidateLineProvider` beside `LocalPhaseCache` initialization and pass its resolver into `build_finder_candidate_inputs`. Keep `analysis_windows.py` changes to wiring only; do not move SQL parsing or batching into it.

Update `_candidate_peaks_for_gain` to ask the same provider first, removing the duplicate `peaks_json` hot path after compatibility tests pass.

### Step 4: Update the finder cache key

Use `ReferenceLineSet.fingerprint` for indexed candidates and the current path/mtime key only for compatibility-CIF candidates. The cache key must change when derived lines or the instrument context changes.

### Step 5: Run the focused adapter test

Expected: PASS.

### Step 6: Commit

```bash
git add XRD_Finder/xrd_finder/ui/match_profile_renderer.py XRD_Finder/xrd_finder/ui/analysis_windows.py XRD_Finder/xrd_finder/ui/candidate_structure_actions.py XRD_Finder/tests/test_indexed_candidate_ui_adapter.py
git commit -m "feat: feed sqlite line sets into candidate scoring"
```

## Task 5: Extract a background download/index queue with session subscribers

**Files:**

- Create: `XRD_Finder/xrd_finder/services/candidate_preparation_queue.py`
- Modify: `XRD_Finder/xrd_finder/services/candidate_search_service.py`
- Test: `XRD_Finder/tests/test_candidate_preparation_queue.py`
- Modify test: `XRD_Finder/tests/test_staged_candidate_search.py`

### Step 1: Write failing queue tests

Cover:

- jobs expose separate `DOWNLOADING` and `INDEXING` stages;
- SQLite/index writes remain serialized through the single worker;
- a second search subscribing to an already queued `SOURCE:ENTRY` receives the completion event too;
- an obsolete local entry can enqueue an index-only job without downloading again;
- completion includes `session_token`, `source`, `entry_id` and final outcome;
- failed/offline jobs update counters but do not invalidate ready local rows;
- shutdown releases the worker cleanly.

### Step 2: Implement the queue as a standalone service

Use dataclasses such as:

```python
CandidatePreparationJob(fetch, index, source, entry_id)
CandidatePreparationProgress(queued, downloading, indexing, ready, failed)
CandidatePreparedNotice(session_tokens, source, entry_id, error)
```

Maintain subscribers per stable key so queue deduplication does not lose a newer active search. A job may complete after its originating search is stale; its indexed cache entry remains valid.

### Step 3: Delegate from `CandidateSearchService`

Keep source-specific fetch/index adapters in `CandidateSearchService`, but move queue ownership, counters and worker lifecycle into `CandidatePreparationQueue`. Split combined “download and index” helpers into `fetch -> Path` and `index(Path)` callables.

Do not call `cancel_background_downloads()` when a new search starts. Session-token filtering will prevent stale UI updates while useful cache work completes.

### Step 4: Delay structural remote rows until indexed

For COD/CCDC/MP/AFLOW/OQMD:

- return current local indexed rows immediately;
- queue remote metadata for preparation;
- do not append unindexed metadata rows to the scoreable result set;
- emit prepared notices after successful indexing.

RRUFF/PDF-2 retain immediate rows when their own reference patterns are available.

### Step 5: Run focused queue/search tests

```bash
cd XRD_Finder
"/Users/artem/Library/Application Support/Sci/env-arm64/bin/python" -m unittest \
  tests.test_candidate_preparation_queue \
  tests.test_staged_candidate_search -v
```

Expected: PASS.

### Step 6: Commit

```bash
git add XRD_Finder/xrd_finder/services/candidate_preparation_queue.py XRD_Finder/xrd_finder/services/candidate_search_service.py XRD_Finder/tests/test_candidate_preparation_queue.py XRD_Finder/tests/test_staged_candidate_search.py
git commit -m "refactor: isolate candidate download and indexing queue"
```

## Task 6: Batch active-session updates and preserve table context

**Files:**

- Create: `XRD_Finder/xrd_finder/ui/candidate_batch_updates.py`
- Create: `XRD_Finder/xrd_finder/ui/candidate_search_status.py`
- Modify: `XRD_Finder/xrd_finder/ui/candidate_search_actions.py`
- Modify: `XRD_Finder/xrd_finder/ui/candidate_tables.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Test: `XRD_Finder/tests/test_candidate_batch_updates.py`
- Test: `XRD_Finder/tests/test_candidate_table_context.py`

### Step 1: Write failing batch/session tests

Cover:

- notices from stale tokens never update the active table;
- active notices are coalesced by a short timer and deduplicated by `SOURCE:ENTRY`;
- a flush merges with existing local rows, recalculates Match/Gain and applies the correct primary sort;
- selected row and horizontal/vertical scroll values survive replacement and re-ranking when the key still exists;
- missing selected keys fall back predictably to the first row;
- status text reports local, queued/downloading, indexing, ranking, downloaded-ready and failed counts;
- an offline completion ends in a usable local-results state without `QMessageBox`.

### Step 2: Implement the small batch coordinator

`CandidateBatchUpdateController` should own the active token, pending prepared rows and a `QTimer` (roughly 150–250 ms). It exposes `start_session`, `accept_notice`, `flush` and `finish`. It receives callbacks for row merge/rank rather than importing the main window.

### Step 3: Preserve table context by stable key

Add capture/restore helpers to `CandidateTableWidget` based on `Source` + `Entry`. Make ordinary `set_rows` preserve context by default, with an explicit opt-out for “new search, select first row”. Avoid row-number identity.

### Step 4: Wire search actions

At search start:

- increment the existing token;
- start the batch controller;
- show local indexed rows immediately;
- subscribe queued jobs with that token.

At each batch flush:

- convert completed cache entries to rows;
- merge/dedupe;
- call existing Match/Gain ranking once for the batch;
- preserve selected key and scroll context.

At completion or partial network failure, keep the current table and set the aggregate status. The existing bottom `background_status_label` remains the display target.

### Step 5: Run focused UI tests headlessly

```bash
cd XRD_Finder
QT_QPA_PLATFORM=offscreen \
"/Users/artem/Library/Application Support/Sci/env-arm64/bin/python" -m unittest \
  tests.test_candidate_batch_updates \
  tests.test_candidate_table_context \
  tests.test_candidate_search_progress_dialog -v
```

Expected: PASS.

### Step 6: Commit

```bash
git add XRD_Finder/xrd_finder/ui/candidate_batch_updates.py XRD_Finder/xrd_finder/ui/candidate_search_status.py XRD_Finder/xrd_finder/ui/candidate_search_actions.py XRD_Finder/xrd_finder/ui/candidate_tables.py XRD_Finder/xrd_finder/ui/analysis_windows.py XRD_Finder/tests/test_candidate_batch_updates.py XRD_Finder/tests/test_candidate_table_context.py
git commit -m "feat: batch background candidate updates"
```

## Task 7: Focused end-to-end regression check

**Files:**

- Create: `XRD_Finder/tests/test_sql_match_gain_pipeline.py`
- Optionally update: `XRD_Finder/benchmark_results/` only if an existing tracked benchmark format already covers this scenario

### Step 1: Add one deterministic pipeline fixture

Build a temporary cache with:

- one dominant indexed phase;
- one complementary impurity;
- one high-intensity false candidate whose strong lines miss observed peaks;
- one remote candidate that becomes ready after the first table render.

Verify:

- initial ranking is by Match;
- after selecting the dominant phase, the complementary phase leads Gain;
- false unmatched intensity is penalized by the existing formula;
- the newly indexed phase appears only after batch completion;
- no CIF/CrIStMa call occurs for current indexed rows;
- Match/Gain numerical definitions are unchanged from the existing calculator.

### Step 2: Run only the pipeline regression set

```bash
cd XRD_Finder
QT_QPA_PLATFORM=offscreen \
"/Users/artem/Library/Application Support/Sci/env-arm64/bin/python" -m unittest \
  tests.test_indexed_reference_lines \
  tests.test_candidate_line_provider \
  tests.test_finder_indexed_candidate_path \
  tests.test_indexed_candidate_ui_adapter \
  tests.test_candidate_preparation_queue \
  tests.test_staged_candidate_search \
  tests.test_candidate_batch_updates \
  tests.test_candidate_table_context \
  tests.test_sql_match_gain_pipeline -v
```

Expected: all focused tests PASS. Do not run the entire repository suite unless requested.

### Step 3: Manual smoke check

Use one existing real pattern:

1. Select elements and press Find.
2. Confirm local rows and Match values appear before network work finishes.
3. Confirm the status bar advances through download/index/rank counts.
4. Select the dominant phase and confirm Gain becomes the active ordering.
5. Confirm newly indexed rows arrive in batches without losing the selected row.
6. Disable network and confirm local search still completes without a blocking error.

### Step 4: Final review

Check:

- no new module approaches 1000 lines;
- `analysis_windows.py` only gained wiring;
- no current indexed candidate enters CIF/CrIStMa broad ranking;
- existing project/cache formats remain readable;
- unrelated dirty-worktree changes were not modified.

### Step 5: Commit

```bash
git add XRD_Finder/tests/test_sql_match_gain_pipeline.py
git commit -m "test: cover sql backed match gain pipeline"
```

## Rollback and Compatibility

The compatibility-CIF branch remains available throughout the migration. If a current indexed line set cannot be produced, the candidate is either queued for indexing or uses the existing CIF path for explicit user/project data. Since the SQLite schema and project serialization are unchanged, rollback consists of reverting the application commits; cached CIF and indexed phase data remain valid.

