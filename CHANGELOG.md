# Changelog

## 1.7.4 - 2026-11-25

- Add per-phase marker colors and intensity controls, using distinct measured maxima rather than extra markers beside strong peaks.
- Show accepted phases, space groups and refined cells in Sample; clarify Processing section names and highlight clickable phase-color cells.
- Add explicit Le Bail cell/profile refinement with a user-selected iteration budget, continuation from fitted parameters, cancellation and convergence/Rwp reporting.
- Restore the active sample's reference CIF cells with Reset to reference, retaining accepted phases and the scan zero correction.
- Calculate structural mass fractions separately with refined cells and zero held fixed; retain the Le Bail result for further refinement and portable project storage.
- Retain background counting noise in physical scale weights and accept validated CIF composition despite noncritical mapping warnings.
- Preserve compatible saved calculations across the application update; keep published Match/Gain formulas unchanged.
- Publish a new Windows version and update manifests so installations of 1.7.3 can detect the update. macOS remains at 1.7.3 and Linux at 1.7.2 pending platform builds.

## 1.7.3 - 2026-11-24

- Defer scientific-library warmup until the main window has painted, prioritizing opening projects and importing measurements.
- Reuse the prepared library's physical range without expanding its reflection cache for wider experimental scans.
- Restore compatible saved profiles after a range-only crop or application version update, retaining fitted curves, cells and zero shifts.
- Improve accepted-phase marker alignment using independent reflection positions and consistent cell metrics.
- Keep each experimental profile's color when it becomes active; add clickable phase-color cells and Processing color controls.
- Add L/M/R pattern-label alignment, a slider for weak assigned markers and optional active-profile emphasis during export.
- Replace the common multi-pattern phase strip with a draggable compact box; save its relative position in XPFF and retain it in exports.
- Keep disabled axes hidden after redraw and export; suppress residual tick marks when tick length is zero.
- Publish the Windows installer. macOS and Linux installers remain at 1.7.2 until their platform builds are provided.

## 1.7.2 - 2026-11-18

- Open one main Finder window directly from Windows shortcuts, retaining automatic runtime repair when needed.
- Avoid save prompts for unchanged projects, browsing and automatic calculation-cache refreshes.
- Stabilize plot controls near layout wrapping thresholds and reuse toolbar icons.
- Show the workspace before restoring project graphs; defer optional startup tasks and PDF-2 preparation.


## 1.7.1 - 2026-11-07

- Include verified download-and-install updates in the macOS package: fetch fresh manifests, validate size/SHA-256, preserve the save/cancel path and open Installer only after Finder exits.

- Apply observed-pattern normalization and stack offsets to CIF/PDF-2 candidate sticks, calculated/background overlays and RRUFF previews. Retain raw scientific data, fitted profiles and Match/Gain results.
- Declare the bundled XPFF icon in the exported macOS document type for Finder.

- Keep legacy CIF public IDs on folder/ZIP reimport and carry persistent import origins through prepared-library transfer and storage optimization. Refuse ambiguous legacy matches instead of duplicating or replacing project-linked cards.
- Start Identify phases with one click; open optional settings using the arrow within the same button. Refine search uses current filters; the red Finish auto search stops automatic work while retaining candidates and selected phases.
- Identify arbitrary CIFs by their own relative path so adding/removing neighbouring files never reassigns an ID; bound extracted filenames and retain last-record handling for identical numeric COD IDs. Previously stored IDs are kept without automatic renaming.
- Refuse individual Quant fractions for ill-conditioned phase profiles and recheck saved Quant without discarding saved curves or peak assignments.
- Evaluate matched-filter convolutions only inside each width segment and its full kernel halo, preserving boundary and radiation-component behavior.
- Display prepared cards in batches of up to 100 every 50 ms and coalesce their Match/Gain refresh requests.
- Reuse a loaded card for its diffraction table instead of loading all reflections twice.
- Cache finite trace arrays and legend baselines during plot navigation, using indexed intervals for sorted traces.
- Rank SQL peak shortlists by distinct observed-peak evidence rather than raw counts of coincident reflections.
- Limit XPFF manifest/member/total unpacked sizes and extract members atomically.
- Include the built-in example XPFF in Python wheels; remove the overlay width estimator's Qt dependency.
- Read raw angular bounds before accepted-profile preparation, avoiding automatic background fitting on the GUI thread.
- Add informative source labels, configurable local/online library connections, organic/MOF libraries and database descriptions.
- Batch CIF preparation and improve COD/Materials Project loading, I/Ic reuse and native startup.
- Improve macOS fullscreen/project opening, dark-theme contrast and multi-pattern marker display controls.

