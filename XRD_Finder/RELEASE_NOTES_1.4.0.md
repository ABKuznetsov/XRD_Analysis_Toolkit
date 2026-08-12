# XRD Phase Finder 1.4.0

Version 1.4.0 turns `.xpff` into a portable scientific-result container while keeping it fully editable in XRD Phase Finder.

## Portable XRD results

- Stores source XRD patterns, processed curves, series, user CIF files, selected phases and Finder state in one `.xpff` file.
- Stores a versioned `analysis_summary` for every calculated pattern: identified phases, estimated fractions, fit, explained peaks and unknown peak positions.
- Deduplicates shared phases in `phase_catalog`; one phase can be referenced by many patterns.
- Embeds a per-pattern PNG preview generated from the already rendered result without repeating Match or Gain.
- Keeps old `.xpff` projects readable when they do not contain an analysis summary.

## Reproducible result history

- Provides stable analysis, revision, pattern and phase identifiers.
- Uses an RFC 8785/JCS `result_sha256` to distinguish scientific changes from presentation or metadata changes.
- Keeps physical-sample links outside the scientific hash, so linking an XRD pattern to a laboratory sample does not create a false scientific revision.
- Allows external tools to read the stored result and revision history without repeating scientific calculations.

## Compatibility

- Match, Gain, phase assignment and quantification algorithms are unchanged by the XPFF contract.
- User CIF assets remain embedded and are restored into the local phase library when absent.
- Windows `.xpff` file association and double-click opening remain supported.

## Guided setup and responsive searches

- Introduces a visual seven-step tour of selection, processing, phase search, verification, comparison, figure setup and export.
- Shows the tour once after updating to 1.4.0; it can be browsed with arrows or skipped.
- Keeps the same visual tour on screen while a new scientific Python environment is being installed, without exposing a command window.
- Lists missing or damaged runtime components before installation and asks for confirmation before changing the environment.
- Reports package download and installation progress, and provides Retry, Open log and Close actions if setup cannot be completed.
- Shows a dedicated progress dialog during long candidate searches, including the current source and accumulated result count.

The public schema is documented in `docs/xpff-analysis-summary-v1.md`.
