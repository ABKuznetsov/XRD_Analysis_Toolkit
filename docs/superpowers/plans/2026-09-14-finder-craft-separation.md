# Finder and CRAFT Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to execute this plan.

**Goal:** Remove XRD CRAFT and every Finder-side installation/discovery link to it from `XRD_Analysis_Toolkit`, while preserving a working Finder-only repository and producing a verified macOS installer for the current Finder version.

**Architecture:** `XRD_Analysis_Toolkit` becomes the release repository for XRD Phase Finder only. Finder keeps its own runtime bootstrap, update manifests, `.xpff` integration, databases, CrIStMa-backed calculations and platform installers; CRAFT source, packaging, update metadata and companion-app UI are removed. Repository contract tests and package-payload guards prevent CRAFT from being accidentally bundled again.

**Tech Stack:** Python 3.11/3.12, pytest, PySide6, JSON manifests, Inno Setup, PowerShell, zsh, `rsync`, Apple `pkgbuild`/`productbuild`/`pkgutil`.

---

## File Map

**Delete completely**

- `XRD_Craft/`
- `installer/craft_setup/`
- `dist/CRAFT_macOS_1.0.1.pkg`
- `dist/craft_macos_pkg_build/`
- `toolkit/updates/xrd_craft.json`
- `toolkit/install_companion_app.ps1`
- `XRD_Finder/xrd_finder/services/toolkit_catalog.py`
- `XRD_Finder/xrd_finder/ui/toolkit_catalog_actions.py`
- `XRD_Finder/xrd_finder/ui/toolkit_catalog_dialog.py`
- `XRD_Finder/tests/test_toolkit_catalog_service.py`
- `XRD_Finder/tests/test_toolkit_catalog_ui.py`
- `docs/superpowers/specs/2026-08-26-modular-toolkit-installer-design.md`
- `docs/superpowers/plans/2026-08-26-modular-toolkit-installation-plan.md`

**Modify**

- `toolkit/catalog.json`: retain only the `xrd_finder` application entry.
- `installer/finder_setup/XRD_Phase_Finder.iss`: remove the optional CRAFT task, download command and installation probe.
- `XRD_Finder/xrd_finder/ui/phase_finder_menu.py`: remove `More XRD tools...`.
- `XRD_Finder/xrd_finder/ui/analysis_windows.py`: remove the toolkit-catalog mixin and startup announcement.
- `XRD_Finder/tests/test_toolkit_catalog_manifest.py`: validate a Finder-only catalog and Finder update manifest.
- `XRD_Finder/tests/test_modular_installer_contract.py`: assert that the Finder installer has no companion-app behavior.
- `XRD_Finder/tests/test_release_versions.py`: retain only Finder version and release-note contracts.
- `XRD_Finder/tests/test_macos_pkg_payload.py`: require explicit Finder-only exclusions and payload validation.
- `scripts/build_macos_pkg.command`: defensively exclude and reject CRAFT paths in the staged payload.
- `toolkit/updates/xrd_finder.json`: update the rebuilt macOS package size and SHA-256.
- `toolkit/manifest.json`: update the rebuilt macOS package SHA-256.

**Create**

- `XRD_Finder/tests/test_finder_only_repository.py`: repository-level regression contract for removed CRAFT surfaces.

## Task 1: Lock the Finder-only Repository Contract

**Files:**

- Create: `XRD_Finder/tests/test_finder_only_repository.py`
- Modify: `XRD_Finder/tests/test_toolkit_catalog_manifest.py`
- Modify: `XRD_Finder/tests/test_modular_installer_contract.py`
- Modify: `XRD_Finder/tests/test_release_versions.py`

- [ ] **Step 1: Add a failing repository-boundary test**

Create `XRD_Finder/tests/test_finder_only_repository.py` with explicit forbidden paths and release-surface checks:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_craft_source_and_release_surfaces_are_absent() -> None:
    forbidden = (
        "XRD_Craft",
        "installer/craft_setup",
        "toolkit/install_companion_app.ps1",
        "toolkit/updates/xrd_craft.json",
        "dist/CRAFT_macOS_1.0.1.pkg",
        "dist/craft_macos_pkg_build",
    )

    assert [path for path in forbidden if (ROOT / path).exists()] == []


