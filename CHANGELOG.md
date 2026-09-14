# Changelog

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
