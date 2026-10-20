# XRD Phase Finder 1.6.5

This maintenance release corrects structural phase quantities following Hill and Howard (1987).

- Quant uses the physical profile scale, occupied unit-cell mass and unit-cell volume: `W_k = S_k (ZM)_k V_k / sum_j[S_j (ZM)_j V_j]`.
- Physical integrated profiles are kept separate from normalized display curves. Equivalent ordinary and doubled unit cells give the same mass fractions.
- Quant is unavailable when structural data are incomplete, a selected phase cannot be calculated, or the selected patterns cannot be distinguished quantitatively.
- Gain runs only after **Auto search**. Manual element/text results remain available for browsing without automatic Gain reranking when phases are accepted or cards finish downloading.
- The Match/Gain scoring and peak detection remain those of 1.6.4. Experimental search changes are not included.

This is a correction to approximate structural phase quantities, not a full Rietveld-refinement implementation or a claim of experimental quantitative accuracy.

Reference: [Hill & Howard, Journal of Applied Crystallography 20 (1987), 467–474](https://doi.org/10.1107/S0021889887086199).

## Download

- Windows: `XRD_Phase_Finder_Setup_v1_6_5.exe`.
- macOS and Linux installers remain explicitly at 1.6.4 until native 1.6.5 builds are available. Their source launchers use the corrected 1.6.5 application code.

The installer contains application and launch files. Tests, benchmarks, development documents, downloaded databases and user caches are not included.