def test_finder_release_surfaces_do_not_reference_craft() -> None:
    paths = (
        ROOT / "installer/finder_setup/XRD_Phase_Finder.iss",
        ROOT / "toolkit/catalog.json",
        ROOT / "XRD_Finder/xrd_finder/ui/phase_finder_menu.py",
        ROOT / "XRD_Finder/xrd_finder/ui/analysis_windows.py",
    )
    forbidden_tokens = ("xrd_craft", "xrd craft", "crystal_viewer")

    for path in paths:
        source = path.read_text(encoding="utf-8-sig").casefold()
        assert all(token not in source for token in forbidden_tokens), path
```

- [ ] **Step 2: Convert existing catalog tests to a single Finder entry**

In `test_toolkit_catalog_manifest.py`, replace the two-application assertion and two-manifest loop with:

```python
applications = {entry["app_id"]: entry for entry in catalog["applications"]}
assert set(applications) == {"xrd_finder"}
assert applications["xrd_finder"]["version"] == version
assert applications["xrd_finder"]["update_manifest_url"].endswith(
    "/toolkit/updates/xrd_finder.json"
)
```

Read `version` from `pyproject.toml`; do not add a second hard-coded release version.

- [ ] **Step 3: Convert installer and version tests to Finder-only assertions**

In `test_modular_installer_contract.py`, delete the positive CRAFT offer/loader tests and add:

```python
def test_finder_installer_has_no_companion_application_task() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig").casefold()

    for token in ("installcraft", "xrd_craft", "xrd craft", "install_companion_app"):
        assert token not in source
```

In `test_release_versions.py`, remove `test_craft_release_version_is_consistent` and make the release-note theme test read only the current Finder release notes.

- [ ] **Step 4: Run the focused contract tests and confirm they fail for the current mixed repository**

Run:

```bash
.venv/bin/python -m pytest -q \
  XRD_Finder/tests/test_finder_only_repository.py \
  XRD_Finder/tests/test_toolkit_catalog_manifest.py \
  XRD_Finder/tests/test_modular_installer_contract.py \
  XRD_Finder/tests/test_release_versions.py
```

Expected: failures identify the existing `XRD_Craft`, companion installer, catalog entry and CRAFT release checks.

- [ ] **Step 5: Commit only the contract-test changes**

```bash
git add \
  XRD_Finder/tests/test_finder_only_repository.py \
  XRD_Finder/tests/test_toolkit_catalog_manifest.py \
  XRD_Finder/tests/test_modular_installer_contract.py \
  XRD_Finder/tests/test_release_versions.py
git commit -m "test: define Finder-only release boundary"
```

## Task 2: Remove CRAFT Source, Packaging and Historical Combined-Installer Docs

**Files:**

- Delete: `XRD_Craft/`
- Delete: `installer/craft_setup/`
- Delete: `dist/CRAFT_macOS_1.0.1.pkg`
- Delete: `dist/craft_macos_pkg_build/`
- Delete: `toolkit/updates/xrd_craft.json`
- Delete: `docs/superpowers/specs/2026-08-26-modular-toolkit-installer-design.md`
- Delete: `docs/superpowers/plans/2026-08-26-modular-toolkit-installation-plan.md`

- [ ] **Step 1: Remove the approved CRAFT-owned trees and artifacts**

Remove exactly the paths listed above. Do not touch the external future CRAFT repository, Finder code, Finder installers or shared Sci runtime scripts.

- [ ] **Step 2: Confirm no CRAFT implementation remains outside the current separation documents**

Run:

```bash
rg -n -i "xrd[_ -]?craft|crystal_viewer" \
  XRD_Finder installer toolkit scripts pyproject.toml .github || true
```

Expected: only the still-to-be-removed Finder companion integration from Task 3; no `XRD_Craft/`, CRAFT installer or CRAFT update manifest.

- [ ] **Step 3: Commit only the approved deletions**

```bash
git add -A -- \
  XRD_Craft \
  installer/craft_setup \
  toolkit/updates/xrd_craft.json \
  docs/superpowers/specs/2026-08-26-modular-toolkit-installer-design.md \
  docs/superpowers/plans/2026-08-26-modular-toolkit-installation-plan.md
