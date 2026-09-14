# XRD Phase Finder 1.6.0

This release starts the standalone XRD Phase Finder project layout.

## Changed

- Finder is separated from the broader XRD Analysis Toolkit workspace.
- Non-Finder application modules are not included in the Finder runtime or macOS package.
- The project now uses a flat `xrd_finder/` package layout.
- Runtime launcher files live under `launcher/`.
- Instrument radiation/profile metadata is aligned with the CRiStMa-based calculation path.
- macOS package payload is built from a strict Finder-only allowlist.

## Compatibility Note

The public GitHub repository remains `ABKuznetsov/XRD_Analysis_Toolkit`, but its main branch now contains the standalone XRD Phase Finder layout.
