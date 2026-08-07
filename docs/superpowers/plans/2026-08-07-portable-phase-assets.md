# Portable XPFF Phase Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every `.xpff` project self-contained: all CIF-backed phases used by Match/Gain are embedded once, restored on another computer, recalculated automatically, and remain editable without populating the global USER library.

**Architecture:** Extend `FinderProjectState` with a candidate-key-to-CIF-path map. During UI state synchronization, collect the unique candidates referenced by the active Match list and every per-pattern `profile_states[*].candidates`, resolve their local CIF files, and save those paths. The portable ZIP writer embeds and deduplicates the files under `assets/candidates/`; the loader extracts them to the existing project-private temporary directory. Candidate resolution prefers this project-private map, so the normal structure parser and profile renderer restore calculated curves and markers unchanged.

**Tech Stack:** Python 3.11, dataclasses, `zipfile`, PySide6 UI mixins, `unittest`.

## Global Constraints

- Do not add embedded candidates to `Project.phases`, `Project.structures`, the project tree, or the global USER cache.
- Embed only CIF-backed candidates actually referenced by the saved Match/Gain working sets.
- Store one CIF asset per unique candidate/source file even when the phase occurs in many patterns.
- Preserve per-pattern candidate membership in `profile_states`; quantities and marker positions continue to be recalculated from the restored CIF and XRD data.
- Keep old `.xpff` files loadable through a default empty mapping.
- Abort an `.xpff` save before replacing the destination if any referenced CIF cannot be resolved or read.
- Keep path traversal protection for extracted ZIP members.

---

### Task 1: Add portable candidate assets to the project model and ZIP format

**Files:**
- Modify: `XRD_Finder/xrd_finder/core/finder_state.py`
- Modify: `XRD_Finder/xrd_finder/io/project_io.py`
- Modify: `XRD_Finder/tests/test_portable_project_io.py`

- [ ] **Step 1: Write failing round-trip tests**

Add tests that construct a `Project` with no `Project.phases` or `Project.structures`, but with:

```python
candidate_key = "USER:BaSiO3"
project.finder_state.match_candidates = [candidate]
project.finder_state.profile_states = {
    first_pattern.id: {"candidates": [candidate]},
    second_pattern.id: {"candidates": [candidate]},
}
project.finder_state.candidate_cif_paths = {candidate_key: str(cif_path)}
```

Assert after save, deleting the original CIF, and load that:

- `candidate_cif_paths[candidate_key]` points to a readable extracted CIF;
- the ZIP contains exactly one member under `assets/candidates/` for the phase shared by two patterns;
- both pattern states still reference the same candidate key;
- a manifest without `candidate_cif_paths` loads with `{}`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest XRD_Finder.tests.test_portable_project_io -v
```

Expected failure: `FinderProjectState` lacks `candidate_cif_paths`, or the loaded path still points outside the archive extraction root.

- [ ] **Step 3: Add the model field**

In `FinderProjectState`, add:

```python
candidate_cif_paths: dict[str, str] = field(default_factory=dict)
```

The default preserves compatibility with older JSON and `.xpff` manifests because `_from_dataclass()` ignores absent and unknown fields.

- [ ] **Step 4: Embed and extract the mapping**

In `project_io.py`, add focused helpers with these signatures:

```python
def _embed_path_mapping(
    archive: zipfile.ZipFile,
    paths: Any,
    folder: str,
    default_suffix: str,
    file_members: dict[str, str],
) -> None:
    """Rewrite local mapping values to deduplicated ZIP member paths."""

def _extract_path_mapping(
    archive: zipfile.ZipFile,
    paths: dict[str, str],
    extraction_root: Path,
) -> dict[str, str]:
    """Return candidate keys mapped to project-private extracted paths."""
```

Call the embed helper for `data["finder_state"]["candidate_cif_paths"]` before writing `project.json`, and call the extraction helper on `project.finder_state.candidate_cif_paths` during load. Reuse `file_members` so a CIF already stored elsewhere in the project is written only once.

Raise `ValueError` with the candidate key and source path when a mapped file is absent or unreadable. Keep the existing temporary ZIP plus `os.replace()` sequence so a failed save cannot replace a valid project.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m unittest XRD_Finder.tests.test_portable_project_io -v
```

Expected: all portable project I/O tests pass.

- [ ] **Step 6: Commit the model and I/O slice**

```powershell
git add XRD_Finder/xrd_finder/core/finder_state.py XRD_Finder/xrd_finder/io/project_io.py XRD_Finder/tests/test_portable_project_io.py
git commit -m "Embed Match phase CIFs in XPFF projects"
```

---

### Task 2: Capture every used Match/Gain phase without duplicating shared phases

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/project_state_actions.py`
- Add: `XRD_Finder/tests/test_portable_candidate_state.py`

- [ ] **Step 1: Write failing candidate-collection tests**

Create a lightweight mixin harness and test a new helper:

```python
def _collect_project_candidate_cif_paths(self) -> dict[str, str]:
    """Resolve one readable local CIF path for every saved candidate key."""
