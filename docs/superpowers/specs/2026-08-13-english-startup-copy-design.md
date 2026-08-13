# English Startup Copy Design

## Scope

The Windows startup experience for XRD Phase Finder 1.4.0 must use English only. This includes the first-run feature showcase, scientific-runtime consent and repair dialogs, startup status messages, and startup errors.

## Files

- `toolkit/first_run_showcase.ps1`: showcase window chrome, buttons, and installation state.
- `toolkit/showcase/showcase.json`: seven feature-card titles, descriptions, and the performance notice.
- `toolkit/sci_runtime_setup_ui.ps1`: runtime consent, progress, failure, retry, and log controls.
- `toolkit/launch_xrd_finder_preview.ps1`: startup notifications, runtime errors, and progress details.

The main application interface, scientific phase names, paths, logs produced by third-party tools, and user data are outside this change.

## Copy Rules

- All user-authored static copy in the four scoped files is English.
- Product terms such as Match, Gain, CIF, XRD, XPFF, Sci, and Python remain unchanged.
- Paths, package names, exception details, and downloaded tool output are displayed verbatim.
- Existing controls, timing, installation behavior, and visual layout remain unchanged.

## Verification

- A focused test rejects Cyrillic characters in the four scoped resources.
- Existing showcase and Windows launcher tests assert the new English labels.
- The Windows installer is rebuilt, its manifest checksum is refreshed, and the GitHub 1.4.0 asset is replaced.

