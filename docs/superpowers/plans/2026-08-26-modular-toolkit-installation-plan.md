# Modular XRD Toolkit Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add XRD CRAFT to the repository as an independent application and let Finder and CRAFT discover and explicitly install other XRD tools through a verified shared catalogue, without introducing a common installer.

**Architecture:** `toolkit/catalog.json` is the only shared discovery contract. Finder and CRAFT each keep a small local catalogue client, their own UI entry point, installer, updater manifest, version, installation directory, and dependency validation. Catalogue installers are downloaded to a per-user cache, checked by size and SHA-256, confirmed by the user, and then launched independently.

**Tech Stack:** Python 3.11, PySide6, pytest, PowerShell, Inno Setup 6, JSON, SHA-256, GitHub Releases.

**Spec:** [2026-08-26-modular-toolkit-installer-design.md](../specs/2026-08-26-modular-toolkit-installer-design.md)

## Global Constraints

- Preserve every unrelated dirty or untracked file already present in the Finder worktree.
- Do not move or merge Finder and CRAFT internals.
- Do not create a combined installer or a shared `Program Files` application directory.
- Preserve Finder at `C:\Program Files\XRD Phase Finder`, CRAFT at `%LocalAppData%\Sci\apps\craft`, and the shared environment at `%LocalAppData%\Sci\env`.
- Never delete or rebuild a working Sci environment as part of module installation.
- Do not download or run another application's installer without explicit user action and final confirmation.
- Never execute an installer whose byte size or SHA-256 differs from the catalogue.
- Keep all startup, installer, catalogue, and failure copy in English.
- Do not mention internal SCI Manager compatibility in release notes.
- Finder release version is `1.5.0`; CRAFT release version is `0.1.0`.
- Commit only files belonging to the current task; use path-scoped `git add`.

## File and Responsibility Map

- `toolkit/catalog.json`: cross-application discovery contract.
- `toolkit/updates/xrd_finder.json`: Finder updater contract.
- `toolkit/updates/xrd_craft.json`: CRAFT updater contract.
- `XRD_Finder/xrd_finder/services/toolkit_catalog.py`: Finder catalogue parsing, cache validation, and download service.
- `XRD_Finder/xrd_finder/ui/toolkit_catalog_dialog.py`: Finder catalogue cards, confirmation, progress, Retry/Cancel, and one-time announcement state.
- `XRD_Finder/xrd_finder/ui/toolkit_catalog_actions.py`: Finder window integration and background worker ownership.
- `XRD_Finder/xrd_finder/ui/analysis_windows.py`: compose the catalogue action mixin into `PhaseFinderWindow`.
- `XRD_Finder/xrd_finder/ui/phase_finder_menu.py`: permanent `More XRD tools…` Help action.
- `XRD_Craft/src/crystal_viewer/services/toolkit_catalog.py`: CRAFT-local implementation of the same catalogue contract.
- `XRD_Craft/src/crystal_viewer/ui/toolkit_catalog_dialog.py`: CRAFT catalogue UI and installer workflow.
- `XRD_Craft/src/crystal_viewer/ui/main_window.py`: permanent Help action and one-time announcement scheduling.
- `installer/finder_setup/XRD_Phase_Finder.iss`: Finder standalone installer source.
- `installer/craft_setup/CRAFT.iss`: CRAFT standalone installer source.
- `installer/finder_setup/build_installer.bat`, `installer/craft_setup/build_installer.bat`: reproducible module builds.

---

### Task 1: Import a curated XRD CRAFT source tree

**Files:**

- Create: `XRD_Craft/src/**`
- Create: `XRD_Craft/assets/**`
- Create: `XRD_Craft/examples/**`
- Create: `XRD_Craft/tests/**`
- Create: `XRD_Craft/toolkit/setup_sci_env.bat`
- Create: `XRD_Craft/toolkit/requirements-windows.txt`
- Create: `XRD_Craft/pyproject.toml`
- Create: `XRD_Craft/README.md`
- Create: `XRD_Craft/ARCHITECTURE.md`
- Create: `XRD_Craft/run_viewer.bat`
- Create: `XRD_Craft/run_viewer_silent.vbs`
- Create: `XRD_Craft/run_viewer.command`
- Modify: `.gitignore`
- Create: `XRD_Craft/tests/test_repository_payload.py`

**Step 1: Write the failing payload test**

