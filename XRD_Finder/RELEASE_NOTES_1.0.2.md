# XRD Phase Finder 1.0.2

Windows installer and Phase Finder workflow update.

## Added

- Windows installer distributed as a GitHub Release `.exe` asset.
- Shared per-user `XRD_Toolkit` Python environment under `%LocalAppData%`.
- Startup preview window with folder, local database, connection, update and settings checks.
- Update prompt that shows a short change summary and lets the user choose whether to open the update download.
- Windows 10/11-only setup checks.
- Direct Python 3.11.9 installer fallback when Python is missing and `winget` is unavailable or fails.
- Start Menu shortcuts, optional Desktop shortcut and Windows uninstall entry.
- Toolkit manifest for per-application version/update metadata.
- Update manifest with installer download URL, size and SHA256 for future update workflows.
- PDF-2 local-library support and reference-pattern preview behavior.
- User CIF local-library handling for candidate search and preview.
- Structural/reference data filters and peak-match probability ranking.
- Background-task plumbing for more responsive database operations.

## Changed

- Renamed the application UI to XRD Phase Finder.
- Windows installer keeps the application in the selected install folder and the shared runtime environment in user AppData.
- Root setup scripts remain available for manual Windows/macOS/Linux environment setup.
- RRUFF entries use shorter readable identifiers in candidate tables.
- RRUFF and PDF-2 reference cards are handled as measured/reference patterns rather than calculated CIF phases.
- Candidate table rows can be browsed by keyboard arrows as well as mouse selection.
- User CIF behavior now depends on context: tree selection shows the user-loaded item normally, candidate-table selection previews calculated/database-style lines.
- Smoothing and background removal controls are anchored toolbar panels with OK, Cancel and Auto controls.
- Search/database/update labels were cleaned up for clearer English.
- Startup preview now reports no available update instead of a skipped update check when appropriate.
- Candidate probability ranking now focuses more on the candidate's own strongest peaks.

## Fixed

- Fixed Windows 10 installer setup stopping when Python was not already installed.
- Fixed preprocessing panels appearing transparent over the plot.
- Fixed panel closing behavior during smoothing/background tuning.
- Fixed project-tree order buttons showing placeholder text.
- Fixed several database/search/update UI wording issues.
- Fixed user CIF preview mode differences between project-tree and candidate-table selection.
- Excluded generated installer output from source control; the `.exe` is distributed as a GitHub Release asset.

## Verification

- Python files compile successfully with Python 3.11.9 from `XRD_Toolkit`.
- Windows installer builds with Inno Setup 6.
- GitHub access was verified for publishing the release.