```

Cover these cases:

- active `match_candidates` plus candidates from all `profile_states` are collected;
- the same `USER:BaSiO3` candidate in multiple patterns is resolved once;
- a second distinct candidate is included separately;
- stale saved mappings not referenced by any current pattern are removed;
- a referenced candidate with no resolvable CIF raises a clear `ValueError` containing its source and entry.

The harness stubs `_candidate_key()` and `_candidate_local_cif_path()` so tests do not require a live Qt window or network.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest XRD_Finder.tests.test_portable_candidate_state -v
```

Expected failure: `_collect_project_candidate_cif_paths` does not exist.

- [ ] **Step 3: Implement unique collection and save it in `FinderProjectState`**

The helper must:

1. iterate `self.match_candidates` and each dictionary `profile_states[pattern_id]["candidates"]`;
2. accept only CIF-backed sources `COD`, `USER`, `MP`, `CCDC`, `AFLOW`, and `OQMD` with a non-empty entry;
3. deduplicate by `_candidate_key(candidate)`;
4. resolve a local file through `_candidate_local_cif_path(candidate)` without downloading during Save;
5. fall back to the currently loaded `project.finder_state.candidate_cif_paths` for already extracted assets;
6. return normalized string paths or raise a phase-specific error.

Pass the helper result to the `candidate_cif_paths` argument when constructing `FinderProjectState` in `_sync_finder_state_to_project()`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m unittest XRD_Finder.tests.test_portable_candidate_state -v
```

Expected: all candidate collection tests pass.

- [ ] **Step 5: Commit the UI-state slice**

```powershell
git add XRD_Finder/xrd_finder/ui/project_state_actions.py XRD_Finder/tests/test_portable_candidate_state.py
git commit -m "Save CIF assets for all used project phases"
```

---

### Task 3: Restore embedded CIFs before local/global caches

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/candidate_structure_actions.py`
- Modify: `XRD_Finder/tests/test_portable_candidate_state.py`

- [ ] **Step 1: Write failing resolution tests**

Using the same harness, assert that `_candidate_local_cif_path(candidate)`:

- returns the embedded path from `project.finder_state.candidate_cif_paths` even when the local cache is empty;
- prefers the embedded project copy over a different global cache copy;
- ignores a missing embedded path and falls back to the existing cache/project-phase logic;
- does not index or copy the embedded file into the global USER library.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest XRD_Finder.tests.test_portable_candidate_state -v
```

Expected failure: current resolution checks the local cache first and never consults `candidate_cif_paths`.

- [ ] **Step 3: Implement project-private resolution**

At the start of `_candidate_local_cif_path()`, compute `_candidate_key(candidate)`, inspect `self.project.finder_state.candidate_cif_paths`, and return the mapped `Path` only when it is a file. Then retain all current USER/project-phase/database cache fallbacks unchanged.

Because `_restore_match_state()` already calls `_candidate_local_cif_path()`, parses the CIF with `create_phase_from_cif()`, and then invokes `_recalculate_match_profile()`, no separate marker restoration path is needed.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m unittest XRD_Finder.tests.test_portable_candidate_state XRD_Finder.tests.test_portable_project_io -v
```

Expected: embedded project assets take priority and portable I/O remains green.

- [ ] **Step 5: Commit the restore slice**

```powershell
git add XRD_Finder/xrd_finder/ui/candidate_structure_actions.py XRD_Finder/tests/test_portable_candidate_state.py
git commit -m "Restore Match phases from embedded project CIFs"
```

---

### Task 4: Verify the complete portable-project workflow

**Files:**
- Modify only if a test exposes a defect in the files above.

- [ ] **Step 1: Run the full automated suite**

Run from the repository root:

```powershell
python -m unittest discover -s XRD_Finder/tests -p "test_*.py" -v
```

Expected: all tests pass.

- [ ] **Step 2: Inspect the archive contract**

Create a temporary `.xpff` fixture with one phase used by two patterns and verify:

- `project.json` contains one `candidate_cif_paths` entry;
- the ZIP contains one corresponding CIF member;
- the manifest contains two independent pattern candidate lists;
- loading succeeds after the original CIF is deleted.

- [ ] **Step 3: Run application-level smoke checks**

Open a saved `.xpff` in an isolated/empty local phase-cache setup and confirm:

- each pattern restores its own phase list;
- the shared phase is available to every linked pattern;
- calculated profiles and phase markers appear automatically;
- renaming a phase remains possible;
- the phase is not added to the global USER database or project tree unless the user explicitly requests it;
- saving the reopened project again remains portable.

- [ ] **Step 4: Review the diff for scope and compatibility**

Run:

```powershell
git diff origin/main HEAD -- XRD_Finder/xrd_finder/core/finder_state.py XRD_Finder/xrd_finder/io/project_io.py XRD_Finder/xrd_finder/ui/project_state_actions.py XRD_Finder/xrd_finder/ui/candidate_structure_actions.py XRD_Finder/tests/test_portable_project_io.py XRD_Finder/tests/test_portable_candidate_state.py
```

Confirm there are no unrelated edits, no network access during Save, and no automatic USER-library mutation.

- [ ] **Step 5: Record final verification evidence**

Report the exact test count, the test command, and any manual limitation. Do not publish a release or push until the user explicitly asks after verifying the built application.