Add a test that resolves the `XRD_Craft` root and asserts that `src/crystal_viewer/app.py`, `assets`, `examples`, `pyproject.toml`, and runtime setup files exist. It must recursively reject `dist`, `build`, `.pytest_cache`, `__pycache__`, `*.pyc`, `*.pyo`, `*.exe`, virtual environments, and `docs/superpowers`.

Run:

```powershell
pytest XRD_Craft/tests/test_repository_payload.py -q
```

Expected: FAIL because the curated module does not exist yet.

**Step 2: Copy only the approved payload**

Copy the source project's runtime source, assets, examples, tests, metadata, launchers, and required runtime scripts from `C:\Users\Artem\Documents\disk\Yandex.Disk\Python\XRD\вивер`. Do not copy generated binaries, caches, local environments, temporary files, or internal plans. Extend `.gitignore` with module-local generated paths.

**Step 3: Verify the curated tree**

Run:

```powershell
pytest XRD_Craft/tests/test_repository_payload.py -q
python -m compileall -q XRD_Craft/src
```

Expected: PASS, with no generated files tracked.

**Step 4: Commit**

```powershell
git add .gitignore XRD_Craft
git commit -m "feat: add curated XRD CRAFT module"
```

---

### Task 2: Define and validate the toolkit catalogue contracts

**Files:**

- Create: `toolkit/catalog.json`
- Create: `toolkit/updates/xrd_craft.json`
- Modify: `toolkit/updates/xrd_finder.json`
- Create: `scripts/validate_toolkit_catalog.py`
- Create: `XRD_Finder/tests/test_toolkit_catalog_manifest.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class CatalogInstaller:
    url: str
    filename: str
    size_bytes: int
    sha256: str

@dataclass(frozen=True)
class CatalogApplication:
    app_id: str
    name: str
    description: str
    version: str
    announcement_revision: int
    platforms: tuple[str, ...]
    architectures: tuple[str, ...]
    update_manifest_url: str
    installer: CatalogInstaller

def validate_catalog(payload: Mapping[str, Any]) -> list[str]: ...
```

**Step 1: Write manifest contract tests**

Test schema version `1`, unique `app_id`, Finder `1.5.0`, CRAFT `0.1.0`, HTTPS URLs, Windows/x86_64 support, 64-character lowercase SHA-256, positive sizes, and independent update manifests. During development, permit the explicit all-zero hash only when `--allow-unbuilt` is passed to the validation script; tests for release mode must reject it.

Run:

```powershell
pytest XRD_Finder/tests/test_toolkit_catalog_manifest.py -q
```

Expected: FAIL because the catalogue and CRAFT update manifest are absent.

**Step 2: Implement the validator and JSON contracts**

Create catalogue entries `xrd_finder` and `xrd_craft`. Use GitHub release URLs for the eventual `v1.5.0` assets and independent update manifest URLs. Add `announcement_revision: 1` for CRAFT. Keep release asset size and hash as explicit build-time placeholders accepted only by `--allow-unbuilt`.

**Step 3: Verify development contracts**

Run:

```powershell
python scripts/validate_toolkit_catalog.py toolkit/catalog.json --allow-unbuilt
pytest XRD_Finder/tests/test_toolkit_catalog_manifest.py -q
```

Expected: PASS for development mode and documented failure in strict mode until installers are built.

**Step 4: Commit**

```powershell
git add toolkit/catalog.json toolkit/updates/xrd_finder.json toolkit/updates/xrd_craft.json scripts/validate_toolkit_catalog.py XRD_Finder/tests/test_toolkit_catalog_manifest.py
git commit -m "feat: define toolkit application catalogue"
```

---

### Task 3: Implement Finder's verified catalogue service

**Files:**

- Create: `XRD_Finder/xrd_finder/services/toolkit_catalog.py`
- Create: `XRD_Finder/tests/test_toolkit_catalog_service.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ToolkitApplication:
    app_id: str
    name: str
    description: str
    version: str
    announcement_revision: int
    installer_url: str
    installer_filename: str
    installer_sha256: str
    installer_size_bytes: int

def parse_catalog(payload: Mapping[str, Any], *, current_app_id: str) -> tuple[ToolkitApplication, ...]: ...
def cached_installer_path(app: ToolkitApplication, cache_root: Path) -> Path: ...
def installer_is_valid(path: Path, app: ToolkitApplication) -> bool: ...
def download_installer(
    app: ToolkitApplication,
    cache_root: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> Path: ...
```

**Step 1: Write failing service tests**