git commit -m "chore: remove CRAFT from Finder repository"
```

The ignored `dist/` deletions are verified locally but are not committed.

## Task 3: Remove Finder-side CRAFT Discovery and Installation

**Files:**

- Delete: `toolkit/install_companion_app.ps1`
- Delete: `XRD_Finder/xrd_finder/services/toolkit_catalog.py`
- Delete: `XRD_Finder/xrd_finder/ui/toolkit_catalog_actions.py`
- Delete: `XRD_Finder/xrd_finder/ui/toolkit_catalog_dialog.py`
- Delete: `XRD_Finder/tests/test_toolkit_catalog_service.py`
- Delete: `XRD_Finder/tests/test_toolkit_catalog_ui.py`
- Modify: `toolkit/catalog.json`
- Modify: `installer/finder_setup/XRD_Phase_Finder.iss`
- Modify: `XRD_Finder/xrd_finder/ui/phase_finder_menu.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`

- [ ] **Step 1: Make the public catalog Finder-only**

Retain the current `xrd_finder` object and remove only the `xrd_craft` object. Keep `schema_version`, repository URL, Finder installer URL, size, SHA-256 and update manifest unchanged.

- [ ] **Step 2: Remove the optional companion task from the Windows installer**

Delete from `XRD_Phase_Finder.iss`:

- the CRAFT-specific `[Messages]` text;
- `installcraft` from `[Tasks]`;
- the CRAFT PowerShell command from `[Run]`;
- the entire `CraftIsInstalled` function and now-empty `[Code]` section.

Keep the desktop shortcut, Finder files, toolkit runtime files, `.xpff` registration, updater and Finder launch action unchanged.

- [ ] **Step 3: Remove the companion catalog from Finder UI startup and Help**

In `phase_finder_menu.py`, remove only the `More XRD tools...` action.

In `analysis_windows.py`, remove:

```python
from xrd_finder.ui.toolkit_catalog_actions import PhaseFinderToolkitCatalogActionsMixin
```

the mixin from `PhaseFinderWindow`, and:

```python
self._schedule_toolkit_announcement()
```

Do not alter the current toolbar, instrument-profile, CrIStMa, Match/Gain or plotting changes in those files.

- [ ] **Step 4: Delete the now-unreachable companion implementation and its dedicated tests**

Delete the service, actions mixin, dialog, PowerShell loader and the two catalog UI/service test files listed above.

- [ ] **Step 5: Run the focused Finder-only contract tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  XRD_Finder/tests/test_finder_only_repository.py \
  XRD_Finder/tests/test_toolkit_catalog_manifest.py \
  XRD_Finder/tests/test_modular_installer_contract.py \
  XRD_Finder/tests/test_release_versions.py
```

Expected: all tests pass.

- [ ] **Step 6: Run focused import and menu smoke tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  XRD_Finder/tests/test_phase_finder_settings_layout.py
```

Also extend `test_menu_actions_open_separate_settings_windows` in that file to assert that the Help menu has no `More XRD tools...` action. Do not create a broad GUI test suite for this cleanup.

- [ ] **Step 7: Commit the Finder-side separation**

```bash
git add -A -- \
  toolkit/catalog.json \
  toolkit/install_companion_app.ps1 \
  installer/finder_setup/XRD_Phase_Finder.iss \
  XRD_Finder/xrd_finder/services/toolkit_catalog.py \
  XRD_Finder/xrd_finder/ui/toolkit_catalog_actions.py \
  XRD_Finder/xrd_finder/ui/toolkit_catalog_dialog.py \
  XRD_Finder/xrd_finder/ui/phase_finder_menu.py \
  XRD_Finder/xrd_finder/ui/analysis_windows.py \
  XRD_Finder/tests/test_toolkit_catalog_service.py \
  XRD_Finder/tests/test_toolkit_catalog_ui.py
git commit -m "refactor: make Finder distribution standalone"
```

## Task 4: Guard the macOS Package Against CRAFT Payloads

**Files:**

- Modify: `scripts/build_macos_pkg.command`
- Modify: `XRD_Finder/tests/test_macos_pkg_payload.py`

- [ ] **Step 1: Add failing package-guard assertions**

Extend `test_macos_pkg_payload.py`:

```python
def test_macos_pkg_explicitly_rejects_craft_payload() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '--exclude "XRD_Craft/"' in script
    assert '--exclude "installer/craft_setup/"' in script
    assert "Forbidden CRAFT payload" in script
```

- [ ] **Step 2: Run the package test and confirm the new test fails**

Run:

```bash
.venv/bin/python -m pytest -q XRD_Finder/tests/test_macos_pkg_payload.py
```

Expected: failure because the defensive package checks are not present yet.

- [ ] **Step 3: Add defensive exclusions and a staged-payload check**

Add these `rsync` exclusions to `build_macos_pkg.command` even though the directories are removed from the repository:

```zsh
--exclude "XRD_Craft/" \
--exclude "installer/craft_setup/" \
```

Immediately after `rsync`, fail the build if any path containing the removed product names appears in the staged application payload:

```zsh
FORBIDDEN_PAYLOAD="$(find "$APP_PAYLOAD_DIR" \
    \( -iname '*xrd_craft*' -o -iname '*xrd craft*' -o -iname '*crystal_viewer*' \) \
    -print -quit)"
