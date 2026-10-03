# Changelog

## 1.6.4 - 2026-10-03

### Added

- Synthetic Match/Gain benchmark, sensitivity analysis and runtime reporting used in the revised manuscript.
- Residual evidence measurements and diffraction-fingerprint suppression for equivalent phase records.
- Copy support for selected diffraction-table cells, columns and complete tables.

### Changed

- Match now uses the benchmark-selected `0.44 / 0.43 / 0.08 / 0.05` weights and the documented 48 observed / 64 reference line limits.
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