Cover parsing, exclusion of the current application, deterministic cache paths, reuse of a valid cache file, rejection and deletion of a mismatched complete file, atomic `.part` download, progress callbacks, and preservation of a valid completed download across retries. Use in-memory fake responses; tests must not access the network.

Run:

```powershell
pytest XRD_Finder/tests/test_toolkit_catalog_service.py -q
```

Expected: FAIL because the service does not exist.

**Step 2: Implement the minimal service**

Use `%LocalAppData%\Sci\downloads\toolkit` as the default cache. Stream in 1 MiB chunks to `<filename>.part`, flush and close, check exact size and SHA-256, then atomically replace the final path. Never return an unverified file. Raise typed `CatalogUnavailableError`, `InstallerIntegrityError`, and `InstallerDownloadError` with English actionable messages.

**Step 3: Verify the service**

Run:

```powershell
pytest XRD_Finder/tests/test_toolkit_catalog_service.py -q
```

Expected: PASS.

**Step 4: Commit**

```powershell
git add XRD_Finder/xrd_finder/services/toolkit_catalog.py XRD_Finder/tests/test_toolkit_catalog_service.py
git commit -m "feat: add verified toolkit download service"
```

---

### Task 4: Add Finder catalogue UI and one-time CRAFT discovery

**Files:**

- Create: `XRD_Finder/xrd_finder/ui/toolkit_catalog_dialog.py`
- Create: `XRD_Finder/xrd_finder/ui/toolkit_catalog_actions.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Modify: `XRD_Finder/xrd_finder/ui/phase_finder_menu.py`
- Create: `XRD_Finder/tests/test_toolkit_catalog_ui.py`

**Interfaces:**

```python
class ToolkitCatalogWorker(QObject):
    progress = Signal(int, int)
    downloaded = Signal(Path)
    failed = Signal(str)

class ToolkitCatalogDialog(QDialog):
    install_requested = Signal(ToolkitApplication)
    not_now_requested = Signal(ToolkitApplication)

class PhaseFinderToolkitCatalogActionsMixin:
    def _open_toolkit_catalog(self) -> None: ...
    def _schedule_toolkit_announcement(self) -> None: ...
    def _install_toolkit_application(self, app: ToolkitApplication) -> None: ...
```

**Step 1: Write failing UI tests**

With `QT_QPA_PLATFORM=offscreen`, verify that Help contains `More XRD tools…`, the dialogue excludes Finder, `Not now` stores `toolkit/announcements/xrd_craft = 1`, the same revision is not offered again, a higher revision is offered, download runs off the GUI thread, and a final confirmation appears before `subprocess.Popen` is called. Patch the process launcher; tests must never run an installer.

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest XRD_Finder/tests/test_toolkit_catalog_ui.py -q
```

Expected: FAIL because no catalogue UI is connected.

**Step 2: Implement UI and window integration**

Add the mixin before `AnalysisWindow` in `PhaseFinderWindow`. Add the permanent Help action through `build_phase_finder_menu_bar(owner)`. Schedule one-time discovery with `QTimer.singleShot(0, ...)` after window construction so startup stays responsive. Use a `QThread` worker for catalogue fetch and installer download. On download completion, ask `Install XRD CRAFT now?`; only an affirmative response launches the verified installer. Display module name, exit/start error, and cache or log path in English.

**Step 3: Verify UI behavior**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest XRD_Finder/tests/test_toolkit_catalog_ui.py -q
```

Expected: PASS.

**Step 4: Commit**

```powershell
git add XRD_Finder/xrd_finder/ui/toolkit_catalog_dialog.py XRD_Finder/xrd_finder/ui/toolkit_catalog_actions.py XRD_Finder/xrd_finder/ui/analysis_windows.py XRD_Finder/xrd_finder/ui/phase_finder_menu.py XRD_Finder/tests/test_toolkit_catalog_ui.py
git commit -m "feat: expose XRD tools catalogue in Finder"
```

---

### Task 5: Add the same discovery contract to CRAFT without coupling applications

**Files:**

- Create: `XRD_Craft/src/crystal_viewer/services/toolkit_catalog.py`
- Create: `XRD_Craft/src/crystal_viewer/ui/toolkit_catalog_dialog.py`
- Modify: `XRD_Craft/src/crystal_viewer/ui/main_window.py`
- Create: `XRD_Craft/tests/test_toolkit_catalog_service.py`
- Create: `XRD_Craft/tests/test_toolkit_catalog_ui.py`

**Step 1: Write failing CRAFT tests**

Reuse the JSON fixtures from the Finder tests as copied test data, not imports from the Finder package. Verify that CRAFT excludes `xrd_craft`, offers Finder, validates installer bytes, stores announcement revisions under CRAFT's own `QSettings` namespace, and adds `More XRD tools…` to the existing Help menu built by `MainWindow._build_actions()`.

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest XRD_Craft/tests/test_toolkit_catalog_service.py XRD_Craft/tests/test_toolkit_catalog_ui.py -q
```

