# Changelog

## Unreleased

### Added

- Linux launch scripts: `setup_env.sh`, `run_finder.sh`, and `run_finder_cli.sh`.
- Linux installation notes for Python venv/pip and Qt desktop packages.

## 0.2.0 - 2026-07-04

### Added

- Standalone Phase Finder UI for macOS and Windows launch scripts.
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

- `xrd_manager/ui/analysis_windows.py` is still large and should be split further before adding batch-processing workflows.
- Quantification and I/Ic values are practical estimates for phase identification, not a replacement for full-profile refinement.
- Large COD/RRUFF databases are intentionally user-managed and are not bundled in the release.
