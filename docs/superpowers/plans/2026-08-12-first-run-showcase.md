# First-run Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a consent-driven, console-free scientific-runtime installer with real progress and a screenshot-based first-run XRD Phase Finder showcase.

**Architecture:** Split the current startup PowerShell script into a showcase module and a runtime-setup UI module while leaving the launcher as orchestration. Package curated screenshots under `toolkit/showcase`, keep installation permission and failure recovery in one modal startup experience, and persist a versioned one-time marker for existing users.

**Tech Stack:** Windows PowerShell 5.1, WinForms, Inno Setup, Python `unittest` contract tests.

## Global Constraints

- Runtime lives under `%LocalAppData%\Sci`.
- Do not display a command-line window during environment setup.
- Do not install or repair anything before explicit user confirmation.
- New-user installation showcase cannot be skipped while setup is running.
- Ready-runtime 1.4.0 showcase is shown once and can be skipped.
- Runtime success is determined by executing the existing import probe, not file existence alone.
- Do not modify scientific Match, Gain, profile, or quantification logic.

---

### Task 1: Package showcase assets and manifest

**Files:**
- Create: `toolkit/showcase/showcase.json`
- Create: `toolkit/showcase/*.png`
- Test: `XRD_Finder/tests/test_first_run_showcase.py`

**Interfaces:**
- Produces: a UTF-8 JSON array with `id`, `title`, `description`, `image`, and optional `notice` fields consumed by `Load-ShowcaseCards`.

- [ ] **Step 1: Write the failing asset-contract test**

Assert that seven cards exist in the required order, all image paths resolve, titles start with the approved action verbs, and the performance notice mentions both the visible operation window and status bar.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m unittest XRD_Finder.tests.test_first_run_showcase.FirstRunShowcaseTests.test_assets`

- [ ] **Step 3: Copy and crop the selected screenshots**

Use the six supplied screenshots plus article figures `amor.png`, `gel na.png`, and `multi.jpg`. Preserve originals; place only resized/cropped derivatives in `toolkit/showcase`.

- [ ] **Step 4: Create `showcase.json`**

Add the seven cards specified in the design. Keep each description to one sentence and store the slowdown warning only once.

- [ ] **Step 5: Run the focused test and verify it passes**

Run the command from Step 2 and expect `OK`.

### Task 2: Implement the reusable showcase module

**Files:**
- Create: `toolkit/first_run_showcase.ps1`
- Test: `XRD_Finder/tests/test_first_run_showcase.py`

**Interfaces:**
- Produces: `Initialize-FirstRunShowcase`, `Set-ShowcaseMode`, `Set-ShowcaseInstallationComplete`, `Save-ShowcaseSeenMarker`, and `Dispose-FirstRunShowcase`.
- Consumes: `toolkit/showcase/showcase.json`, a parent WinForms control, mode `Installing|Ready`, and marker version `1.4.0`.

- [ ] **Step 1: Add failing static contract tests**

Verify module functions, a 4.5-second timer, previous/next navigation, skip visibility only in `Ready` mode, image disposal, and marker path below `%LocalAppData%\Sci\XRD_Finder`.

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m unittest XRD_Finder.tests.test_first_run_showcase`

- [ ] **Step 3: Implement card loading and rendering**

Create the image panel, title, description, optional warning, arrows, page dots, timer, and aspect-preserving image display. Dispose the previous image before loading another.

- [ ] **Step 4: Implement mode rules and marker persistence**

In `Installing`, hide Skip and ignore window-close requests while a process is active. In `Ready`, expose Skip and write `showcase-1.4.0.seen` after skip or completion.

- [ ] **Step 5: Run the focused tests and verify pass**

Run the command from Step 2 and expect `OK`.

### Task 3: Implement consent-driven runtime repair UI

**Files:**
- Create: `toolkit/sci_runtime_setup_ui.ps1`
- Modify: `toolkit/launch_xrd_finder_preview.ps1`
- Test: `XRD_Finder/tests/test_windows_file_association.py`

**Interfaces:**
- Produces: `Show-RuntimeConsent`, `Invoke-VisibleSciRuntimeRepair`, `Show-RuntimeSetupFailure`.
- Consumes: the existing `Test-SciRuntime`, `setup_sci_env.bat`, setup log path, and callbacks for progress text and package status.

- [ ] **Step 1: Extend failing launcher-contract tests**

Require dot-sourcing of both modules, no automatic setup before `Show-RuntimeConsent`, hidden `cmd.exe`, failure buttons `Повторить`, `Открыть журнал`, `Закрыть`, and no installer `[Run]` entry for `setup_sci_env.bat`.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m unittest XRD_Finder.tests.test_windows_file_association`

- [ ] **Step 3: Move runtime UI and setup monitoring out of the launcher**

Parse the existing setup log for package name and `N/M`; show indeterminate progress when unavailable. Run the batch file with `-WindowStyle Hidden`. Use `Start-Process` for opening the log only after a user click.

- [ ] **Step 4: Wire consent, retry, and verification into startup**

Probe first, render the exact failure details, wait for consent, enter installing showcase mode, run setup, and probe again. On failure, remain in the same window and allow retry/log/close. Launch the GUI only after readiness.

- [ ] **Step 5: Run the focused test and PowerShell parser**

Run the test from Step 2. Parse all three `.ps1` files with `System.Management.Automation.Language.Parser` and expect zero syntax errors.

### Task 4: Integrate the one-time ready-runtime showcase

**Files:**
- Modify: `toolkit/launch_xrd_finder_preview.ps1`
- Test: `XRD_Finder/tests/test_first_run_showcase.py`

**Interfaces:**
- Consumes: `Initialize-FirstRunShowcase -Mode Ready -Version 1.4.0`.
- Produces: startup behavior that waits only when the versioned marker is absent.

- [ ] **Step 1: Add failing marker-flow tests**

Require a versioned marker, a ready-runtime first-run branch, Skip support, and no showcase delay when the marker exists.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m unittest XRD_Finder.tests.test_first_run_showcase`

- [ ] **Step 3: Implement ready-runtime flow**

Show the cards before normal GUI launch only when `showcase-1.4.0.seen` is absent. Continue after Skip or final-card completion and save the marker.

- [ ] **Step 4: Handle installation completion**

If setup ends early, show `Запустить XRD Phase Finder`; if cards end first, continue cycling until setup succeeds.

- [ ] **Step 5: Run focused startup tests**

Run both focused unittest modules and expect `OK`.

### Task 5: Build and release verification

**Files:**
- Modify after build: `toolkit/manifest.json`
- Modify after build: `toolkit/updates/xrd_finder.json`
- Build: `installer/output/XRD_Phase_Finder_Setup_1.4.0.exe`

**Interfaces:**
- Produces: a signed-off 1.4.0 installer asset and matching SHA-256/size metadata.

- [ ] **Step 1: Run focused verification**

Run the two showcase/runtime tests and PowerShell parser. Do not run unrelated scientific benchmark suites.

- [ ] **Step 2: Build the installer**

Run: `installer\build_installer.bat`

- [ ] **Step 3: Update release metadata**

Calculate SHA-256 and byte size of the installer and update both JSON manifests.

- [ ] **Step 4: Verify packaged files and manifest hashes**

Confirm the installer is non-empty, both runtime modules, the JSON manifest, and all seven card images are included by the Inno Setup file rule, and both hash fields match the artifact.

- [ ] **Step 5: Commit and publish 1.4.0**

Stage only intended source, asset, installer metadata, spec, and plan files. Push the fast-forward release branch/tag and upload the installer to the GitHub 1.4.0 release with product-focused notes that do not mention SCI Manager compatibility.