Expected: FAIL because CRAFT has no catalogue client.

**Step 2: Implement CRAFT-local service and UI**

Implement the same schema and download safety locally so CRAFT never imports `xrd_finder`. Sharing is through JSON only. Add the permanent Help action and one-time announcement with CRAFT's settings namespace. Use the same cache root so verified installers can be reused.

**Step 3: Verify independence**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest XRD_Craft/tests/test_toolkit_catalog_service.py XRD_Craft/tests/test_toolkit_catalog_ui.py -q
rg -n "xrd_finder" XRD_Craft/src
```

Expected: tests PASS and `rg` returns no Python dependency from CRAFT to Finder.

**Step 4: Commit**

```powershell
git add XRD_Craft/src/crystal_viewer/services/toolkit_catalog.py XRD_Craft/src/crystal_viewer/ui/toolkit_catalog_dialog.py XRD_Craft/src/crystal_viewer/ui/main_window.py XRD_Craft/tests/test_toolkit_catalog_service.py XRD_Craft/tests/test_toolkit_catalog_ui.py
git commit -m "feat: expose toolkit catalogue in CRAFT"
```

---

### Task 6: Add CRAFT's independent automatic update check

**Files:**

- Create: `XRD_Craft/src/crystal_viewer/services/application_updates.py`
- Create: `XRD_Craft/src/crystal_viewer/ui/application_update_dialog.py`
- Modify: `XRD_Craft/src/crystal_viewer/ui/main_window.py`
- Create: `XRD_Craft/tests/test_application_updates.py`
- Create: `XRD_Craft/tests/test_application_update_ui.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ApplicationUpdate:
    version: str
    release_notes: str
    installer_url: str
    installer_filename: str
    installer_size_bytes: int
    installer_sha256: str

def compare_versions(left: str, right: str) -> int: ...
def parse_update_manifest(payload: Mapping[str, Any], *, current_version: str) -> ApplicationUpdate | None: ...

class ApplicationUpdateController(QObject):
    update_available = Signal(ApplicationUpdate)
    check_failed = Signal(str)
    download_progress = Signal(int, int)
    installer_ready = Signal(Path)

    def check_in_background(self, *, interactive: bool = False) -> None: ...
    def download_update(self, update: ApplicationUpdate) -> None: ...
```

**Step 1: Write failing update-service tests**

Cover semantic version ordering, no result for the current or an older version, valid update parsing, malformed manifests, exact size and lowercase SHA-256 validation, cache reuse, and checksum mismatch. Reuse the verified-download primitive within CRAFT rather than adding a second unsafe downloader. Use fake HTTP responses only.

Run:

```powershell
pytest XRD_Craft/tests/test_application_updates.py -q
```

Expected: FAIL because CRAFT has no self-updater.

**Step 2: Write failing UI tests**

With `QT_QPA_PLATFORM=offscreen`, verify that `MainWindow._build_actions()` adds `Check for updates…` under Help, the startup check is scheduled after the main window is shown, the check and download do not block the GUI thread, a network failure during a silent startup check does not show a modal error or stop CRAFT, an interactive check reports `CRAFT is up to date`, and an available update requires confirmation before download and again before launching the installer. Patch `subprocess.Popen`; tests must never run a real installer.

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest XRD_Craft/tests/test_application_update_ui.py -q
```

Expected: FAIL because the Help action and controller do not exist.

**Step 3: Implement the independent updater**

Fetch only `toolkit/updates/xrd_craft.json`. Compare it against `crystal_viewer.__version__`. Use a worker thread for both check and download. Silent startup failures go to the status bar and diagnostic log; interactive failures show an English actionable dialogue. Download to `%LocalAppData%\Sci\downloads\updates\craft`, verify size and SHA-256, and never execute invalid bytes. After final confirmation, launch the CRAFT installer independently; Finder is never called or updated.

