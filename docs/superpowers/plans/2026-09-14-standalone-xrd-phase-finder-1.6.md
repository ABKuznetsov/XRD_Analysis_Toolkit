# Standalone XRD Phase Finder 1.6.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean standalone XRD Phase Finder 1.6.0 project in `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder`.

**Architecture:** The new project is a flat Python application repo with `xrd_finder/` at the root, focused tests in `tests/`, release/install tooling in `scripts/` and `installer/`, and startup/update tooling in `launcher/`. The migration copies the current working tree state through an allowlist, then rewrites paths and metadata so Finder no longer depends on the old `XRD_Analysis_Toolkit` layout.

**Tech Stack:** Python, PySide6, NumPy/SciPy, pyqtgraph, pybaselines, CrIStMa, shell/batch launchers, macOS `pkgbuild`/`productbuild`, Windows installer scripts.

**Spec:** `docs/superpowers/specs/2026-09-14-standalone-xrd-phase-finder-1.6-design.md`

## Global Constraints

- Target root: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder`.
- Source root: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD_Analysis_Toolkit`.
- Preserve the current working tree state, including uncommitted Finder files.
- Use an allowlist copy, not a full repository copy.
- Version must be `1.6.0` in runtime, installer, and metadata files.
- Do not copy CRAFT, XRD Manager, old Toolkit app glue, local databases, cache folders, manuscripts, package output, or old release archives.
- Do not delete `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD_Analysis_Toolkit`.
- Do not delete `/Users/artem/Yandex.Disk.localized/Python/XRD/finder`.
- Old GitHub update endpoints may remain only as documented temporary compatibility references.
- Any runtime or installer reference to CRAFT is a migration failure.
- Any required write under `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder` needs filesystem approval if the sandbox blocks it.

---

### Task 1: Target Guardrails And Allowlist

**Files:**
- Create: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/MIGRATION_SOURCE.txt`
- Create: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/.gitignore`
- Read: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD_Analysis_Toolkit/docs/superpowers/specs/2026-09-14-standalone-xrd-phase-finder-1.6-design.md`

**Interfaces:**
- Consumes: Source root and target root paths from the spec.
- Produces: An empty guarded target root and a documented migration source marker.

- [ ] **Step 1: Verify target folder is safe to populate**

Run:

```bash
TARGET="/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder"
find "$TARGET" -mindepth 1 -maxdepth 1 -print
```

Expected: no output. If output appears, stop and list the files before modifying anything.

- [ ] **Step 2: Create the target root metadata**

Create `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/MIGRATION_SOURCE.txt` with:

```text
Standalone XRD Phase Finder 1.6.0

Created from:
/Users/artem/Yandex.Disk.localized/Python/XRD/XRD_Analysis_Toolkit

Copy mode:
working tree allowlist

Old folders are intentionally preserved until manual verification:
/Users/artem/Yandex.Disk.localized/Python/XRD/XRD_Analysis_Toolkit
/Users/artem/Yandex.Disk.localized/Python/XRD/finder
```

- [ ] **Step 3: Create standalone `.gitignore`**

Create `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/.gitignore` with:

```gitignore
__pycache__/
*.py[cod]
*.pyo
.Python
.DS_Store
__MACOSX/
.venv/
venv/
build/
dist/
*.egg-info/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
data/
cod_cache/
rruff_cache/
*.sqlite
*.sqlite3
*.db
runtime_install.log
runtime_repair.log
*.pkg
*.zip
*.7z
```

- [ ] **Step 4: Verify no Git repo was initialized yet**

Run:

```bash
test ! -d "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/.git"
```

Expected: exit code `0`.

---

### Task 2: Copy Finder Runtime Into Flat Layout

**Files:**
- Copy: `XRD_Finder/xrd_finder/` to `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/xrd_finder/`
- Copy: `XRD_Finder/tests/` to `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/tests/`
- Copy: `XRD_Finder/requirements.txt` to `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/requirements.txt`
- Copy: `XRD_Finder/requirements-dev.txt` to `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/requirements-dev.txt`
- Copy: `LICENSE`, `README.md`, `CHANGELOG.md`, `THIRD_PARTY_DATA_SOURCES.md`, `MANIFEST.in`, `pyproject.toml`
- Copy: Finder-only root launch/repair scripts after path review.

**Interfaces:**
- Consumes: Source tree Finder files.
- Produces: A flat importable `xrd_finder` package and top-level `tests`.

- [ ] **Step 1: Copy runtime package**

Run from the source root:

```bash
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  XRD_Finder/xrd_finder/ \
  "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/xrd_finder/"
