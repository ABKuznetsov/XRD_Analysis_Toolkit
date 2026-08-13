# English Startup Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every notification and feature card in the Windows 1.4.0 startup experience English-only.

**Architecture:** Keep the existing PowerShell UI and JSON card architecture unchanged. Enforce the language boundary with one focused source-level regression test covering the four user-facing startup resources.

**Tech Stack:** PowerShell, JSON, Python `unittest`, Inno Setup.

## Global Constraints

- Do not change the main application UI or scientific behavior.
- Do not translate paths, package names, product terms, or third-party output.
- Preserve all startup and installation behavior.

---

### Task 1: English-only startup contract

**Files:**
- Modify: `XRD_Finder/tests/test_first_run_showcase.py`
- Modify: `XRD_Finder/tests/test_windows_file_association.py`
- Create: `XRD_Finder/tests/test_english_startup_copy.py`

**Interfaces:**
- Consumes: UTF-8 source text from the four startup resources.
- Produces: a failing regression test when required English startup copy is missing.

- [ ] Write assertions for the seven English card titles, English performance notice, runtime buttons, and primary startup messages.
- [ ] Run the focused tests and confirm they fail on the existing Russian strings.

### Task 2: Translate startup resources

**Files:**
- Modify: `toolkit/first_run_showcase.ps1`
- Modify: `toolkit/showcase/showcase.json`
- Modify: `toolkit/sci_runtime_setup_ui.ps1`
- Modify: `toolkit/launch_xrd_finder_preview.ps1`

**Interfaces:**
- Consumes: existing runtime details, paths, card images, and progress values.
- Produces: English-only labels and messages with unchanged control flow.

- [ ] Replace Russian static UI copy with concise English equivalents.
- [ ] Run the focused tests and confirm they pass.
- [ ] Confirm the required English labels are present in all four scoped files.

### Task 3: Publish the corrected installer

**Files:**
- Modify: `toolkit/manifest.json`
- Modify: `toolkit/updates/xrd_finder.json`
- Build: `installer/output/XRD_Phase_Finder_Setup_1.4.0.exe`

**Interfaces:**
- Consumes: translated startup resources.
- Produces: a verified Windows installer and matching release metadata.

- [ ] Build the Inno Setup installer.
- [ ] Compute SHA-256 and size and update both manifests.
- [ ] Commit and push the exact scoped changes to `main`.
- [ ] Replace the GitHub release asset and verify its downloaded SHA-256.
