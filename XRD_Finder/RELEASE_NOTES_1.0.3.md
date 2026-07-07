# XRD Phase Finder 1.0.3

Patch release for testing the in-app update flow and improving Windows startup reliability.

## Changed
- Added a visible Save project button in the Phase Finder workspace.
- Stored smoothed and background-corrected XRD curves on each project pattern, so preprocessing is preserved when switching samples in multi-pattern mode.
- Saved preprocessing state in project JSON manifests.
- Added Qt software-rendering fallback for Windows 10 systems that crash during PySide startup with native graphics drivers.
- Improved startup diagnostics with Python stdout/stderr logging.

## Verification
- Python modules compile successfully.
- Project JSON save smoke test includes processed XRD points and background-removal state.
- Windows installer builds as `XRD_Phase_Finder_Setup_1.0.3.exe`.