**Step 4: Verify CRAFT updates**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest XRD_Craft/tests/test_application_updates.py XRD_Craft/tests/test_application_update_ui.py -q
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add XRD_Craft/src/crystal_viewer/services/application_updates.py XRD_Craft/src/crystal_viewer/ui/application_update_dialog.py XRD_Craft/src/crystal_viewer/ui/main_window.py XRD_Craft/tests/test_application_updates.py XRD_Craft/tests/test_application_update_ui.py
git commit -m "feat: add independent CRAFT updater"
```

---

### Task 7: Build independent installers that preserve the shared Sci environment

**Files:**

- Create: `installer/finder_setup/XRD_Phase_Finder.iss`
- Create: `installer/finder_setup/build_installer.bat`
- Create: `installer/craft_setup/CRAFT.iss`
- Create: `installer/craft_setup/build_installer.bat`
- Modify: `XRD_Craft/toolkit/setup_sci_env.bat`
- Modify: `XRD_Craft/toolkit/requirements-windows.txt`
- Modify: `XRD_Craft/tests/test_windows_installer_contract.py`
- Create: `XRD_Finder/tests/test_modular_installer_contract.py`

**Step 1: Write failing installer contract tests**

Assert Finder `DefaultDirName={autopf}\XRD Phase Finder`, CRAFT `DefaultDirName={localappdata}\Sci\apps\craft`, CRAFT `PrivilegesRequired=lowest`, independent uninstall identities, no shared-app directory, no Sci-env deletion in uninstall sections, `.xpff` ownership only in Finder, and runtime scripts that install only missing/incompatible requirements. Assert both installer scripts exclude caches, bytecode, build output, tests, and development documents.

Run:

```powershell
pytest XRD_Finder/tests/test_modular_installer_contract.py XRD_Craft/tests/test_windows_installer_contract.py -q
```

Expected: FAIL until installer sources are split and curated.

**Step 2: Implement the module installers**

Move the Finder installer source into `installer/finder_setup` without changing its install location or `.xpff` behavior. Create the CRAFT installer from its existing per-user installer contract. Runtime setup must first import and version-check only that module's requirements, repair failed requirements individually with visible English status and Retry/Cancel, and leave all valid packages intact.

**Step 3: Verify contracts**

Run:

```powershell
pytest XRD_Finder/tests/test_modular_installer_contract.py XRD_Craft/tests/test_windows_installer_contract.py -q
```

Expected: PASS.

**Step 4: Commit**

```powershell
git add installer/finder_setup installer/craft_setup XRD_Craft/toolkit XRD_Craft/tests/test_windows_installer_contract.py XRD_Finder/tests/test_modular_installer_contract.py
git commit -m "build: add independent Finder and CRAFT installers"
```

---

### Task 8: Prepare Finder 1.5.0 and CRAFT 0.1.0 release metadata

**Files:**

- Modify: `pyproject.toml`
- Modify: `XRD_Craft/pyproject.toml`
- Modify: `XRD_Craft/src/crystal_viewer/__init__.py`
- Create: `XRD_Finder/RELEASE_NOTES_1.5.0.md`
- Create: `XRD_Craft/RELEASE_NOTES_0.1.0.md`
- Modify: `toolkit/manifest.json`
- Modify: `toolkit/updates/xrd_finder.json`
- Modify: `toolkit/updates/xrd_craft.json`
- Modify: `toolkit/catalog.json`
- Create: `XRD_Finder/tests/test_release_versions.py`

**Step 1: Write failing version-consistency tests**

Assert Finder version `1.5.0` agrees across `pyproject.toml`, installer, update manifest, and release notes. Assert CRAFT version `0.1.0` agrees across package metadata, `__version__`, installer, update manifest, and release notes. Assert notes describe modular discovery, independent installation, performance, and reliability without mentioning SCI Manager.

Run:

```powershell
pytest XRD_Finder/tests/test_release_versions.py -q
```

Expected: FAIL because metadata is not synchronized.

**Step 2: Synchronize versions and notes**

Patch only the version fields in the already-dirty root `pyproject.toml`; preserve unrelated dependency and export changes. Write concise English user-facing release notes. Leave installer hashes and sizes pending the actual build.

**Step 3: Verify metadata except binary hashes**

Run:

```powershell
pytest XRD_Finder/tests/test_release_versions.py -q
python scripts/validate_toolkit_catalog.py toolkit/catalog.json --allow-unbuilt
```

Expected: PASS.

**Step 4: Commit only release metadata**

```powershell
git add pyproject.toml XRD_Craft/pyproject.toml XRD_Craft/src/crystal_viewer/__init__.py XRD_Finder/RELEASE_NOTES_1.5.0.md XRD_Craft/RELEASE_NOTES_0.1.0.md toolkit/manifest.json toolkit/updates/xrd_finder.json toolkit/updates/xrd_craft.json toolkit/catalog.json XRD_Finder/tests/test_release_versions.py
git commit -m "chore: prepare Finder 1.5.0 and CRAFT 0.1.0"
```

---

### Task 9: Build, hash, smoke-test, and publish both standalone releases

**Files:**

- Modify: `toolkit/catalog.json`
- Modify: `toolkit/updates/xrd_finder.json`
- Modify: `toolkit/updates/xrd_craft.json`
- Create: release assets in ignored `dist/releases/`

**Step 1: Run focused and full automated verification**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
pytest XRD_Finder/tests/test_toolkit_catalog_manifest.py XRD_Finder/tests/test_toolkit_catalog_service.py XRD_Finder/tests/test_toolkit_catalog_ui.py XRD_Finder/tests/test_modular_installer_contract.py XRD_Finder/tests/test_release_versions.py -q
pytest XRD_Craft/tests/test_repository_payload.py XRD_Craft/tests/test_toolkit_catalog_service.py XRD_Craft/tests/test_toolkit_catalog_ui.py XRD_Craft/tests/test_windows_installer_contract.py -q
pytest XRD_Craft/tests/test_application_updates.py XRD_Craft/tests/test_application_update_ui.py -q
pytest XRD_Finder/tests -q
pytest XRD_Craft/tests -q
```

