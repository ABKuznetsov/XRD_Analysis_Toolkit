# Security and offline deployment notes

XRD Phase Finder is a local desktop application. It does not include telemetry, analytics reporting or background usage tracking.

## Network access

Network access is used only for user-visible online functions:

- launcher update checks and installer downloads;
- COD online CIF search/download;
- Materials Project REST search/download when an API key is configured;
- AFLOW and OQMD online structure searches when enabled;
- RRUFF archive download when requested;
- CCDC public DOI/download lookup when requested.

Use **Tools -> Network mode -> Offline / secure** to disable online database requests. The setting is stored in the user data directory and is read by both the launcher and the main application. When enabled, the launcher shows that secure/offline mode is active and skips update checks. Local project files, user CIF libraries, local SQL indexes and already prepared database caches remain available.

For scripted or locked-down deployments, `XRD_FINDER_OFFLINE=1` forces the same mode regardless of the saved setting.

## Local data

User data is stored in the user's application-data area, not in the program source tree:

- Windows: `%LocalAppData%\Sci\apps\xrd_phase_finder`
- macOS: `~/Library/Application Support/Sci/XRD_Finder` for packaged installs
- Linux/source runs: the platform data directory or `XRD_FINDER_DATA_DIR` when set

This data can include imported XRD patterns, imported CIF files, local phase caches, local SQL indexes, instrument profiles and `.xpff` project files.

## Logs and diagnostics

Runtime diagnostic logs are local-only, capped and rotated. They redact full home-directory paths and are intended for troubleshooting failures.

Set `XRD_FINDER_DIAGNOSTICS=0` to disable Finder runtime diagnostics and launcher console logs where supported. Installer/repair scripts can still create setup logs while preparing the scientific Python runtime.

## Secrets

Materials Project API keys are stored in local application settings and sent only to the Materials Project API when that source is enabled. They are not sent to COD, AFLOW, OQMD, RRUFF or GitHub.

For high-security deployments, disable online Materials Project access or distribute prebuilt local caches instead of storing API keys on shared workstations.

## Recommended controlled deployment

For institutional or government workstations:

1. Build or install the Sci runtime on a controlled machine.
2. Prepare local user/COD/PDF/RRUFF caches on a connected machine if needed.
3. On macOS, use **Tools -> Create secure macOS installer...** or run `scripts/build_secure_macos_pkg.command` to create a single secure/offline `.pkg`.
4. Deploy that secure installer through the institution's approved software channel.
5. The secure installer copies the prepared runtime and local Finder data/cache snapshot to the target user profile and enables offline/secure mode automatically.
6. For scripted launches, `XRD_FINDER_OFFLINE=1` can still force the same behavior.
7. Use `XRD_FINDER_DIAGNOSTICS=0` if runtime diagnostics are not allowed.

This document is an implementation/security posture note, not a formal certification. Formal approval still requires the institution's own review of installers, dependencies, signatures, update policy and local data-handling requirements.
