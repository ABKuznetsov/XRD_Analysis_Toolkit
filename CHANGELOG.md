# Changelog

## 1.3.1 - 2026-08-07

### Added

- Embedded CIF data for every phase used by Match, Gain or per-pattern assignments directly in portable `.xpff` projects.
- Restored missing embedded phases into the local user library when a project is opened on another computer.

### Changed

- Stored a shared phase only once when it is used by several XRD patterns.
- Preferred the exact embedded CIF for project profiles, markers and derived phase data.
- Kept existing local phase records unchanged when their source and entry keys already exist.

### Fixed

- Preserved phase markers and editable phase assignments when transferring a project to a computer without the original user CIF files.

## 1.3.0 - 2026-08-07

### Added

- Added portable `.xpff` project containers with embedded XRD patterns, user CIF references, series, selected phases and saved plot state.
- Added multiple project series, whole-folder drag-and-drop import and series-level visibility controls.
- Added Windows `.xpff` file association and direct project opening from Explorer.
- Added in-place Save alongside Save As and editable phase display names.
- Added configurable outward axis ticks and grid color/width controls.

### Changed

- Improved multi-pattern figures with per-pattern labels, scalable annotations and consistent colors for the same phase.
- Preserved project-tree expansion state while editing and reopening projects.
- Kept candidate preview profiles and sticks independent from accepted-phase plot layers.
- Improved normalized-pattern marker placement and split-color markers for genuine overlapping phases.

### Fixed

- Prevented weak fitted phase contributions from producing false overlap markers.
- Restored strong phase-supported markers that were hidden by structured neighbouring peaks.
- Fixed crop-all processing, plot unit removal and several project persistence edge cases.

## 1.2.0 - 2026-07-27

### Added

- Added indexed peak fingerprints for fast full-database candidate selection.
- Added optional PDF-2 participation in automatic ranking through the reference-pattern filter.
- Added staged direct, overlap and hidden-phase Gain ranking.
- Added lightweight cell refinement, phase-specific profile widths and updated peak positions.
- Added independent physical/amorphous background handling and expanded plot/export controls.

### Changed

- Reworked Match around strong experimental peak positions and relative intensities.
- Reworked Gain to prioritize unexplained experimental evidence over generic profile similarity.
- Improved candidate ranking responsiveness, phase persistence and sample-card phase data.

### Fixed

- Fixed background state loss while phases are added or changed.
- Fixed phase and unknown markers appearing artificially above the experimental profile.
- Fixed several stale Match/Gain values and candidate-table navigation issues.

## 1.1.2 - 2026-07-10

### Added

- Added per-profile plot visibility controls for experimental patterns, candidate preview sticks, calculated totals, individual phase profiles, backgrounds, phase tick marks, peak labels and unknown peaks.
- Added active-profile-aware plotting groundwork for multi-pattern figures.

### Changed

- Improved candidate preview rendering and kept peak labels disabled by default.
- Synchronized more View tab and plot context-menu layer toggles.
- Reduced candidate-table redraw overhead for larger search results.
- Cached more candidate/profile data during browsing to avoid repeated CIF enrichment and profile recalculation.

### Fixed

- Fixed normalization for unprocessed imported XRD files so Finder calculations use the same normalized intensity scale as the displayed experimental pattern.
- Fixed several stale plot-layer artifacts while switching between single-pattern and multi-pattern display modes.

## 1.1.1 - 2026-07-08

### Added

- Added the foundation for separate `Match (%)` and experimental `Gain (%)` candidate metrics for future tuning.
- Added a `Normalize` checkbox for observed XRD patterns (`Imax = 100`) used by display and phase search without modifying source data.

### Changed

- Candidate tables now keep standalone `Match (%)`, experimental mixture `Gain (%)` and reference `I/Ic` values separate.
- Finder profile calculations explicitly include Cu K-alpha1/K-alpha2 doublet contributions.
- Finder background estimation now uses the shared robust XRD background estimator instead of a simple percentile filter.