```

Expected: target contains `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/xrd_finder/__init__.py`.

- [ ] **Step 2: Copy focused tests**

Run:

```bash
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  XRD_Finder/tests/ \
  "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/tests/"
```

Expected: target contains `tests/test_runtime_requirements.py` and the CrIStMa/instrument profile tests currently present in source.

- [ ] **Step 3: Copy requirements and top-level metadata**

Run:

```bash
cp XRD_Finder/requirements.txt "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/requirements.txt"
cp XRD_Finder/requirements-dev.txt "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/requirements-dev.txt"
cp LICENSE README.md CHANGELOG.md THIRD_PARTY_DATA_SOURCES.md MANIFEST.in pyproject.toml "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/"
```

Expected: all listed files exist at target root.

- [ ] **Step 4: Copy Finder launch and repair scripts**

Copy only scripts that start or repair Finder:

```bash
cp XRD_Finder/run_finder.command "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/run_finder.command"
cp install_xrd_finder_windows_runtime.bat "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/install_xrd_finder_windows_runtime.bat"
cp repair_xrd_finder_windows_runtime.bat "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/repair_xrd_finder_windows_runtime.bat"
cp XRD_Finder/install_windows_runtime_direct.bat "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/install_windows_runtime_direct.bat"
```

Expected: no CRAFT launcher is copied.

- [ ] **Step 5: Verify forbidden directories are absent**

Run in target:

```bash
find . -maxdepth 4 \( -name CRAFT -o -name xrd_manager -o -name cod_cache -o -name rruff_cache -o -name manuscript_assets -o -name manuscript_work \) -print
```

Expected: no output.

---

### Task 3: Copy Release Tooling And Launcher Boundary

**Files:**
- Copy: Finder-relevant `scripts/` files to target `scripts/`
- Copy: Finder-relevant `installer/` files to target `installer/`
- Create: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/launcher/`
- Move/adapt: Toolkit runtime/update metadata needed by Finder into target `launcher/`

**Interfaces:**
- Consumes: Current macOS pkg builder, Windows installer scripts, update metadata.
- Produces: Standalone release tooling that does not require the old Toolkit root.

- [ ] **Step 1: Copy scripts with allowlist**

Run:

```bash
mkdir -p "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/scripts"
cp scripts/build_macos_dmg.command "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/scripts/" 2>/dev/null || true
cp scripts/build_macos_pkg.command "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/scripts/" 2>/dev/null || true
cp scripts/build_release_archive.py "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/scripts/" 2>/dev/null || true
cp scripts/build_portable_archive.py "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/scripts/" 2>/dev/null || true
```

Expected: only existing Finder-relevant scripts are copied; missing optional scripts do not fail the task.

- [ ] **Step 2: Copy installer folder with exclusions**

Run:

```bash
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'build/' \
  --exclude 'dist/' \
  installer/ \
  "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/installer/"
```

Expected: installer files exist and no CRAFT installer files remain after Task 5 cleanup.

- [ ] **Step 3: Copy launcher/update metadata into `launcher/`**

Run:

```bash
mkdir -p "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/launcher/updates"
cp toolkit/manifest.json "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/launcher/manifest.json"
cp toolkit/catalog.json "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/launcher/catalog.json" 2>/dev/null || true
cp toolkit/updates/xrd_finder.json "/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/launcher/updates/xrd_finder.json"
```

Expected: Finder update metadata is present without old Toolkit runtime code being required at launch.

- [ ] **Step 4: Remove copied non-Finder installer/runtime references**

Run in target:

```bash
rg -n "CRAFT|Craft|xrd_manager|XRD Manager" installer launcher scripts || true
```

Expected: if matches appear, delete or rewrite the referenced non-Finder files in Task 5.

---

### Task 4: Rewrite Paths, Version, And Entry Points

