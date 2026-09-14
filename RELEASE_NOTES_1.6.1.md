# XRD Phase Finder 1.6.1

This release focuses on reviewer-facing packaging, reproducible diffraction calculation and practical transfer of user data between computers.

## Changed

- CRiStMa is the single diffraction path for CIF-backed Finder candidates, including candidates that are already linked to project phases.
- Local peak-index preselection now compares observed peaks by d-spacing using the active wavelength instead of comparing cached Cu-space two-theta values.
- CRiStMa calculation failures are no longer silently converted to legacy diffraction calculations in the Finder line cache.
- The Windows installer packages the standalone Finder runtime only and excludes development folders, tests, docs, local logs and caches.
- Bundled example project is available from Help and opens read-only.
- Help and Database menu entries now open working windows or are marked as in development.
- Plot appearance, layout and instrument profile settings are stored as user settings and can be exported/imported.
- User, COD and Materials Project phase caches can be exported/imported with their SQL peak indexes.
- Instrument profiles are no longer installed with author-specific defaults; project snapshots remain reproducible without populating every user's global profile list.
- COD connectivity warnings now mention VPN/network blocking as a possible cause.

## Notes

- Windows asset: `XRD_Phase_Finder_Setup_1.6.1.exe`.
- macOS package should be built separately on macOS with `scripts/build_macos_pkg.command`.
