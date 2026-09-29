# Match Weight Benchmark Design

## Purpose

Build a compact, reproducible benchmark that selects and validates the four weights used by the XRD Phase Finder Match score and quantitatively evaluates the subsequent Gain ranking. The benchmark must support the methodological claims in the manuscript, remain small enough to store in the public GitHub repository, and exercise the same peak detection, Match, residual construction, and Gain implementation used by the application.

The benchmark must answer four questions:

1. Which weight vector ranks the correct phase most reliably?
2. How stable is that choice across noise, phase overlap, phase count, minor-phase fraction, peak width, background, intensity distortion, and axis error?
3. Does the selected vector generalize to held-out phases and experimental RRUFF patterns?
4. What accuracy and runtime should a user expect for the packaged benchmark and for the complete local database?
5. How reliably does Gain recover a known additional phase after the dominant phase has been accepted?
6. How do the direct, overlap, hidden, and sparse-evidence branches affect that recovery?

## Scope

The repository will contain Python benchmark code and one compact SQLite dataset. It will not contain CIF files, atom lists, the proprietary PDF-2 database, the user's private library, or a copy of the complete application cache.

The first benchmark release evaluates both Match and Gain. Match weights are optimized; Gain is formally characterized and sensitivity-tested without silently retuning its thresholds in the primary experiment.

The working application's weights remain unchanged until the benchmark has produced held-out results. The manuscript must not be updated to a new formula before that result is available.

## Data Sources

### Structural reference library

The public dataset will be built from peak-indexed COD records already present in the local cache. The current cache contains 1,060 COD entries with indexed peaks. For each retained entry the benchmark stores only:

- COD identifier;
- formula, name, space group, and normalized formula key;
- source and source-version metadata;
- up to 64 calculated reflections with 2theta, d spacing, normalized intensity, and optional hkl/multiplicity;
- a duplicate-family identifier used for dataset splitting.

Entries with fewer than three usable reflections in the benchmark angular interval are rejected. Exact duplicate peak lists are collapsed. Near-duplicate structures remain available as realistic hard distractors but are assigned to the same split family.

Materials Project and USER records may be used by an optional local evaluation mode but are not copied to the public benchmark. PDF-2 is excluded from the public dataset.

### Experimental external test

The local RRUFF installation contains 1,484 measured powder patterns. A stratified subset of 48 to 60 patterns will be selected using the following criteria:

- a clear primary mineral name and formula;
- a corresponding COD phase family in the structural library;
- coverage of sparse, dense, narrow, broad, clean, and noisy patterns;
- no dependence on a single mineral family;
- duplicate specimens retained only when they add a materially different profile.

The RRUFF subset is an external robustness test and never participates in weight fitting. Possible impurities and secondary phases are recorded as a limitation. Evaluation targets the reported primary mineral family rather than requiring a single exact COD entry.

Profiles are stored as compressed float32 arrays in SQLite BLOBs together with the original angular step and RRUFF identifier. The intended SQLite file size is at most 20 MiB; the builder fails if the limit is exceeded.

### Organic cases

The benchmark will include three measured organic PXRD patterns published by the International Union of Crystallography as organic powder-diffraction self-test materials:

- aspirin, as the simpler single-polymorph case;
- sucrose, as a more conformationally complex case;
- anhydrous beta-caffeine, as the hard case with a large unit cell and dense line overlap.

The normalized Cu K-alpha XYE profiles are small enough for the compact benchmark and have documented acquisition conditions. If their redistribution terms permit bundling, the profiles are stored in SQLite; otherwise the repository stores a deterministic downloader, source URLs, and expected hashes. Each profile is paired with a verified open COD structure or phase-family target. The dataset builder records the source URL, download hash, citation, redistribution terms, radiation, geometry, angular range, and target COD identifier. A measured pattern is admitted only after its target has been reproduced from the chosen structure within a documented tolerance; ambiguous mappings fail dataset construction.

These measured organic profiles form a separate external-test stratum and do not influence weight fitting. Controlled synthetic organic mixtures may additionally be generated from their verified structures to test phase fraction, overlap, noise, FWHM, and Gain under known ground truth. Reports must distinguish measured and synthetic results.

## SQLite Dataset

The versioned database is stored at `benchmarks/match/data/match_benchmark.sqlite` and contains these logical tables:

- `dataset_meta`: schema version, build timestamp, source snapshots, angular range, wavelength, content hash, and size limit;
- `reference_phases`: public identity and split-family metadata;
- `reference_peaks`: the strongest usable calculated reflections;
- `experimental_patterns`: RRUFF and IUCr metadata, provenance, citation, and compressed x/y profile arrays;
- `experimental_targets`: accepted phase-family targets for each measured pattern;
- `phase_categories`: inorganic, organic, or mixed classification with the rule used;
- `split_assignments`: fixed train, validation, or test assignment by phase family;
- `scenario_definitions`: deterministic synthetic scenario parameters and random seeds;
- `scenario_components`: phases and fractions in each synthetic mixture.

The database is immutable during benchmark execution. Results are written to separate CSV and JSON files so a run cannot alter the source dataset.

