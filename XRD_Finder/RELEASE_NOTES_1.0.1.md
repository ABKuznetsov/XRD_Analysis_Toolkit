# XRD Analysis Toolkit 1.0.1

Patch release for XRD Finder.

## Fixed

- Restored automatic plot fitting after adding one or more calculated phases when a single XRD pattern is displayed.
- Candidate preview still preserves the current zoom while browsing the candidate table.
- Removed the old default project name from the XRD Finder GUI.
- Moved XRD Finder into the `XRD_Finder/` application folder inside the shared `XRD_Analysis_Toolkit` repository layout.
- Moved XRD Finder databases, caches and temporary working data to `XRD_Finder/data/` by default.
- Replaced remaining public `XRD Manager` window labels with `XRD Analysis Toolkit` / `XRD Finder` names.
- Clarified that setup scripts create a shared Toolkit `.venv` in the repository root.
- Synchronized package metadata version with the release number.

## Verification

- Python package compilation passed with Python 3.11.
- GUI and CLI imports passed.
- Phase Finder window smoke test passed in offscreen mode.
