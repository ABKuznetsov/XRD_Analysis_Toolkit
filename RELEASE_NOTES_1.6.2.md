# XRD Phase Finder 1.6.2

This release focuses on offline/secure deployment, macOS packaging and network-control behavior.

## Changed

- Added offline/secure network mode that disables online database requests and skips launcher update checks when enabled.
- Added Security and offline-use information in Help and documentation.
- Added a secure macOS installer builder that packages the application, prepared Sci runtime, local Finder data/cache snapshot and secure-mode settings into a single `.pkg`.
- Added `Tools -> Create secure macOS installer...` for building a secure/offline macOS installer from the current prepared workstation.
- Added command-line secure macOS package builder: `scripts/build_secure_macos_pkg.command`.
- Materials Project access uses the lightweight REST connector and no longer requires `mp-api`/`pymatgen` for normal Finder operation.
- Candidate search status is more compact and local/online source behavior is clearer in offline mode.

## Notes

- macOS package: `XRD_Phase_Finder_macOS_1.6.2.pkg`.
- Secure/offline installers can be built locally from a prepared workstation when needed; no separate secure package is attached to this release.
- Windows installer remains at `XRD_Phase_Finder_Setup_v1_6_1.exe` until the Windows build is produced.