## Dataset Splitting

Synthetic query-generating phases are divided into train, validation, and test sets in a 60/20/20 ratio. The split is grouped by normalized formula and diffraction-similarity family. Therefore polymorph duplicates and nearly identical entries cannot leak between partitions.

Every ranking query uses the full packaged candidate library as distractors. Only the identity of phases used to generate the query is split. The test partition remains unopened until the weight-search and selection rules have been finalized from train and validation results.

The split and all scenario seeds are committed to SQLite. Rebuilding the database from the same source snapshot must reproduce the same assignments and scenarios.

## Synthetic Profile Generation

Synthetic queries are generated on a fixed 2theta grid and passed through the application's production `observed_peak_records` function. Match therefore receives detected peaks, rather than ideal lines supplied directly by the benchmark.

Each reference stick pattern is broadened with the production pseudo-Voigt profile implementation. Components are scaled and summed before background and noise are applied.

The scenario design covers:

- phase count: 1, 2, 3, and 4;
- component fractions: balanced mixtures and major/minor mixtures down to an 8% nominal component;
- FWHM: 0.08, 0.15, 0.30, and 0.50 degrees;
- overlap: ordinary random combinations and deliberately selected high-overlap combinations;
- counting noise: none, low, medium, and high, generated with Poisson statistics at fixed count levels;
- additive detector noise: fixed fractions of the strongest peak;
- background: flat, sloped, curved, and broad amorphous contribution;
- zero shift: values within plus or minus 0.30 degrees;
- axis scale: values within plus or minus 0.5%;
- intensity distortion: none, moderate, and strong line-wise log-normal perturbation.

The benchmark uses a balanced deterministic sample of combinations instead of the full Cartesian product. Every principal factor appears independently and in pairwise combinations with phase count, noise, overlap, and FWHM.

Organic phase families are sampled as an explicit stratum rather than left to random selection.

### FWHM analysis

FWHM is both a controlled input and a reported stratum. The report must show:

- ranking metrics at every FWHM level;
- interaction of FWHM with noise;
- interaction of FWHM with overlap;
- observed peak-recovery rate at every FWHM;
- whether the selected Match weights change when broad and narrow patterns are optimized separately;
- sensitivity to the Match line tolerance and the peak detector's minimum separation.

This separates failures caused by the Match formula from failures caused by peak detection or an inappropriate tolerance.

## Match Components and Weight Search

The benchmark extracts the four unweighted components returned by the production Match implementation:

1. observed-line coverage;
2. reference-line coverage;
3. sufficient-line support;
4. alignment-seed support.

The production scorer will expose these component values and accept an explicit weight vector. The default application call retains the current values until benchmark selection is complete.

Candidate features are computed once per query. Weight search then ranks candidates from the cached feature matrix, avoiding repeated peak matching.

All weights are non-negative and sum to one. Search proceeds in two stages:

1. simplex grid search with a 0.025 step;
2. local refinement around the best stable region with a 0.005 step.

The selection target is macro-averaged mean reciprocal rank of the dominant phase family across scenario strata. Ties within its bootstrap uncertainty are resolved by, in order:

1. higher worst-stratum Recall@5;
2. higher all-component Recall@10 for mixtures;
3. a wider near-optimal neighborhood in weight space;
4. simpler rounded weights.

The held-out test set is evaluated once with the selected vector.

## Comparisons and Ablations

Every report compares:

- manuscript weights: 0.62/0.25/0.08/0.05;
- current application weights: 0.44/0.43/0.08/0.05;
- equal weights: 0.25/0.25/0.25/0.25;
- validation-selected weights;
- four ablations, each setting one component weight to zero and renormalizing the remainder.

The sensitivity analysis also varies:

- maximum observed lines;
- maximum reference lines;
- peak detector minimum separation;
- Match line tolerance;
- FWHM.

Only the four Match weights are optimized in the primary experiment. Detector and tolerance sweeps are reported as sensitivity analyses so the weight search does not silently absorb unrelated parameter tuning.

## Gain Definition and Evaluation

For each synthetic mixture containing at least two phases, the benchmark first supplies the known dominant phase as the accepted phase and uses the production simultaneous profile scaling to construct the residual. It then ranks the remaining candidate phases with Gain. This isolates the behavior the manuscript describes: conditional ranking of an additional phase after a major phase has been accepted.

The benchmark records the numerical stage-selection rules used by the application:

- `direct` evidence is used when at least two qualifying residual lines are available;
- if fewer than two direct lines qualify, `overlap` evidence is used when at least two overlap lines qualify;
- otherwise the candidate is evaluated by the `hidden` stage;
- a pattern is classified as sparse when the strongest of its ten strongest calculated lines contributes at least 45% of their summed intensity, or when the two strongest lines contribute at least 65%.

The runner must obtain these values from one shared policy object used by production code and reporting. The numbers may not be duplicated independently in the benchmark and application.

Gain evaluation reports:

- Top-1, Top-5, and Top-10 rank of the known next phase;
- mean reciprocal rank of the next phase;
- stage chosen for every candidate and true phase;
- results grouped by direct, overlap, hidden, and sparse classifications;
- sensitivity to phase fraction, residual noise, FWHM, overlap, line tolerance, and number of residual lines;
- failures caused by an incorrect accepted major phase as a separate stress test, not part of the primary Gain metric.

The formal report includes the exact residual definition, line qualification rules, tolerances, stage precedence, sparse-pattern definition, profile-support term, excess-profile penalty, and final bounding of Gain. This material is generated from the shared policy and implementation constants so it can be transferred to the manuscript without contradicting the code.

## Metrics

Primary metric:

- macro-averaged mean reciprocal rank of the dominant phase family.

Secondary metrics:

- Top-1, Top-5, and Top-10 dominant-phase accuracy;
- Recall@5 and Recall@10 for all phase families in a mixture;
- Gain Top-1, Top-5, Top-10, and mean reciprocal rank for the known next phase;
- median and 90th-percentile rank;
- peak-detection precision and recovery for synthetic ground truth;
- metrics stratified by noise, phase count, minor fraction, overlap, FWHM, background, and axis distortion;
- bootstrap 95% confidence intervals using query groups;
- runtime for feature extraction and ranking.

The report includes both macro averages and stratum tables. A gain in easy single-phase cases cannot compensate invisibly for a large loss in broad, noisy, or multiphase cases.

## Full-Database Runtime Mode

The packaged benchmark is the reproducible accuracy test. A separate optional command evaluates runtime and ranking against the user's complete local cache without copying that cache into the repository.

This mode records:

- number of candidate phases and indexed lines;
- source counts and cache versions;
- CPU, operating system, Python version, and application version;
- cold and warm runtime;
- query scenario identifier;
- resulting ranks and metrics.

The full-database output is a portable JSON/CSV result artifact suitable for the manuscript's timing description.

## Code Layout

The benchmark will be isolated from the GUI:

- `benchmarks/match/build_dataset.py`: construct and validate the compact SQLite dataset;
- `benchmarks/match/dataset.py`: read-only typed access to the benchmark schema;
- `benchmarks/match/generate_profiles.py`: deterministic synthetic mixture and degradation generation;
- `benchmarks/match/extract_features.py`: production peak detection and Match component extraction;
- `benchmarks/match/evaluate_gain.py`: accepted-phase residual construction, Gain staging, and next-phase ranking;
- `benchmarks/match/optimize_weights.py`: train/validation simplex search;
- `benchmarks/match/evaluate.py`: held-out, RRUFF, sensitivity, and timing evaluation;
- `benchmarks/match/report.py`: CSV, JSON, and Markdown summaries;
- `benchmarks/match/README.md`: exact reproduction commands and interpretation;
- `tests/benchmark/`: schema, determinism, split-leakage, profile-generation, metric, and smoke tests.

No new runtime dependency is required. The implementation uses Python's `sqlite3`, NumPy, SciPy, and existing XRD Phase Finder services.

## Outputs

A standard run writes:

- `weight_search.csv`: all evaluated weight vectors and validation metrics;
- `selected_weights.json`: selected vector, objective, confidence interval, and dataset hash;
- `comparison.csv`: manuscript, current, equal, selected, and ablation results;
- `sensitivity.csv`: factor-level and interaction results, including FWHM;
- `experimental_external.csv`: measured RRUFF and IUCr organic pattern ranks and quality notes;
- `gain_evaluation.csv`: next-phase ranks, selected stages, sparse flags, and residual conditions;
- `gain_definition.md`: implementation-derived formal definition and all numerical thresholds;
- `organic_cases.csv`: measured IUCr organic results and separately labeled synthetic-organic results;
- `runtime.json`: packaged and optional full-cache timings;
- `summary.md`: manuscript-ready tables and a concise methods description.

Generated result files are ignored by default except for one reviewed reference result set used by the manuscript.

## Validation and Acceptance Criteria

The implementation is accepted when:

1. rebuilding from the same source cache and seed produces the same dataset content hash;
2. the SQLite file is at most 20 MiB and passes integrity and foreign-key checks;
3. no split family occurs in more than one of train, validation, and test;
4. synthetic profiles are processed through production peak detection and Match components;
5. a smoke run compares both existing weight vectors and completes without the GUI;
6. the full run produces all specified metrics and FWHM analyses;
7. RRUFF and IUCr organic results are reported separately and never influence selected weights;
8. Gain stage selection and sparse-pattern thresholds come from one production policy object and are reproduced in the report;
9. measured and synthetic organic results are labeled separately, and every measured profile retains its provenance and verified structural target;
10. the application default and manuscript formula are changed only after reviewing held-out results;
11. benchmark tests and the existing application test suite pass.

## Known Limitations

Synthetic mixtures do not reproduce every sample-preparation, preferred-orientation, or instrument effect. RRUFF supplies an experimental check but may contain impurities, secondary phases, and heterogeneous acquisition conditions. The manuscript must describe the benchmark as validation over the stated factors, not as proof of universal identification accuracy.