## 1.0.2 - 2026-07-07

### Added

- Added a Windows installer build workflow; the generated `.exe` is published as a GitHub Release asset instead of being committed to the repository.
- Added a modern startup preview for XRD Phase Finder with checks for application folders, local databases, database connections, updates and settings.
- Added an update prompt that shows the latest version, a short change summary and Yes/No choice before opening the update download.
- Added shared per-user `Sci` environment setup in `%LocalAppData%`, so future XRD applications can reuse the same Python runtime environment.
- Added Windows Start Menu and optional Desktop shortcuts through the installer.
- Added an uninstall entry for Windows Apps & Features / installed programs.
- Added Windows 10/11 checks to the installer setup scripts and launch scripts.
- Added automatic Python 3.11 installation fallback for Windows 10 systems where Python is missing and `winget` is unavailable or fails.
- Added `toolkit/manifest.json` for per-application version/update metadata.
- Added `toolkit/updates/xrd_finder.json` with release asset URL, size and SHA256 for future update workflows.
- Added `update_from_github.bat` for future repository-based updates.
- Added database background-task infrastructure for responsive UI operations.
- Added PDF-2 support through a user-selected local PDF-2 folder, including PDF-2 candidate search and reference-pattern preview behavior.
- Added more explicit search filters for structural data and experimental/reference patterns.
- Added candidate ranking by peak-match probability against the active XRD pattern.
- Added user CIF handling in the local phase library so imported structures can be searched and previewed from candidate tables.

### Changed

- Renamed the public application from XRD Finder to XRD Phase Finder.
- The Windows installer now installs the application wherever the user chooses, while the shared Python environment is kept in user AppData.
- Root setup scripts remain available for manual environment setup on Windows, macOS and Linux; runtime setup logic is kept under `toolkit/`, while generated installer artifacts stay outside source control.
- COD and online/local database searches now favor immediate local results while longer downloads/index work can happen in the background.
- RRUFF entries are displayed with shorter, readable identifiers instead of full generated file names.
- RRUFF and reference-pattern candidates are treated as measured/reference data rather than calculated CIF phases.
- Candidate tables support keyboard row navigation as well as mouse selection.
- User CIF selection behavior was split: selecting a CIF in the project tree shows it as a normal imported pattern/structure context, while selecting it from the candidate table previews calculated/database-style lines.
- Smoothing and background removal controls were reworked from modal dialogs into anchored panels opened from their toolbar buttons.
- Smoothing/background panels now stay open until OK, Cancel or the toolbar button is pressed again.
- Preprocessing controls now expose more parameters and use sliders for values that are easier to tune visually.
- Database management wording and status labels were cleaned up for clearer English.
- Startup preview update wording now says that no update is available instead of reporting a skipped state.
- The project tree order buttons are visible as `Up` and `Down`.
- Phase Finder candidate scoring now focuses more on each candidate's own strong peaks, reducing over-penalty from minor second/third-phase peaks.
- The installer and application metadata were bumped to version `1.0.2`.

### Fixed

- Fixed Windows 10 setup stopping when Python was missing by adding a direct official Python installer fallback.
- Fixed preprocessing panels appearing visually transparent over the plot.
- Fixed the smoothing/background panel lifecycle so screenshots and repeated tuning are practical.
- Fixed update/status text inconsistencies in the startup preview.
- Fixed several English labels in database/search/update UI areas.
- Fixed user CIF preview behavior so tree and table selections use the expected plotting mode.
- Fixed project tree order controls that had degraded into placeholder text.
- Fixed installer packaging so release artifacts are excluded from source control and attached to GitHub Releases instead.

### Verification

- Python package compilation passed with Python 3.11.9 from the shared `Sci` environment.
- Inno Setup 6 successfully built `XRD_Phase_Finder_Setup_1.0.2.exe`.
- GitHub CLI authentication and repository admin access were verified for `ABKuznetsov/XRD_Analysis_Toolkit`.
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