**Files:**
- Modify: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/pyproject.toml`
- Modify: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/xrd_finder/__init__.py`
- Modify: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/run_finder.command`
- Modify: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/launcher/manifest.json`
- Modify: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/launcher/updates/xrd_finder.json`
- Modify: Windows installer/runtime scripts copied to target
- Modify: macOS package builder copied to target
- Create: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/RELEASE_NOTES_1.6.0.md`

**Interfaces:**
- Consumes: Flat target layout from Tasks 2 and 3.
- Produces: Standalone version `1.6.0` and launch scripts that work from target root.

- [ ] **Step 1: Set package version to 1.6.0**

Edit `pyproject.toml` so the project version is:

```toml
version = "1.6.0"
```

Edit `xrd_finder/__init__.py` so the runtime version is:

```python
__version__ = "1.6.0"
```

- [ ] **Step 2: Rewrite macOS launcher for flat root**

Edit `run_finder.command` so it computes the project root from its own location and starts:

```bash
cd "$SCRIPT_DIR"
python3 -m xrd_finder.apps.finder_gui
```

If the script creates or activates `.venv`, keep that behavior and point it at `"$SCRIPT_DIR/.venv"`.

- [ ] **Step 3: Rewrite update metadata**

Set Finder metadata in `launcher/manifest.json` and `launcher/updates/xrd_finder.json` to `1.6.0`. Keep any old GitHub release URL only in the Finder update entry and add this note in `RELEASE_NOTES_1.6.0.md`:

```text
Temporary update compatibility: this standalone migration may still read update metadata from the previous XRD_Analysis_Toolkit release endpoint until the new Finder repository is published.
```

- [ ] **Step 4: Rewrite build scripts for flat root**

In target `scripts/`, replace path assumptions like:

```text
XRD_Finder/xrd_finder
XRD_Finder/run_finder.command
```

with:

```text
xrd_finder
run_finder.command
```

Keep payload allowlists strict.

- [ ] **Step 5: Verify old root references**

Run in target:

```bash
rg -n "XRD_Analysis_Toolkit|XRD_Finder/|/XRD_Finder|CRAFT|xrd_manager|XRD Manager" .
```

Expected: only documented migration notes or temporary update endpoint references remain. Runtime Python, launcher, installer, and package-builder files must not require those old paths.

---

### Task 5: Clean Release Payload Rules

**Files:**
- Modify: target macOS package build script under `scripts/`
- Modify: target Windows installer config under `installer/`
- Modify: target portable archive script if present
- Test: package payload inspection command output

**Interfaces:**
- Consumes: Updated flat paths from Task 4.
- Produces: `.pkg` and portable payload logic that excludes dev/test/cache material.

- [ ] **Step 1: Ensure macOS package allowlist includes runtime only**

The package staging list must include:

```text
xrd_finder/
launcher/
requirements.txt
README.md
LICENSE
THIRD_PARTY_DATA_SOURCES.md
run_finder.command
```

It must not include:

```text
tests/
docs/
manuscript_assets/
manuscript_work/
data/
dist/
build/
*.pkg
*.zip
```

- [ ] **Step 2: Ensure Windows installer metadata targets Finder only**

In the target Windows installer files, verify that app name, version, and paths refer to:

```text
XRD Phase Finder
1.6.0
xrd_finder
```

Expected: no CRAFT, XRD Manager, or old Toolkit application entries.

- [ ] **Step 3: Build macOS package**

Run in target:

```bash
scripts/build_macos_pkg.command
```

Expected: a Finder `.pkg` with version `1.6.0` is created under target `dist/` or the script's documented output directory.

- [ ] **Step 4: Inspect macOS package payload**

Run:

```bash
PKG="$(find dist -name '*.pkg' -print | sort | tail -n 1)"
pkgutil --payload-files "$PKG" | rg "tests/|docs/superpowers|manuscript|cod_cache|rruff_cache|CRAFT|xrd_manager|__pycache__|\\.pyc" || true
```

Expected: no forbidden payload paths.

---

### Task 6: Focused Runtime Verification

**Files:**
- Read/execute: target `xrd_finder/`
- Read/execute: target `tests/`
- Read/execute: target `run_finder.command`

**Interfaces:**
- Consumes: Migrated target project.
- Produces: Evidence that the standalone app imports, tests, builds, and launches.

- [ ] **Step 1: Compile runtime package**