if [ -n "$FORBIDDEN_PAYLOAD" ]; then
    echo "Forbidden CRAFT payload in Finder package: $FORBIDDEN_PAYLOAD"
    exit 1
fi
```

- [ ] **Step 4: Run focused package and runtime-manifest tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  XRD_Finder/tests/test_macos_pkg_payload.py \
  XRD_Finder/tests/test_macos_preview_offline.py \
  XRD_Finder/tests/test_runtime_requirements.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit the package guard**

```bash
git add scripts/build_macos_pkg.command XRD_Finder/tests/test_macos_pkg_payload.py
git commit -m "build: keep CRAFT out of Finder package"
```

## Task 5: Build and Verify the Current Finder macOS Installer

**Files:**

- Build ignored artifact: `dist/XRD_Phase_Finder_macOS_<version>.pkg`
- Modify: `toolkit/updates/xrd_finder.json`
- Modify: `toolkit/manifest.json`

- [ ] **Step 1: Read the version from project metadata and build the package**

Run:

```bash
scripts/build_macos_pkg.command
```

Expected output ends with the absolute package path, currently `dist/XRD_Phase_Finder_macOS_1.5.0.pkg` while the project version remains `1.5.0`.

- [ ] **Step 2: Expand the built package and inspect its payload**

Run:

```bash
rm -rf /tmp/xrd-finder-pkg-inspect
pkgutil --expand-full \
  "dist/XRD_Phase_Finder_macOS_1.5.0.pkg" \
  /tmp/xrd-finder-pkg-inspect
find /tmp/xrd-finder-pkg-inspect -iname '*craft*' -o -iname '*crystal_viewer*'
rg -n -i "xrd[_ -]?craft|crystal_viewer" /tmp/xrd-finder-pkg-inspect || true
```

Expected: both CRAFT searches return no matches. Confirm that `Applications/XRD Phase Finder.app` and the Finder launcher are present.

- [ ] **Step 3: Record size and SHA-256 and update Finder manifests**

Run:

```bash
stat -f '%z' "dist/XRD_Phase_Finder_macOS_1.5.0.pkg"
shasum -a 256 "dist/XRD_Phase_Finder_macOS_1.5.0.pkg"
```

Update the macOS asset `size_bytes` and `sha256` in `toolkit/updates/xrd_finder.json`, and the matching `macos_installer_sha256` in both `toolkit/updates/xrd_finder.json` and `toolkit/manifest.json`. Do not modify Windows asset metadata.

- [ ] **Step 4: Validate only the release surfaces affected by this cleanup**

Run:

```bash
.venv/bin/python -m pytest -q \
  XRD_Finder/tests/test_finder_only_repository.py \
  XRD_Finder/tests/test_toolkit_catalog_manifest.py \
  XRD_Finder/tests/test_modular_installer_contract.py \
  XRD_Finder/tests/test_macos_pkg_payload.py \
  XRD_Finder/tests/test_macos_preview_offline.py \
  XRD_Finder/tests/test_macos_release_manifest.py \
  XRD_Finder/tests/test_release_versions.py \
  XRD_Finder/tests/test_runtime_requirements.py
```

Expected: all focused release tests pass. Do not run the full scientific/GUI suite for this packaging-only cleanup.

- [ ] **Step 5: Perform the final repository audit**

Run:

```bash
rg -n -i "xrd[_ -]?craft|crystal_viewer" \
  XRD_Finder installer toolkit pyproject.toml .github || true
rg -n -i "xrd[_ -]?craft|crystal_viewer" scripts/build_macos_pkg.command
git status --short
```

Expected: no CRAFT references in active Finder/release surfaces; the build script contains only the deliberate defensive exclusion and rejection checks. Existing unrelated Finder changes remain untouched and visible in `git status`.

- [ ] **Step 6: Commit only rebuilt package metadata**

```bash
git add toolkit/updates/xrd_finder.json toolkit/manifest.json
git commit -m "release: refresh Finder macOS package metadata"
```

- [ ] **Step 7: Report the installer artifact**

Report:

- absolute `.pkg` path;
- Finder version;
- byte size and human-readable size;
- SHA-256;
- package-content audit result;
- focused test result;
- confirmation that CRAFT was removed only from `XRD_Analysis_Toolkit` and no external CRAFT project was touched.
