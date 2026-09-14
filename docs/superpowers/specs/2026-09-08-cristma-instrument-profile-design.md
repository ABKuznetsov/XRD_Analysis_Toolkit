# CRiStMa Migration And Instrument Profiles

**Date:** 2026-09-08

## Goal

Prepare XRD Phase Finder for the CRiStMa diffraction engine and turn the currently inactive `Wavelength...` and `Resolution...` menu items into one reusable instrument-profile workflow.

The migration is staged. Finder-side profile models, persistence and UI do not depend on an unstable diffraction API and can be completed against the currently published package. The scientific adapter targets the simple powder API planned for CRiStMa beta8; Finder must not bind its main calculation path to the temporary low-level beta6 chain.

The migration must preserve the Finder workflow: experimental processing, candidate retrieval, Match, Gain and phase-fraction estimates remain application responsibilities. CRiStMa becomes the single source of theoretical reflections, structure factors, powder lines and calculated profiles.

## Boundary

```text
CRiStMa
  CIF/structure -> reflections -> F/F2 -> powder lines -> profile

XRD Phase Finder
  observed pattern -> processing -> search -> Match/Gain -> starting estimates
```

Finder keeps its own stable `HKLPeak` transfer object during the migration. Once beta8 is available, a focused adapter converts `PowderCalculationResult` into this object so UI, caches and scoring are not rewritten at the same time as the scientific backend.

## Required CRiStMa Beta8 Contract

The Finder adapter expects one high-level entry point equivalent to:

```python
calculate_powder_profile(
    structure,
    radiation,
    grid,
    instrument_profile=None,
    phase_broadening=None,
) -> PowderCalculationResult
```

The result must keep the scientific stages inspectable:

```text
PowderCalculationResult
├─ reflections
├─ structure_factors
├─ powder_lines
├─ calculated_profile
├─ diagnostics
└─ provenance
```

CRiStMa owns reciprocal-space generation, systematic absences, structure factors, radiation components, diffraction geometry and physical line/profile calculation. Finder owns experimental preprocessing, database retrieval, Match, Gain and starting phase estimates.

## Instrument Profile

An instrument profile is a reusable, versioned record with four groups of data.

### Identity

- Stable UUID and schema version.
- User-facing name.
- Manufacturer, model, serial number and laboratory.
- Calibration date and free-form comment.

### Radiation

- Tube target: Cr, Fe, Co, Cu, Mo, Ag or custom.
- Radiation mode: K-alpha doublet, K-alpha1 only or custom monochromatic wavelength.
- Component wavelengths and relative weights.
- Tube voltage and current.
- Filter and monochromator description.

Only wavelength components and weights affect the calculation in the first release. Voltage, current, filter and monochromator are retained as reproducibility metadata.

### Geometry And Detector

- Geometry name, initially `Bragg-Brentano` or descriptive custom geometry.
- Polarization/correction settings supported by CRiStMa.
- Goniometer radius, divergence slit, receiving slit and Soller slit descriptions.
- Detector manufacturer, model, type and operating mode.

Only CRiStMa-supported corrections are calculation-active. Unsupported geometry and detector fields remain explicit metadata and must not silently alter intensities.

### Resolution

- Constant FWHM, or TCH profile.
- TCH parameters `U`, `V`, `W`, `X`, `Y` with units shown in the UI.
- A compact resolution preview.

Crystallite size, microstrain, preferred orientation and other sample effects do not belong to the instrument profile. They remain phase/sample parameters for the future refinement application.

## Persistence

The user maintains a global instrument library in the managed XRD Finder data directory. The library is JSON, schema-versioned and written atomically.

When a profile is applied to a pattern, a complete immutable snapshot is copied into the project. This guarantees that reopening a project produces the same calculation even if the global preset was later edited or deleted.

Legacy projects containing only `Pattern.wavelength` are upgraded in memory to a compatible legacy profile. No existing project file becomes unreadable.

## UI

The top action bar gains a compact instrument selector and an edit button. The dialog is implemented in focused modules rather than added to `analysis_windows.py`.

The dialog uses sections:

1. Identity
2. Tube and radiation
3. Geometry and optics
4. Detector
5. Resolution

Primary actions:

- Save as new profile
- Update profile
- Delete profile
- Apply to active pattern
- Apply to selected patterns
- Restore built-in Cu K-alpha default

`Pattern > Wavelength...` opens the same dialog focused on radiation. `Pattern > Resolution...` opens it focused on resolution. These are not separate settings implementations.

Changing a profile recalculates theoretical lines/profile and invalidates Match/Gain caches. It does not modify smoothing, background, crop ranges or observed intensities.

The existing `Strip K-Alpha2` wording must not imply that raw experimental data were deconvolved when only the calculated radiation spectrum changes. The first implementation exposes this as the K-alpha1-only radiation mode in the profile.

## Calculation And Cache Keys

Instrument models expose two serializations:

- Full snapshot: scientific inputs plus metadata, for project reproducibility.
- Calculation key: only parameters that affect theoretical diffraction.

The calculation key is incorporated into `CalculationContext`. Editing a comment or serial number therefore does not invalidate numerical caches; changing wavelength, radiation weights, correction settings or resolution does.

Zero shift remains pattern-specific. It is not stored as an intrinsic property of the instrument preset because it may differ between measurements and calibrations.

## Compatibility Strategy

`CalculatedPatternService` remains the public Finder facade. Until CRiStMa beta8 is published and verified, it continues to use the legacy calculation path. The beta8 adapter will be introduced behind this facade, preserving current callers and `HKLPeak` semantics. Direct Gemmi use is removed only after CIF import and atomic-weight access have CRiStMa-backed replacements.

The initial built-in profile matches current Finder defaults as closely as practical: Cu K-alpha radiation and constant FWHM. Numerical results may still change because CRiStMa uses a different, more explicit diffraction chain. Representative Match/Gain rankings must be compared before the legacy calculation code is deleted.

## Dependencies And Packaging

- Use the currently published CRiStMa beta only for stable structure-level capabilities needed during preparation.
- Switch the scientific powder adapter and runtime pin together when beta8 is published.
- Keep NumPy, SciPy, pybaselines, PySide6, pyqtgraph, rfc8785, packaging and certifi in Finder.
- Keep `mp-api` and `pymatgen` optional.
- Remove Gemmi from required runtime only after all direct imports are gone.
- Update root metadata, Finder requirements, runtime probes and the visible Windows runtime installer together.

## Acceptance Criteria

- Finder instrument profiles can be completed and persisted without depending on a temporary low-level CRiStMa diffraction API.
- Once beta8 is available, one CIF can be loaded and calculated through its high-level powder API without direct Finder crystallographic mathematics.
- Cu K-alpha doublet, K-alpha1-only and custom monochromatic radiation produce deterministic line positions.
- Constant-width and TCH profiles produce finite arrays on the requested grid.
- Instrument presets can be created, updated, selected and deleted.
- Applying a preset affects only the requested pattern(s).
- Project round-trip preserves the complete applied snapshot.
- Legacy projects still load with their original wavelength.
- Match/Gain calculation receives the new calculation key and does not reuse stale profiles.
- macOS and Windows runtime checks require the same published CRiStMa version whenever the dependency is enabled for a release.
- Focused scientific, persistence and UI-connection tests pass; no broad unrelated test expansion is required.
