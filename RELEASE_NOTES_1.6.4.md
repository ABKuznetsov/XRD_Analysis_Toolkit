# XRD Phase Finder 1.6.4

This release improves the everyday phase-identification workflow while keeping phase acceptance under user control.

## Phase identification

- Match gives a more stable shortlist for multi-phase patterns.
- Accepted phase profiles are rescaled together before Gain is calculated, reducing dependence on the order in which phases are accepted.
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

## Assets

- Windows installer: `XRD_Phase_Finder_Setup_v1_6_4.exe`.
- Linux package for Debian/Ubuntu amd64 will be added after the native Linux build is complete.
- The most recent macOS package remains `XRD_Phase_Finder_macOS_1.6.3.pkg` until a 1.6.4 package is built on macOS.

## Notes

Match and Gain are heuristic ranking scores, not probabilities. Quant. (%) is a semi-quantitative profile contribution and is not a Rietveld-derived phase fraction.

The public installers do not contain local user data, database caches or secure/offline runtime snapshots.
