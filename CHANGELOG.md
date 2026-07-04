# Changelog

## 1.0.1 - 2026-07-04

### Fixed

- Fixed HTTPS/SSL certificate handling for online COD, RRUFF, CCDC and manual COD archive downloads by installing `certifi` and using a shared SSL context.
- Restored automatic plot fitting after adding phases to the working set when a single XRD pattern is displayed.
- Kept candidate preview zoom preservation unchanged, so browsing candidate rows does not reset the user's zoom.
- Removed the old default project name from the XRD Finder GUI.
- Moved XRD Finder into the `XRD_Finder/` application folder inside the shared `XRD_Analysis_Toolkit` repository layout.
- Moved XRD Finder databases, caches and temporary working data to `XRD_Finder/data/` by default.
- Replaced remaining public `XRD Manager` window labels with `XRD Analysis Toolkit` / `XRD Finder` names.
- Clarified that setup scripts create a shared Toolkit `.venv` in the repository root.
- Updated package metadata version to `1.0.1`.

## 1.0.0 - 2026-07-04

### Added

- Linux launch scripts: `setup_env.sh`, `run_finder.sh`, and `run_finder_cli.sh`.
- Linux installation notes for Python venv/pip and Qt desktop packages.
- PDF-2 reference-card support from a local PDF-2 folder.
- Structural/reference data switches for separating CIF-calculated phases from measured/reference cards.
- Peak-match probability column and optional candidate ranking by active XRD pattern.
- Application data/cache paths outside the repository using OS-native locations.
- Database clear/update actions for user library, COD, RRUFF, PDF-2 and Materials Project caches.
- Redesigned compound card with scrollable sections, atom table, diffraction-line table and source links.

### Changed

- COD and Materials Project online searches now return rows immediately and download CIFs in the background when possible.
- Local phase cache search now uses indexed SQL filters for source, formula key and elements.
- RRUFF indexing now refreshes the local table cleanly and supports suffixed RRUFF identifiers.
- XY import handles mixed comma/space/semicolon numeric formats more robustly.

## 0.2.0 - 2026-07-04

### Added

- XRD Finder UI for macOS and Windows launch scripts.
- Drag-and-drop import for XRD patterns and CIF structures.
- Multi-pattern display with `One` / `All selected` modes.
- Vertical offset slider for stacked XRD series.
- Project tree ordering controls for XRD patterns and CIF phases.
- Candidate preview as intensity sticks over the active XRD pattern.
- Persistent selected phase overlays with editable phase colors.
- Compact selected-candidate table with color, phase, matched peaks, quantity, and I/Ic.
- COD, local CIF, RRUFF, CCDC/CSD, and Materials Project database management panel.
- Optional/required element filtering using left/right clicks in the periodic table.
- Compound card with cell parameters, atoms, source links, and publication metadata.
- High-resolution plot image export.

### Changed

- Zoom now changes only through `Reset view` or the plot context menu item `Show full pattern`.
- Phase tick lanes are hidden in `All selected` mode to keep multi-XRD figures readable.
- COD/CIF parsing now preserves chemical groups in names such as `Ca28 (Al57 Si135 O384)`.
- COD metadata parsing now reads publication title, authors, journal, year, pages, DOI, cell, atoms, and space group when present.

### Fixed

- Candidate preview no longer resets zoom while browsing rows.
- Selected phase overlays stay attached to the active XRD pattern in stacked views.
- Tree order, plot order, and legend order are aligned.
- Existing cached COD candidates are corrected when a row is clicked and its CIF is re-read.

### Known Limitations

- `XRD_Finder/xrd_finder/ui/analysis_windows.py` is still large and should be split further before adding batch-processing workflows.
- Quantification and I/Ic values are practical estimates for phase identification, not a replacement for full-profile refinement.
- Large COD/RRUFF databases are intentionally user-managed and are not bundled in the release.
