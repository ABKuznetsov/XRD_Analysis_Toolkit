# XRD Phase Finder 1.2.0

This feature release develops XRD Phase Finder into a faster first-pass phase-identification and profile-inspection tool.

## Search and ranking

- Added indexed reference fingerprints with the strongest lines stored for fast first-pass candidate selection.
- Added optional PDF-2 candidates to automatic ranking through the existing `Experimental/reference patterns` filter.
- Reworked `Match (%)` around the positions and relative intensities of the strongest experimental peaks.
- Reworked `Gain (%)` as a staged search for direct unexplained peaks, overlapping peaks and hidden-phase evidence.
- Added background/noise-aware peak handling and improved experimental peak-width estimation.
- Kept searches independent of a presumed elemental composition when no element filter is selected.

## Profiles and refinement

- Added lightweight unit-cell refinement from assigned indexed reflections and immediate peak-position updates.
- Added independent profile widths for selected phases.
- Improved calculated totals, difference curves, phase assignment markers and unknown-peak markers.
- Added separate physical and broad/amorphous backgrounds with automatic estimation and persistent manual tuning.
- Preserved selected phases and tuned backgrounds while candidates and plot settings are changed.

## Interface and export

- Added sample-card phase rows with editable cell parameters.
- Added per-pattern XRD cropping with multiple retained ranges.
- Expanded plot controls for observed, calculated, background, reference and individual phase profiles.
- Added observed line/scatter display modes and per-layer colors and widths.
- Improved high-resolution export so font and line proportions follow the on-screen plot.
- Improved responsiveness and progress feedback during full-database ranking.

## Notes

- The application remains a first-approximation search-match tool, not a replacement for full Rietveld refinement.
- Crystallographic databases are intentionally not bundled. Search becomes available after the user indexes the required COD, RRUFF, Materials Project, PDF-2 or user data.

## Download

- Windows: [XRD_Phase_Finder_Setup_1.2.0.exe](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.2.0/XRD_Phase_Finder_Setup_1.2.0.exe)