Run in target:

```bash
python3 -m compileall xrd_finder
```

Expected: no compile errors.

- [ ] **Step 2: Run focused tests**

Run in target:

```bash
python3 -m pytest \
  tests/test_runtime_requirements.py \
  tests/test_cristma_powder_adapter.py \
  tests/test_instrument_profile_models.py \
  tests/test_instrument_calculation_context.py \
  tests/test_peak_intensity_sticks.py \
  tests/test_windows_bootstrap.py
```

Expected: all selected tests pass. If one named test does not exist after migration, run `rg -n "runtime|cristma|instrument|peak|windows" tests` and choose the closest current equivalent.

- [ ] **Step 3: Run import smoke**

Run in target:

```bash
python3 -c "import xrd_finder; print(xrd_finder.__version__)"
```

Expected output:

```text
1.6.0
```

- [ ] **Step 4: Launch Finder from target**

Run:

```bash
"/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/run_finder.command"
```

Expected: the Finder UI opens. On macOS, harmless `TSMSendMessageToUIServer` messages do not fail the check if the UI opens.

- [ ] **Step 5: Manual visual check**

Use the launched UI to verify:

```text
Project tree appears.
Top toolbar appears.
Right panel Elements / Processing / Card tabs appear.
Instrument profile dialog opens.
Changing instrument profile refreshes calculated lines/profiles/match state.
Peak markers appear on all displayed patterns after loading and after adding phases.
```

---

### Task 7: Initialize Standalone Git Repository

**Files:**
- Create: `/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder/.git/`
- Commit: all clean standalone project files

**Interfaces:**
- Consumes: Verified standalone target.
- Produces: Fresh Git repo with an initial Finder 1.6.0 baseline commit.

- [ ] **Step 1: Initialize Git**

Run in target:

```bash
git init
git add .
git status --short
```

Expected: only intended standalone Finder files are staged or ready to stage.

- [ ] **Step 2: Inspect staged file list**

Run:

```bash
git diff --cached --name-only | rg "CRAFT|xrd_manager|cod_cache|rruff_cache|manuscript|__pycache__|\\.pyc|\\.pkg|\\.zip|dist/|build/" || true
```

Expected: no forbidden files.

- [ ] **Step 3: Commit baseline**

Run:

```bash
git commit -m "chore: create standalone XRD Phase Finder 1.6.0"
```

Expected: initial commit succeeds.

- [ ] **Step 4: Final status**

Run:

```bash
git status --short
```

Expected: clean or only ignored generated files such as `dist/`.

---

### Task 8: Final Handoff And Old Folder Hold

**Files:**
- Read: new project package output
- Read: new Git status
- Do not modify: old Toolkit folder
- Do not modify: old finder folder

**Interfaces:**
- Consumes: Verified new standalone project and package.
- Produces: User-facing summary and explicit hold before destructive cleanup.

- [ ] **Step 1: Report artifacts**

Report:

```text
New project path
Git commit hash
Package path
Package size
SHA256 hash
Focused test result
Launch result
```

- [ ] **Step 2: Ask for manual installation check**

Ask the user to test the generated package and the new folder launch.

- [ ] **Step 3: Hold deletion**

Do not delete:

```text
/Users/artem/Yandex.Disk.localized/Python/XRD/XRD_Analysis_Toolkit
/Users/artem/Yandex.Disk.localized/Python/XRD/finder
```

Deletion needs a separate explicit user approval after manual verification.

---

## Self-Review

Spec coverage:

- Clean standalone target is covered by Tasks 1, 2, and 7.
- Current working tree preservation is covered by Task 2 allowlist copy.
- CRAFT/XRD Manager exclusion is covered by Tasks 2, 3, 4, 5, and 7.
- Version `1.6.0` is covered by Task 4.
- Package cleanliness is covered by Task 5.
- Runtime launch and focused checks are covered by Task 6.
- Old folder deletion hold is covered by Task 8.

Placeholder scan:

- The plan contains no placeholder markers or unspecified implementation steps.
- Optional script copy uses `2>/dev/null || true` only for scripts that may not exist in the source tree; the expected result is explicit.

Type and path consistency:

- Source root and target root match the spec.
- Python package name remains `xrd_finder`.
- Target version is consistently `1.6.0`.
