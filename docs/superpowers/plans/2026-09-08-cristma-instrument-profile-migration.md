# CRiStMa Instrument Profile Migration Implementation Plan

> **For Codex:** Execute this plan task by task with focused tests. Do not fold new UI into `analysis_windows.py`, and do not remove the legacy diffraction implementation until representative Match/Gain comparisons pass.

**Goal:** Add reusable, project-persisted instrument profiles now and replace Finder's theoretical diffraction backend through the high-level powder API planned for CRiStMa beta8.

**Architecture:** Complete pure Finder instrument dataclasses, an atomic profile library, project snapshots and focused UI modules independently of the diffraction backend. Keep `CalculatedPatternService` and `HKLPeak` as a compatibility facade. Add the CRiStMa-backed service only after beta8 publishes a stable high-level powder entry point. Calculation caches use only calculation-active profile fields.

**Tech Stack:** Python 3.11/3.12, CRiStMa 0.1.0b6, NumPy, SciPy, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-cristma-instrument-profile-design.md`

---

## Task 1: Prepare And Validate The CRiStMa Runtime

**Files:**
- Modify: `pyproject.toml`
- Modify: `XRD_Finder/requirements.txt`
- Modify: `XRD_Finder/xrd_finder/apps/runtime_check.py`
- Modify: `XRD_Finder/install_windows_runtime_direct.bat`
- Modify: `XRD_Finder/tests/test_runtime_requirements.py`
- Modify: `XRD_Finder/tests/test_standalone_runtime_repair_bat.py`

1. Add a focused failing assertion that the required runtime contains one exact published CRiStMa beta and that Windows installs/imports it.
2. Run `pytest XRD_Finder/tests/test_runtime_requirements.py XRD_Finder/tests/test_standalone_runtime_repair_bat.py -q` and confirm the failure.
3. Add the exact dependency to all runtime manifests and probes. Keep Gemmi temporarily during the compatibility phase. Do not route scientific powder calculation through beta6.
4. Run the focused tests and the direct `python -c "import cristma"` probe in the project environment.
5. Commit only Task 1 files.

## Task 2: Add Pure Instrument Models

**Files:**
- Create: `XRD_Finder/xrd_finder/instrument/__init__.py`
- Create: `XRD_Finder/xrd_finder/instrument/models.py`
- Create: `XRD_Finder/tests/test_instrument_profile_models.py`

1. Write tests for the built-in Cu K-alpha profile, validation, JSON-safe round-trip and stable calculation keys.
2. Define frozen, slotted dataclasses for identity, radiation, geometry, detector, resolution and `InstrumentProfile`.
3. Provide `to_dict()`, `from_dict()`, `calculation_payload()` and `calculation_key()` without importing Qt or CRiStMa.
4. Verify metadata-only changes preserve the calculation key and numerical changes invalidate it.
5. Run `pytest XRD_Finder/tests/test_instrument_profile_models.py -q`.

## Task 3: Add The Atomic Global Profile Library

**Files:**
- Create: `XRD_Finder/xrd_finder/instrument/library.py`
- Modify: `XRD_Finder/xrd_finder/services/cache_paths.py`
- Create: `XRD_Finder/tests/test_instrument_profile_library.py`

1. Write tests for first-run defaults, create/update/delete, duplicate names, corrupted-file recovery and atomic replacement.
2. Add `default_instrument_profile_library_path()` under the managed user data root.
3. Implement a schema-versioned JSON library. Preserve a built-in Cu K-alpha profile that cannot leave the library empty.
4. Run `pytest XRD_Finder/tests/test_instrument_profile_library.py -q`.

## Task 4: Persist Per-Pattern Profile Snapshots

**Files:**
- Modify: `XRD_Finder/xrd_finder/core/pattern.py`
- Modify: `XRD_Finder/xrd_finder/io/project_io.py`
- Create: `XRD_Finder/tests/test_project_instrument_profiles.py`

1. Write a project round-trip test with a complete profile snapshot.
2. Write a legacy-project test containing `wavelength` but no snapshot.
3. Add a JSON-safe `instrument_profile` field to `Pattern` and migrate legacy wavelength data during load.
4. Ensure portable `.xpff` and plain JSON manifests preserve the same snapshot.
5. Run `pytest XRD_Finder/tests/test_project_instrument_profiles.py -q`.

## Task 5: Implement The CRiStMa Beta8 Scientific Adapter

**Files:**
- Create: `XRD_Finder/xrd_finder/services/cristma_diffraction_service.py`
- Modify: `XRD_Finder/xrd_finder/services/calculated_pattern_service.py`
- Create: `XRD_Finder/tests/test_cristma_diffraction_service.py`
- Use fixtures from: `XRD_Finder/tests/fixtures/`

1. Wait until the beta8 high-level powder API is published. Do not implement this task against beta6 low-level objects.
2. Inspect the installed beta8 signatures and write contract tests against the published package, not a local checkout.
3. Test reflection/line generation, allowed/extinct filtering, K-alpha doublet, K-alpha1-only, custom wavelength, constant FWHM and TCH profile output.
4. Implement conversion from Finder `Structure` and `InstrumentProfile` to the beta8 entry point and map `PowderCalculationResult` lines back to `HKLPeak`.
5. Make `CalculatedPatternService` delegate to the adapter while retaining its current method signatures.
6. Run the adapter and existing calculated-pattern tests.

## Task 6: Extend Calculation Context And Cache Invalidation

**Files:**
- Modify: `XRD_Finder/xrd_finder/finder/context.py`
- Modify: `XRD_Finder/xrd_finder/finder/profile_calculator.py`
- Modify: `XRD_Finder/xrd_finder/finder/service.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Create or modify: `XRD_Finder/tests/test_calculation_context.py`

