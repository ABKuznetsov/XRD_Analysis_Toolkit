# Standalone XRD Phase Finder 1.6.0 Design

## Goal

Create a clean standalone XRD Phase Finder project at:

```text
/Users/artem/Yandex.Disk.localized/Python/XRD/XRD phase finder
```

The new project becomes the working home for Finder 1.6.0. It should contain the current Finder application, its launch/update/install tooling, focused tests, and minimal user/developer documentation, without CRAFT, old XRD Manager modules, manuscript work, release debris, caches, local databases, or historical scaffolding.

The current directories remain untouched during the migration:

```text
/Users/artem/Yandex.Disk.localized/Python/XRD/XRD_Analysis_Toolkit
/Users/artem/Yandex.Disk.localized/Python/XRD/finder
```

Deleting those directories is a later explicit cleanup step after the standalone project launches and packages correctly.

## Non-Goals

- Do not migrate CRAFT into the new Finder project.
- Do not keep the old Toolkit as a nested dependency of the new project.
- Do not publish to GitHub or PyPI during the migration unless explicitly requested.
- Do not copy COD/RRUFF/PDF/user cache data into the new repository or installer.
- Do not rewrite the Finder UI or search pipeline as part of the split.
- Do not delete the old Toolkit or old finder folder in the same step as migration.

## Source Of Truth

The migration copies the current working tree state of Finder, not only the last Git commit. The current repository contains uncommitted Finder work that must be preserved. Copying must therefore use an allowlist of paths from the filesystem, not `git archive HEAD`.

Only Finder-owned files are copied. Generated package outputs, caches, local databases, manuscript folders, and deleted/legacy modules are not carried over.

## Target Layout

Use a flat standalone Python project:

```text
XRD phase finder/
├─ xrd_finder/
├─ tests/
├─ scripts/
├─ installer/
├─ launcher/
├─ assets/
├─ docs/
├─ pyproject.toml
├─ requirements.txt
├─ requirements-dev.txt
├─ README.md
├─ CHANGELOG.md
├─ LICENSE
└─ RELEASE_NOTES_1.6.0.md
```

### `xrd_finder/`

Copied from `XRD_Finder/xrd_finder`. This is the application package. It remains importable as:

```python
import xrd_finder
```

The version becomes `1.6.0` in all runtime-visible places.

### `tests/`

Focused Finder tests are copied from `XRD_Finder/tests`. Tests stay in the repository but are excluded from release payloads and macOS/Windows installers.

### `scripts/`

Build and maintenance scripts are copied only if they are still relevant to Finder. Release scripts must use strict allowlists.

### `installer/`

Installer assets for Windows and macOS are kept here. The macOS package builder should produce an installable Finder package without docs, tests, old release archives, caches, local data, manuscript work, or CRAFT.

### `launcher/`

This contains startup/update/runtime-check code that used to live under the broader Toolkit boundary. Finder uses it directly so the installed app can start, repair/check its runtime, and check for updates without requiring the old Toolkit folder.

Temporary compatibility is allowed: update metadata may still point to the current `XRD_Analysis_Toolkit` GitHub release endpoint until the new Finder repository exists. This must be documented clearly in the release notes. Before a public 1.6.x release from the new repository, update URLs should be switched to the new repository.

### `assets/`

Only assets required by the app, installers, launchers, and minimal examples are copied. Local scientific datasets, user databases, cache folders, generated screenshots, manuscripts, and draft figures are excluded.

### `docs/`

Keep only user/developer docs that explain Finder operation, project format, install/update behavior, and release maintenance. Superpowers planning docs may remain in the old Toolkit repo and do not need to be copied unless they describe active Finder contracts.

## Path And Import Rules

- Replace assumptions that the runtime package lives under `XRD_Finder/`.
- Remove references that require the parent `XRD_Analysis_Toolkit` folder.
- Keep `xrd_finder` as the Python package name.
- Keep user data outside the source tree through the existing cache/user-data path logic.
- Keep project files portable and independent of the old repository path.
- Do not introduce CRAFT imports or CRAFT launch/update entries.

Any remaining string reference to `XRD_Analysis_Toolkit` must be either a documented temporary update endpoint or a migration note. Any remaining string reference to CRAFT in runtime or installer code is a migration failure.

## Versioning

Set the standalone snapshot to `1.6.0` consistently in:

```text
pyproject.toml
xrd_finder/__init__.py
app/update metadata
Windows installer metadata
macOS package metadata
runtime manifests
release notes
```

The new project starts with a fresh Git history. The first commit should represent the clean Finder 1.6.0 standalone baseline.

## Release Payload Rules

The macOS `.pkg`, Windows installer, and portable archive must include only the runtime material needed by users:

```text
xrd_finder/
launcher/runtime files
requirements / app metadata
installer-required icons and scripts
minimal README / license / third-party notices
```

They must exclude:

```text
.git/
__pycache__/
*.pyc
.DS_Store
__MACOSX/
tests/
docs/superpowers/
manuscript_assets/
manuscript_work/
data/cod_cache/
data/rruff_cache/
local/generated databases
dist/
build/
CRAFT
xrd_manager
old Finder release archives
```

## Migration Steps

1. Confirm target folder is empty or contains only disposable migration scratch files.
2. Copy allowlisted Finder files from the current Toolkit tree.
3. Flatten `XRD_Finder/xrd_finder` to `xrd_finder`.
4. Move Finder tests to top-level `tests`.
5. Move launch/update/runtime helpers to `launcher`.
6. Update path references for the new flat layout.
7. Set version to `1.6.0`.
8. Initialize a new Git repository in the target folder.
9. Run focused verification.
10. Build a clean macOS `.pkg`.
11. Launch Finder from the new folder.
12. Commit the clean standalone baseline.
13. Ask for manual verification before removing old folders.

## Verification

Run focused checks, not the full historical test corpus:

```text
python -m compileall xrd_finder
python -m pytest tests/test_runtime_requirements.py
python -m pytest tests/test_cristma_powder_adapter.py
python -m pytest tests/test_instrument_profile_models.py
python -m pytest tests/test_instrument_calculation_context.py
python -m pytest tests/test_peak_intensity_sticks.py
python -m pytest tests/test_runtime_requirements.py tests/test_windows_bootstrap.py
```

Also verify:

```text
Finder starts from the new folder.
macOS package builds from the new folder.
Package payload contains no tests, docs, caches, CRAFT, or old Toolkit files.
Instrument profile changes refresh calculated lines/profiles/match state.
Visible peak markers still appear on every displayed XRD pattern.
```

If a focused test is missing after the copy, replace it with the nearest current equivalent rather than broadening to the full suite.

## Rollback And Safety

The old Toolkit remains available until the new project is manually accepted. No destructive cleanup is part of the migration. If the new project fails to launch, fix the standalone project or discard it; do not mutate the old Toolkit to recover.

## Acceptance Criteria

- `XRD phase finder` contains a standalone Finder 1.6.0 project.
- The app launches from the new project path.
- A macOS `.pkg` builds from the new project path.
- Package payload audit is clean.
- No runtime CRAFT or XRD Manager files remain in the standalone Finder.
- User data and local phase caches are created outside the source tree.
- The new Git repository has an initial clean commit.
- Old folders are still present until the user explicitly approves deletion.
