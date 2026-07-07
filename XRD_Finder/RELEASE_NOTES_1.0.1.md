# XRD Phase Finder 1.0.1

Patch release for XRD Phase Finder.

## Fixed

- Fixed HTTPS/SSL certificate handling for online COD, RRUFF, CCDC and manual COD archive downloads by installing `certifi` and using a shared SSL context.
- Restored automatic plot fitting after adding one or more calculated phases when a single XRD pattern is displayed.
- Candidate preview still preserves the current zoom while browsing the candidate table.
- Removed the old default project name from the XRD Phase Finder GUI.
- Moved XRD Phase Finder into the `XRD_Finder/` application folder inside the shared `XRD_Analysis_Toolkit` repository layout.
- Moved XRD Phase Finder databases, caches and temporary working data to `XRD_Finder/data/` by default.
- Replaced remaining public `XRD Manager` window labels with `XRD Phase Finder` / `XRD Phase Finder` names.
- Clarified that setup scripts create a shared Toolkit `.venv` in the repository root.
- Synchronized package metadata version with the release number.

## Verification

- Python package compilation passed with Python 3.11.
- GUI and CLI imports passed.
- Phase Finder window smoke test passed in offscreen mode.
