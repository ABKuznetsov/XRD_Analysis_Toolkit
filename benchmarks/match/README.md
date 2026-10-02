# Match and Gain benchmark

This directory contains the compact, reproducible benchmark used to evaluate the Match ranking, its numerical parameters, and the Gain ranking. The bundled SQLite file contains 1,058 reference phases and 54,675 reflection records recalculated with CrIStMa 0.1.0b12. Synthetic mixtures are generated at run time, so the repository does not need to store hundreds of diffraction profiles.

## Match benchmark

Run the complete benchmark with:

```powershell
python -m benchmarks.match.evaluate `
  --dataset benchmarks/match/data/match_benchmark.sqlite `
  --output build/match-benchmark `
  --workers 4
```

The benchmark contains 192 profiles: independent train, validation, and held-out test sets spanning four noise levels, four nominal peak-width strata, and one to four phases. Components within the same mixture have different FWHM values and independent six-component reciprocal-metric perturbations derived from the stored `d, h, k, l` data. A single zero shift is applied to the complete synthetic pattern. Each profile is searched against every candidate in the SQLite database. Weight selection uses only the train and validation sets; the test set is evaluated once.

The committed reference run used Python 3.11.9, CrIStMa 0.1.0b12, NumPy 2.4.6 and SciPy 1.17.1 on 64-bit Windows 11 (build 26200), an AMD Ryzen AI 9 365 processor (10 cores/20 logical processors), and 19.6 GiB RAM. Ranking used the complete local SQLite cache and required no network access. A separate single-process sample of 16 balanced profiles measures interactive latency without multiprocessing:

- median time for one XRD pattern searched against all 1,058 candidates: 2.043 s;
- 95th percentile: 2.715 s;
- median all-candidate quick pass: 0.798 s, or 0.755 ms per candidate;
- median exact refinement: 1.160 s for 97 shortlisted candidates;
- estimated sequential time for all 192 benchmark profiles: 392.3 s, or 6.54 min.

The full benchmark represents 203,136 quick candidate comparisons. This batch duration is useful for method development; normal application use processes one XRD pattern at a time, so the single-pattern latency is the user-facing value.

For context, refreshing the fixed 1,058-entry source set from the live COD service transferred 15.63 MiB in 46.5 s using eight concurrent requests under the tested network conditions. Recalculating and indexing all entries with CrIStMa then took 637.9 s (10.6 min, about 0.60 s per CIF), while constructing the compact benchmark SQLite from the completed index took 0.66 s. Network timing is environment-dependent and is reported separately from the local search time.

Reference tables are in `reference_results`. Large feature caches and generated profiles belong under `build` and are not committed.

## Joint Gain benchmark

The existing greedy Gain engine remains the default. A smoke run of the joint NNLS beam-search engine is:

```powershell
python -m benchmarks.match.evaluate_gain `
  --dataset benchmarks/match/data/match_benchmark.sqlite `
  --output build/gain-joint-smoke `
  --scenario-set targeted `
  --splits validation `
  --shortlist 60 `
  --gain-engine joint-beam `
  --workers 1
```

Select the derivative, complexity and excess-intensity terms on validation stress cases, then evaluate the locked configuration on held-out test cases with:

```powershell
python -m benchmarks.match.joint_gain_sensitivity `
  --dataset benchmarks/match/data/match_benchmark.sqlite `
  --output build/gain-joint-sensitivity `
  --workers 4
