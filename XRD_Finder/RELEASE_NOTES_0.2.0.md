# XRD Analysis Toolkit 0.2.0

Beta release focused on the XRD Finder workflow.

## Highlights

- Multi-XRD display with `One` / `All selected` modes.
- Vertical offset slider for stacked diffraction patterns.
- Stable zoom behavior: zoom changes only via `Reset view` or `Show full pattern`.
- Drag-and-drop import for XRD and CIF files.
- Project tree ordering controls for XRD patterns and CIF phases.
- Candidate preview as intensity sticks on the active XRD pattern.
- Persistent selected phase overlays with editable colors.
- Cleaner selected-phase table: color, phase, matched peaks, quantity and I/Ic.
- Improved COD/CIF parsing for phase names, formulas, publication metadata, cell parameters and atom positions.
- Database management for user CIFs, COD local/online, RRUFF, CCDC/CSD and Materials Project.
- High-resolution plot export.

## Important Notes

- Large reference databases are not bundled. COD/RRUFF bulk databases must be downloaded or indexed explicitly from the Databases tab.
- Materials Project support is optional and requires `requirements-optional.txt` plus an API key.
- I/Ic and quantity values are practical search-match estimates, not full-profile refinement results.

## Verification

- Python package compilation passed with Python 3.11.
- GUI and CLI entry-point imports passed.
- COD CIF parsing was checked on COD `1525670`.
- Local database caches are excluded through `.gitignore`.

## Known Technical Debt

- `XRD_Finder/xrd_finder/ui/analysis_windows.py` remains large and should be split before adding larger batch-processing workflows.
- Finder internals should eventually be split into dedicated peak detection, assignment, zero-shift, scaling and fitting services.
