# XRD Phase Finder 1.2.3

## Multi-pattern figures

- Added a separate, scalable label and local phase legend for every observed pattern.
- Reused the same color for the same phase across all patterns.
- Added right-click controls for legends and persistent plot layers.
- Improved label placement to avoid covering the observed profile.

## Candidate preview and markers

- Kept candidate-preview profiles and sticks visible independently of accepted-phase tick marks.
- Applied the same preview behavior in single-pattern and multi-pattern modes.
- Filtered displayed phase markers by local 6-sigma peak prominence to suppress noise markers.
- Increased marker size and placed markers slightly above peak maxima.

## Workflow

- Added an option to apply one crop range to all XRD patterns.
- Restricted profile calculation and display to the active cropped range.
- Prevented a searched user reference from being added automatically to the project structures.
- Added per-row arrows that indicate whether Match or Gain currently drives candidate ranking.

## Runtime reliability

- Replaced file-only runtime checks with Python, pip, package-import and application-import checks.
- Added retry and repair logic for the shared `%LocalAppData%\Sci\env` environment.
- Added clearer diagnostics and persistent repair logs when package installation fails.

## Analysis

- The Match/Gain ranking workflow is unchanged: Match remains available, and Gain becomes active after the first accepted phase.