1. Add a failing test showing that a wavelength/resolution change must miss the profile cache while metadata changes must hit it.
2. Add the instrument calculation key to `CalculationContext` and all cache keys.
3. Resolve the active pattern snapshot once at the orchestration boundary and pass the resulting context downward.
4. Run context, cache and Finder-service focused tests.

## Task 7: Build The Instrument Profile Dialog In Small Modules

**Files:**
- Create: `XRD_Finder/xrd_finder/ui/instrument_profile_dialog.py`
- Create: `XRD_Finder/xrd_finder/ui/instrument_profile_sections.py`
- Create: `XRD_Finder/xrd_finder/ui/instrument_profile_actions.py`
- Create: `XRD_Finder/tests/test_instrument_profile_ui.py`

1. Write UI tests for initial values, model-dependent enabled fields and emitted apply targets.
2. Build collapsible/focused sections for identity, radiation, geometry/optics, detector and resolution.
3. Disable metadata/future-only controls only when they imply unsupported calculations; otherwise label them clearly as recorded metadata.
4. Add profile CRUD and active/selected apply actions through the library/controller.
5. Keep each new UI module comfortably below 1000 lines.
6. Run `pytest XRD_Finder/tests/test_instrument_profile_ui.py -q` with the offscreen Qt platform.

## Task 8: Connect The Top Selector And Existing Menu

**Files:**
- Create: `XRD_Finder/xrd_finder/ui/instrument_profile_selector.py`
- Modify: `XRD_Finder/xrd_finder/ui/finder_action_bar.py`
- Modify: `XRD_Finder/xrd_finder/ui/phase_finder_menu.py`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py`
- Modify: `XRD_Finder/tests/test_instrument_profile_ui.py`

1. Add tests that `Wavelength...` opens the radiation section and `Resolution...` opens the resolution section.
2. Add a compact selector plus edit icon to the action bar.
3. Bind menu actions to explicit owner callbacks instead of inert actions.
4. Apply snapshots only to the active pattern by default; expose a separate selected-pattern command.
5. Trigger theoretical recalculation and Match/Gain invalidation without touching observed preprocessing state.
6. Run the focused UI tests.

## Task 9: Compare Scientific And Ranking Behaviour

**Files:**
- Create: `XRD_Finder/scripts/compare_diffraction_backends.py`
- Create: `XRD_Finder/tests/test_cristma_match_gain_smoke.py`
- Create: `XRD_Finder/benchmark_results/cristma_migration.md`

1. Compare old and CRiStMa line positions/intensities for a small representative CIF set.
2. Run a small set of existing real/synthetic Match/Gain scenarios and record ranking changes, runtime and known causes.
3. Fix mapping or convention defects. Do not tune Match/Gain heuristics merely to reproduce legacy numbers.
4. Require finite profiles, physically valid line positions and acceptable primary-phase ranking before deleting legacy calculations.

## Task 10: Remove Gemmi And Legacy Diffraction Math

**Files:**
- Modify: `XRD_Finder/xrd_finder/io/cif_loader.py`
- Modify: `XRD_Finder/xrd_finder/finder/service.py`
- Modify: `XRD_Finder/xrd_finder/services/calculated_pattern_service.py`
- Modify: `pyproject.toml`
- Modify: `XRD_Finder/requirements.txt`
- Modify: runtime installers/probes and their focused tests

1. Replace CIF parsing with `cristma.read()` plus a narrow compatibility conversion into Finder models.
2. Replace Gemmi atomic-weight lookup with CRiStMa/reference data or a narrow application helper.
3. Delete the superseded reflection, symmetry, scattering-factor and profile mathematics from `calculated_pattern_service.py`.
4. Remove Gemmi from all required-runtime manifests and probes.
5. Run the focused scientific, persistence, runtime and UI tests plus an application import smoke test.

## Task 11: Release Verification

**Files:**
- Modify only if required: `scripts/build_macos_pkg.command`
- Modify only if required: Windows installer/bootstrap scripts
- Modify: release notes for the target version

1. Build the macOS package and verify its runtime imports the pinned CRiStMa version.
2. Verify the Windows runtime installer installs/imports CRiStMa and still gives visible progress.
3. Launch with and without network access, load a legacy project, create a profile, apply it and reopen the saved project.
4. Record exact verification commands and results in the release notes.
