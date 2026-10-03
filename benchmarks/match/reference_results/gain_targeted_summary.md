# Gain benchmark summary

The accepted phase is supplied by the configured oracle or by a complete Match pass; Gain ranks the strongest remaining true phase.

Every candidate is scored once from direct, overlap and hidden evidence; direct evidence has the greatest weight and hidden evidence the least.
One or two residual lines may retrieve a candidate, but the resulting Gain is capped and unsupported strong candidate lines are penalized.
One global zero shift is fitted from the accepted phase. Each phase then receives an independent indexed reciprocal-metric refinement and an independently estimated FWHM.
Match-selected accepted phase correct-family rate: 1.0000.
Dominant-phase Match Top-1/Top-5/Top-10: 1.0000 / 1.0000 / 1.0000.

Global zero-shift median absolute error: 0.0250 deg.
Candidate FWHM median absolute error: 0.0622 deg (31/40 targets estimated).

| Evidence group | Queries | MRR | Top-1 | Top-5 | Top-10 | Shortlist recall | Median time (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| all | 40 | 0.3370 | 0.2000 | 0.5250 | 0.6500 | 0.7750 | 2.950 |
| dominant:direct | 24 | 0.3263 | 0.2500 | 0.3750 | 0.4583 | 0.6250 | 2.833 |
| dominant:overlap | 16 | 0.3530 | 0.1250 | 0.7500 | 0.9375 | 1.0000 | 2.964 |
| mode:direct | 8 | 0.8750 | 0.7500 | 1.0000 | 1.0000 | 1.0000 | 2.830 |
| mode:hidden | 8 | 0.2069 | 0.0000 | 0.5000 | 0.8750 | 1.0000 | 2.970 |
| mode:low_fraction | 8 | 0.0203 | 0.0000 | 0.0000 | 0.0000 | 0.2500 | 3.086 |
| mode:overlap | 8 | 0.3818 | 0.1250 | 0.8750 | 0.8750 | 1.0000 | 2.977 |
| mode:sparse | 8 | 0.2009 | 0.1250 | 0.2500 | 0.5000 | 0.6250 | 2.571 |
