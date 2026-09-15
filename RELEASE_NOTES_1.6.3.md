# XRD Phase Finder 1.6.3

This release fixes database-search regressions found after the 1.6.2 Windows build.

## Bug fixes

- COD online search now returns entries immediately while CIF download, indexing and Match/Gain preparation continue in the background.
- Repeated COD searches are no longer skipped only because the same element set was attempted before; Finder checks whether matching COD rows are present in the local cache first.
- COD element searches try the most specific required+optional element systems first, reducing broad COD requests that can fail or time out behind VPN/proxy setups.
- Candidate-search progress dialogs now show only the current database action text during online requests, without step counters, candidate counters or a progress bar.
- Online database connection warnings now mention VPN/proxy checks and are worded for online sources in general rather than as a COD-only UI problem.

## Assets

- Windows installer: `XRD_Phase_Finder_Setup_v1_6_3.exe`.
- macOS package: `XRD_Phase_Finder_macOS_1.6.3.pkg`.

## Notes

The public Windows installer does not contain local user data or secure/offline runtime snapshots. Local secure Windows packages must stay outside public GitHub release assets.