```

The Gain CSV and Markdown summary report retrieval, candidate-profile construction and beam-search time separately. Batch wall time includes many synthetic patterns and multiprocessing overhead; it is not the interactive latency seen when an operator processes one XRD pattern. The single-pattern total and its retrieval/profile/beam breakdown are the relevant application measurements.

## Optimization conclusions

With phase-specific widths and anisotropic metric perturbations, changing the four linear Match weights has a measurable effect. Relative to the current `0.44/0.43/0.08/0.05` weights, the validation-selected `0.170/0.830/0.000/0.000` weights improve held-out Top-1 from 60.94% to 65.62%, Top-10 from 84.38% to 85.94%, and mixture Recall@10 from 48.44% to 49.48%; Top-5 remains 79.69%. The zero weights assigned to the line-count and alignment-seed components on this synthetic set make experimental confirmation especially important. The selected weights are therefore reported as a sensitivity result and are not promoted to the application default.

The Gain shortlist sweep isolates a similar limitation:

| Profile shortlist | Median time | Shortlist recall | Top-1 | Top-10 |
|---:|---:|---:|---:|---:|
| 24 | 1.417 s | 85.42% | 47.92% | 77.08% |
| 40 | 1.831 s | 89.58% | 47.92% | 81.25% |
| 100 | 5.110 s | 95.83% | 47.92% | 81.25% |

Increasing the shortlist beyond about 40 candidates adds substantial profile-calculation time without improving Top-1 or Top-10. The next benchmark iteration should therefore test changes to the ranking evidence: peak-position errors normalized by measured FWHM, noise-aware line confidence, candidate-specific profile width, and joint non-negative profile competition among the final candidates. Gain also needs deliberately constructed direct, overlap, hidden, sparse-line, and low-fraction cases divided into train, validation, and held-out test sets before its numerical policy is tuned.

The targeted Gain set contains 120 cases, evenly divided across train, validation, and test and across the five intended difficulty modes. Its current generator uses one global zero shift, phase-specific reciprocal-metric perturbations, and different phase widths. Gain first estimates the global zero from the accepted phase, refines each indexed candidate metric with that zero fixed, and estimates FWHM again for each candidate. On the 40 held-out cases with a 24-candidate shortlist, the current policy obtains 20.00% Top-1, 52.50% Top-5, and 65.00% Top-10 with 77.50% shortlist recall. Median time is 2.950 s per pattern. Direct cases remain reliable (75.00% Top-1 and 100.00% Top-5); hidden, sparse, and low-fraction cases expose the remaining weakness.

The generator can also apply a synthetic Caglioti resolution floor with `--instrument-data`. Passing `--instrument-model` makes the candidate profiles use the same angle-dependent minimum width. In a controlled held-out comparison with identical instrument-broadened profiles and a 40-candidate shortlist, modelling the known resolution function raised Top-1 from 10.00% to 15.00%, Top-10 from 37.50% to 47.50%, and shortlist recall from 50.00% to 65.00%. Direct-mode Top-1 increased from 37.50% to 62.50% and Top-10 from 50.00% to 87.50%. Median latency increased from 1.680 s to 2.280 s per pattern. The full comparison is saved in `build/gain-instrument-comparison.md`.

An end-to-end run is available with `--accepted-from-match`. It performs Match against all 1,058 phases, accepts the first ranked candidate, subtracts its fitted profile, and then runs Gain. On the held-out instrument-broadened set, the dominant true family was in Match Top-1/Top-5/Top-10 in 57.50%/82.50%/92.50% of cases, while the accepted Top-1 candidate belonged to any true mixture family in 62.50%. Applying the known instrument resolution to the accepted profile and Gain candidates raised end-to-end Gain Top-1 from 12.50% to 17.50%, Top-10 from 50.00% to 57.50%, and shortlist recall from 52.50% to 67.50%. For the 25 cases where Match selected a true family, Gain Top-1 doubled from 12.00% to 24.00% and shortlist recall rose from 28.00% to 52.00%. This shows that accurate Match subtraction improves Gain, but blindly accepting Match Top-1 is still unsafe; the next pipeline should jointly test several leading Match families. Full results are in `build/match-gain-pipeline-comparison.md`.

Increasing the physical shortlist from 40 to 100 raises recall only from 75.00% to 77.50%, leaves Top-1 and Top-10 unchanged, and increases median latency from about 2.15 s to 4.42 s. Hybrid retrieval also fails to improve the fixed-size shortlist. A sparse-candidate profile blend selected on validation did not transfer to held-out test data and was rejected. The main remaining task is therefore a dedicated one- and two-dominant-line retrieval stage followed by joint profile competition, not a larger shortlist or another global Gain weight.

An experimental FWHM-adaptive positional tolerance reduces held-out Top-1 with the current weights from 60.94% to 51.56% and Top-10 from 84.38% to 78.12%. It also raises the median single-pattern runtime from 2.043 s to 4.146 s. This experiment remains benchmark-only and is rejected as a replacement for the fixed retrieval tolerance. The result supports using FWHM as separate profile-consistency evidence rather than narrowing the Match tolerance itself.

## Dataset provenance

`source_manifest.json` records the source and checksum information. Rebuild the SQLite file with `python -m benchmarks.match.build_dataset`. The reference database SHA-256 is:

```text
7d1c4017d58f8369ace1c763b030da2b4e599c817a7c2cf333d9a75b592238ad
```

