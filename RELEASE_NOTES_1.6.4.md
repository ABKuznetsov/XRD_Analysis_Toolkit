# XRD Phase Finder 1.6.4

This release aligns the public application with the revised Phase Finder manuscript and reviewer response. Match and Gain remain operator-guided ranking tools; phase acceptance stays under user control.

## Phase identification

- Match uses the benchmark-selected weights `0.44 / 0.43 / 0.08 / 0.05` for observed coverage, reference coverage, matched-line support and alignment support.
- Match compares at most 48 detected experimental lines with 64 calculated candidate reflections using the documented 0.55 degree 2-theta tolerance.
- Accepted phase profiles are rescaled jointly before Gain is calculated, reducing dependence on the order in which phases are accepted.
- Gain combines direct and overlap evidence with the documented winner-plus-corroboration rule and checks line evidence against the residual profile.
- Candidates equivalent to an accepted phase are suppressed by their diffraction fingerprint instead of relying on database identifiers or phase names.
- Unreliable Gain values are displayed as dashes rather than ranking candidates from residual noise.

## Diffraction and preprocessing

- CRiStMa 0.1.0b12 is used for faster structure-based powder calculations and corrected reflection generation.
- Peak measurements use a lightly smoothed detection signal and retain positions, areas and widths from the unsmoothed background-corrected profile.
- The simplified smoothing and background controls preserve the original data and expose the estimated amorphous contribution separately.
- Instrument profiles, radiation components and phase-specific broadening are included when calculated profiles are reconstructed.

## Workflow and reliability

- Online database results remain interactive while structures are downloaded and indexed in the background.
- Resetting the candidate table cancels pending preparation work and prevents stale Gain refresh cycles.
- Broad searches report the number of matching cards and request confirmation before preparing more than 100 entries.
- Diffraction-data tables support copying selected cells, complete columns and the full table.
- The repository includes the synthetic Match/Gain benchmark used for the manuscript sensitivity and timing analysis.

## Assets

- Windows installer: `XRD_Phase_Finder_Setup_v1_6_4.exe`.
- Linux package for Debian/Ubuntu amd64: `XRD_Phase_Finder_1.6.4_amd64.deb`.
- The most recent macOS package remains `XRD_Phase_Finder_macOS_1.6.3.pkg` until a 1.6.4 package is built on macOS.

## Notes

Match and Gain are heuristic ranking scores, not probabilities. Quant. (%) is a semi-quantitative profile contribution and is not a Rietveld-derived phase fraction.

The public installers do not contain local user data, database caches or secure/offline runtime snapshots.