## 1.7.0 - 2026-11-06

- Reuse prepared reference libraries with compact SQLite storage and portable library archives.
- Improve startup and keep initial preparation outside the main window.
- Restore saved profiles and peak assignments consistently, including Le Bail results.
- Preserve existing calculated I/Ic values and calculate eligible missing values despite noncritical CIF warnings.
- Handle transient Windows worker-file locks without losing completed results.

## 1.6.10 - 2026-11-03

- Download and prepare the inorganic COD selection with separate download/calculation progress and time estimates.
- Reuse downloaded CIFs and compatible prepared reflections instead of repeating completed work.
- Export and import prepared libraries as .xpflib archives for transfer between laboratory computers.
- Check reference coverage against the measured scan range to avoid unnecessary recalculation.
- Use blue toolbar frames matching the Finder icon.
- Prevent common phase-legend layout from repeatedly scheduling itself during its own range and resize updates.
- Temporarily disable the CCDC web-search controls; manually downloaded CIF files can still be imported.

## 1.6.9 - 2026-11-02

- Contextual Help explains controls directly in the main window.
- Guided workflows, a quick overview and an optional isolated training example are available from Help.
- Search setup includes instrument selection and optional Le Bail adjustment.
- Instrumental broadening can be calibrated from a standard measurement and CIF.
- XPFF projects retain validated profiles, assignments and search results for faster reopening.
- Background reference preparation and relative workspace sizing have been improved.

## Unreleased

- Preserve one relative workspace layout for panels and columns, with initial proportions taken from the reviewed layout. Migrate native Qt pixel records before screen constraints change their ratios and remove competing pixel-state writers.
- Keep panel and table proportions across HD/QHD screens and 100–200% display scaling; remove the sidebar width cap and fixed table-height/column-width floors that distorted the saved layout.

## 1.6.7 - 2026-10-28

- Start fresh installations with Edit layout enabled.
- Store panel and column proportions in one workspace record; migrate older pixel-based settings.
- Responsive HD/2K interface and saved table-column proportions.
- Common or individual phase legends and properly formatted chemical formulas.
- Manual peak lists, peak information and background-aware peak detection.
- Reversible manual angle calibration and consistent numeric-setting arrows.
- Search and calculated-reference display limited to the measured scan range.
- Restore accepted-phase colors and keep table columns within their panels.

## 1.6.4 - 2026-10-03

### Added

- Residual evidence measurements and diffraction-fingerprint suppression for equivalent phase records.
- Copy support for selected diffraction-table cells, columns and complete tables.

### Changed

- Improved Match ranking for multi-phase patterns.
- Gain jointly rescales accepted phase profiles and combines direct and overlap evidence before profile validation.
- Updated structure-based diffraction calculation to CRiStMa 0.1.0b12.
- Simplified smoothing, background and amorphous-contribution controls.

### Fixed

- Suppressed duplicate Gain suggestions using diffraction fingerprints rather than names or database identifiers.
- Prevented residual-noise searches from producing misleading Gain values.
- Kept candidate download and preparation responsive, cancellable and stable across repeated Gain refreshes.

## 1.6.0 - 2026-09-14

### Added

- Standalone XRD Phase Finder repository layout.
- macOS `.pkg` builder for the standalone application bundle.
- CRiStMa-based radiation and instrument-profile integration.
- Clean runtime launcher layout under `launcher/`.

### Changed

- Removed non-Finder application payload from the release structure.
- Flattened launchers and metadata so the application root is the Finder root.
- Kept release packages free of tests, development docs, local caches and build output.

### Fixed

- macOS packaging now strips extended attributes before `pkgbuild` to avoid AppleDouble `._*` payload entries.