Expected: PASS. Do not modify scientific behavior to silence unrelated failures; report pre-existing failures separately.

**Step 2: Build both installers**

Run the two build scripts with Inno Setup 6. Expected artefacts:

```text
dist/releases/XRD_Phase_Finder_Setup_1.5.0.exe
dist/releases/CRAFT_Setup_0.1.0.exe
```

**Step 3: Insert exact release metadata**

Compute each asset's byte size and lowercase SHA-256. Replace build-time placeholders in the catalogue and the corresponding update manifests. Run strict validation:

```powershell
python scripts/validate_toolkit_catalog.py toolkit/catalog.json
pytest XRD_Finder/tests/test_toolkit_catalog_manifest.py XRD_Finder/tests/test_release_versions.py -q
```

Expected: PASS with no placeholder hashes.

**Step 4: Manual smoke test**

On Windows, verify:

1. Finder 1.4.1 updates in place to 1.5.0 and still opens `.xpff`.
2. CRAFT installs under `%LocalAppData%\Sci\apps\craft` and launches.
3. CRAFT checks `toolkit/updates/xrd_craft.json` in the background, offers its newer standalone installer, and `Check for updates…` reports current status interactively.
4. Finder's `More XRD tools…` offers CRAFT once, `Not now` suppresses revision `1`, and Install launches only the verified CRAFT installer.
5. CRAFT can offer Finder without importing or updating it automatically.
6. Closing or cancelling either installer leaves the current application working.
7. Installing either application leaves the other application's files and `%LocalAppData%\Sci\env` intact.

**Step 5: Commit final hashes**

```powershell
git add toolkit/catalog.json toolkit/updates/xrd_finder.json toolkit/updates/xrd_craft.json
git commit -m "build: finalize modular release checksums"
```

**Step 6: Publish**

Push the branch, create GitHub release `v1.5.0`, attach both installer assets, and verify the remote assets and manifests. Do not upload source caches or an obsolete combined installer.

```powershell
git push
gh release create v1.5.0 dist/releases/XRD_Phase_Finder_Setup_1.5.0.exe dist/releases/CRAFT_Setup_0.1.0.exe --title "XRD Phase Finder 1.5.0 and XRD CRAFT 0.1.0" --notes-file XRD_Finder/RELEASE_NOTES_1.5.0.md
gh release view v1.5.0
```

Expected: the release exposes two independent installers and no common bootstrapper.

## Final Verification Checklist

- Every approved spec requirement is represented in Tasks 1–9.
- No task contains `TODO`, `TBD`, placeholder implementation logic, or an unspecified path.
- Finder and CRAFT share JSON schema and cache conventions, not Python imports.
- Catalogue, discovery UI, CRAFT self-update, installer, runtime, version, hash, and release contracts are each tested.
- Dirty Finder export/runtime edits are preserved and excluded from unrelated commits.
- User actions remain explicit at download, confirmation, and installer launch boundaries.
