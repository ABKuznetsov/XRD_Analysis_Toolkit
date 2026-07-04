# Project Health

Snapshot for release `0.2.0`.

## Status

Overall state: stable, suitable for GitHub publication as a XRD Finder research tool.

The core Phase Finder workflow is usable:

- import XRD and CIF files;
- search COD/local/RRUFF/CCDC/Materials Project sources;
- preview candidate phases;
- add selected phases to a working set;
- display stacked XRD series;
- export high-resolution plots;
- inspect CIF card metadata.

## Verification Performed

- Python compilation: passed.
- GUI and CLI import checks: passed.
- COD CIF parsing check on `1525670`: passed.
- Candidate-card enrichment check: passed.
- No `TODO`, `FIXME`, `XXX`, `HACK`, or `NotImplemented` markers found in source.

## Release Readiness

Ready for GitHub source release after creating or moving into a git repository.

Recommended release tag:

```text
v0.2.0
```

Recommended GitHub release notes:

```text
RELEASE_NOTES_0.2.0.md
```

## Important Repository Hygiene

Do not commit local databases or generated caches.

Protected by `.gitignore`:

- `XRD_Finder/data/`
- `__pycache__/`
- `*.pyc`
- `dist/`
- `build/`
- `.venv/`
- macOS metadata folders/files

## Main Technical Risks

- `XRD_Finder/xrd_finder/ui/analysis_windows.py` is still the largest module and should be split before adding batch-processing workflows.
- Finder logic should continue moving into focused services:
  - peak detection;
  - assignment building;
  - zero-shift estimation;
  - scale estimation;
  - NNLS/profile fitting.
- Quantification and I/Ic are search-match estimates, not refinement-grade results.
- Network database integrations depend on external service availability and user-managed downloads.

## Suggested Next Milestones

1. Add batch processing for groups of XRD files.
2. Extract graph overlay/state logic from `analysis_windows.py`.
3. Add small automated tests for CIF parsing, local cache indexing and candidate table behavior.
4. Add packaged app build instructions for macOS and Windows.
