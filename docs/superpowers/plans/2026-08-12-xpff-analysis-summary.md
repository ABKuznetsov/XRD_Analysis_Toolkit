# XPFF Analysis Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the portable `.xpff` container with a versioned, reproducible XRD analysis summary that SCI Manager can read without repeating scientific calculations.

**Architecture:** XRD Phase Finder remains the sole producer of scientific results. A focused `analysis_summary` module builds and validates the public contract, computes an RFC 8785/JCS SHA-256 over the agreed scientific projection, and stores snapshots already produced by Match/Gain. Portable project I/O embeds the summary and preview assets while preserving all existing XRD/CIF/state content.

**Tech Stack:** Python 3.11, dataclasses, `rfc8785`, ZIP `.xpff`, unittest/pytest.

## Global Constraints

- `.xpff` remains fully portable and backward compatible.
- Match, Gain, peak assignment, and quantification algorithms are not changed.
- `result_sha256` excludes `analysis_id`, `result_sha256`, `revision_id`, `generated_at`, `preview_path`, images, and `sample_ref`.
- Arrays are sorted deterministically before JCS: phases and phase references by `phase_id`, patterns by `pattern_id`, unknown peaks by `two_theta` then `intensity`.
- Missing scientific values are `null`; NaN and Infinity are rejected.
- SCI Manager integration is a separate implementation plan after the producer contract is complete.

---

### Task 1: Canonical scientific-result hashing

**Files:**
- Create: `XRD_Finder/xrd_finder/io/analysis_summary.py`
- Create: `XRD_Finder/tests/test_analysis_summary_hash.py`
- Modify: `pyproject.toml`
- Modify: `XRD_Finder/requirements.txt`

**Interfaces:**
- Produces: `scientific_projection(summary: Mapping[str, Any]) -> dict[str, Any]`
- Produces: `compute_result_sha256(summary: Mapping[str, Any]) -> str`

- [x] Write tests proving excluded metadata and array order do not change the hash, scientific values do change it, and non-finite numbers are rejected.
- [x] Run the focused test and confirm it fails because the module does not exist.
- [x] Implement deterministic projection plus RFC 8785 serialization and SHA-256.
- [x] Run the focused test and confirm it passes.

### Task 2: Portable project contract and backward-compatible round trip

**Files:**
- Modify: `XRD_Finder/xrd_finder/core/project.py`
- Modify: `XRD_Finder/xrd_finder/io/project_io.py`
- Modify: `XRD_Finder/tests/test_portable_project_io.py`

**Interfaces:**
- Produces: `Project.analysis_summary: dict[str, Any]`
- Consumes: `compute_result_sha256(...)`

- [x] Write a failing round-trip test for `analysis_summary`, including verification of `result_sha256` after load.
- [x] Add the project field and normalize/finalize the summary immediately before serializing `project.json`.
- [x] Preserve legacy `.xpff` loading with an empty summary.
- [x] Run the portable I/O and hash tests.

### Task 3: Persist one result snapshot per XRD pattern

**Files:**
- Modify: `XRD_Finder/xrd_finder/core/finder_state.py`
- Modify: `XRD_Finder/xrd_finder/ui/match_profile_renderer.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Modify: `XRD_Finder/xrd_finder/ui/project_state_actions.py`
- Create: `XRD_Finder/tests/test_analysis_summary_builder.py`

**Interfaces:**
- Produces: `build_analysis_summary(project, producer_version) -> dict[str, Any]`
- Stores: `profile_states[pattern_id]["result_snapshot"]`
- Stores: `pattern_sample_refs[pattern_id]` or `null`

- [x] Write tests for shared phase catalog entries, per-pattern fractions, fit metrics, unknown peak positions, and nullable sample references.
- [x] Capture quantities and fit/peak statistics from the already calculated Finder result without recalculating it.
- [x] Build a shared `phase_catalog` and pattern result references during project save.
- [x] Run focused builder and profile-state tests.

### Task 4: Portable per-pattern preview assets

**Files:**
- Modify: `XRD_Finder/xrd_finder/io/project_io.py`
- Modify: `XRD_Finder/xrd_finder/ui/project_state_actions.py`
- Modify: `XRD_Finder/tests/test_portable_project_io.py`

**Interfaces:**
- Stores PNG members at `previews/<pattern_id>.png`.
- Stores `preview_path` only as a display reference excluded from `result_sha256`.

- [x] Write a failing test proving preview assets are embedded once, survive transfer, and do not affect `result_sha256`.
- [x] Render/update a compact preview when a pattern result snapshot changes.
- [x] Embed previews atomically with the existing project assets.
- [x] Run portable I/O tests.

### Task 5: Contract documentation and version readiness

**Files:**
- Create: `docs/xpff-analysis-summary-v1.md`
- Modify: `XRD_Finder/RELEASE_NOTES_1.4.0.md`

- [x] Document the complete JSON contract, exclusions, deterministic sorting, revision semantics, and compatibility rules.
- [x] Run the full non-GUI test suite available in the bundled Python runtime.
- [x] Inspect the final diff without changing version or publishing until the complete 1.4.0 feature set is approved.
