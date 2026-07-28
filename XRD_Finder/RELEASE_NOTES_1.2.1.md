# XRD Phase Finder 1.2.1

This maintenance release improves multi-phase refinement, Gain ranking, profile visualization and semi-quantitative phase estimates.

## Refinement and Gain

- Separated post-Match profile rendering, unit-cell refinement and Gain scoring into explicit stages.
- Preserved the established Match workflow for the first phase.
- Added indexed residual evidence for refining later phases without re-refining previously accepted cells.
- Added an automatic fallback from exhausted direct residual evidence to overlapping-peak evidence.
- Kept Overlap active for subsequent phases once the workflow reaches that stage.
- Retained uncovered peaks as candidate-search hints while Overlap remains responsible for ranking.
- Slightly lowered the robust residual threshold to retain weak phase evidence.

## Profiles

- Limited colored preview sticks to the jointly calculated total profile.
- Prevented preview markers from visually overstating a phase contribution.

## Quantities

- Replaced normalized profile-scale percentages with a GSAS-II-style mass normalization.
- Fit phase scales using unnormalized calculated diffraction intensities.
- Convert relative unit-cell populations to mass fractions using symmetry-expanded atoms, occupancies and atomic weights.
- Keep I/Ic values as reference information rather than mixing them into the GSAS-style estimate.

## Notes

- Quantities remain semi-quantitative because this application does not perform a complete Rietveld refinement of preferred orientation, microstructure, absorption and parameter uncertainties.
- Crystallographic databases are not bundled and must be indexed separately.

## Download

- Windows: [XRD_Phase_Finder_Setup_1.2.1.exe](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.2.1/XRD_Phase_Finder_Setup_1.2.1.exe)
- SHA256: `a7dc497878ff8494de04868dc07cb3a6e167b6e19866a0eb574bd7ee0a446afc`
