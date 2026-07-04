# XRD Analysis Toolkit 1.0.0

First stable release of the XRD Finder workflow.

This release turns the prototype into a practical cross-platform search-match tool for visual phase identification in powder XRD data. It combines observed XRD patterns, CIF-based calculated diffraction profiles, local and online crystallographic sources, reference-card overlays and compound cards in one workflow.

## Screenshots

![Phase search overview](docs/screenshots/phase-search-overview.png)

![Candidate preview](docs/screenshots/candidate-preview.png)

![Multi-pattern stack](docs/screenshots/multi-pattern-stack.png)

![Compound card](docs/screenshots/compound-card.png)

![Database panel](docs/screenshots/database-panel.png)

## Highlights

- Cross-platform launch support for Windows, macOS and Linux.
- Multi-XRD display with stable zoom, plot ordering and vertical offset control.
- COD, local CIF, RRUFF, CCDC/CSD, Materials Project and PDF-2 source management.
- PDF-2 reference-card support from a local Match `PDF2-2004` folder.
- Separate switches for structural CIF data and experimental/reference patterns.
- Candidate ranking by estimated peak-match probability for locally available structures.
- CIF-based calculated profiles with persistent selected-phase overlays and editable colors.
- Compound cards with phase metadata, cell parameters, atom positions, diffraction lines and source links.
- Drag-and-drop import for XRD patterns and CIF structures.
- High-resolution plot export.

## Data Sources

- **User library**: imported CIF files and local saved structures.
- **COD local/bulk**: indexed CIF collections or downloaded COD archives.
- **COD online**: lightweight online search with background CIF caching.
- **RRUFF**: measured powder-pattern reference overlays.
- **PDF-2**: optional local Match `PDF2-2004` card reader for reference peak overlays.
- **CCDC/CSD**: optional DOI/refcode lookup when the CCDC Python API is available.
- **Materials Project**: optional API-key based structure search.

## User Workflow

1. Import one or more XRD patterns by button, command line or drag-and-drop.
2. Select required and optional elements in the periodic table.
3. Choose which databases should participate in search.
4. Single-click candidates to preview peaks and inspect the card.
5. Double-click structural candidates to add them to the selected phase set.
6. Adjust selected phase colors and build publication-ready figures with high-resolution export.

## Important Notes

- Large COD/RRUFF/PDF-2 databases are not bundled. They are user-managed from the Databases tab.
- PDF-2 support expects local Match/PDF-2 files and does not redistribute database content.
- Materials Project support is optional and requires `requirements-optional.txt` plus an API key.
- I/Ic, quantity and probability values are search-match aids, not a replacement for full-profile refinement.
- The software is intended for initial phase identification and interpretation. Use dedicated refinement software for final quantitative Rietveld refinement.

## Verification

- Python package compilation passed with Python 3.11.
- GUI and CLI entry-point imports passed.
- Phase Finder window smoke test passed in offscreen mode.
- Linux shell launcher syntax checks passed.
- Local cache/data folders remain excluded through `.gitignore`.

## Known Technical Debt

- `XRD_Finder/xrd_finder/ui/analysis_windows.py` is still the largest module and should be split before the next major batch-processing work.
- Finder internals should continue moving toward dedicated peak detection, assignment, zero-shift, scaling and fitting services.
