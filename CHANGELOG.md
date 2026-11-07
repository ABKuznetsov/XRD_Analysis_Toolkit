# Changelog

## 1.7.1 - 2026-11-07

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
