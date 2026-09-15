# XRD Phase Finder 1.6.2

This release focuses on offline/secure deployment, macOS packaging and network-control behavior.

## Changed

- Added offline/secure network mode that disables online database requests and skips launcher update checks when enabled.
- Added Security and offline-use information in Help and documentation.
- Added secure macOS and Windows installer builders that package the application, prepared Sci runtime, local Finder data/cache snapshot and secure-mode settings into local deployment packages.
- Added `Tools -> Create secure macOS installer...` and `Tools -> Create secure Windows installer...` for building secure/offline installers from the current prepared workstation.
- Added command-line secure package builders: `scripts/build_secure_macos_pkg.command` and `scripts/build_secure_windows_installer.bat`.
- Materials Project access uses the lightweight REST connector and no longer requires `mp-api`/`pymatgen` for normal Finder operation.
- Candidate search status is more compact and local/online source behavior is clearer in offline mode.

## Notes

- macOS package: `XRD_Phase_Finder_macOS_1.6.2.pkg`.
- Secure/offline installers can be built locally from a prepared workstation when needed; no separate secure package is attached to this release.
- Windows installer: `XRD_Phase_Finder_Setup_v1_6_2.exe`.

