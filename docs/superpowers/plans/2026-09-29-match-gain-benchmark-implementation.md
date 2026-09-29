# Match and Gain Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a compact, reproducible SQLite benchmark that selects Match weights and measures Match/Gain robustness across phase count, noise, overlap, FWHM, line count, tolerance, and measured inorganic and organic PXRD patterns.

**Architecture:** First expose Match components and Gain policy/scoring as headless production APIs. Then build an immutable SQLite dataset from the local COD peak index plus measured RRUFF and IUCr profiles, generate deterministic synthetic scenarios, cache candidate features, optimize only the four Match weights, and report held-out Match/Gain sensitivity without changing application defaults automatically.

**Tech Stack:** Python 3.11, sqlite3, NumPy, SciPy, existing XRD Phase Finder services, unittest, Markdown/CSV/JSON outputs.

**Spec:** `docs/superpowers/specs/2026-09-29-match-weight-benchmark-design.md`

## Global Constraints

- Keep `match_benchmark.sqlite` at or below 20 MiB.
- Do not bundle PDF-2, private USER data, Materials Project data, CIF atom lists, or the complete application cache.
- Use no new runtime dependency.
- Fit weights only on train/validation phase families; evaluate the held-out test once after selection.
- Keep measured RRUFF and IUCr cases out of weight fitting.
- Preserve the current application weights until held-out results have been reviewed.
- Treat adaptive parameters as a secondary model selected by nested grouped validation; keep the fixed baseline when improvement is not robust.
- Obtain Gain stages and sparse thresholds from one production policy object.
- Store IUCr profiles only when redistribution terms permit; otherwise download by pinned URL and verify SHA-256.

## Review Focus

- An interrupted or offline IUCr download must leave no partial dataset and must explain which pinned artifact is unavailable; Task 3 tests this.
- Duplicate or near-duplicate phases must never cross train/validation/test families; Task 4 tests this.
- A broad/noisy profile with fewer recovered peaks must remain a valid scenario rather than silently disappearing; Task 5 tests this.
- Match caps for insufficient observed support must remain identical when custom weights are supplied; Task 1 tests this.
- Gain must use the same stage and sparse decisions in the GUI and benchmark; Task 2 and Task 7 test this.

---

### Task 1: Parameterize the production Match score

**Files:**
- Modify: `xrd_finder/finder/fingerprint_matching.py`
- Modify: `tests/test_fingerprint_matching.py`

**Interfaces:**
- Produces: `MatchWeights(observed_coverage, reference_coverage, sufficient_lines, alignment_seed)`.
- Produces: `FingerprintMatchFeatures(observed_coverage, reference_coverage, sufficient_lines, alignment_seed, observed_matched, reference_matched, anchor_count)`.
- Produces: `apply_match_weights(features: FingerprintMatchFeatures, weights: MatchWeights) -> float`.
- Extends: `fingerprint_match_score(..., weights: MatchWeights = DEFAULT_MATCH_WEIGHTS) -> FingerprintMatchResult` and returns its features.

- [ ] **Step 1: Write failing tests for default compatibility and explicit weights**

Add tests asserting that the default score is unchanged, the four components are in `[0, 1]`, invalid negative/non-unit weights raise `ValueError`, and `0.62/0.25/0.08/0.05` changes only the weighted score and not alignment or matched-line counts.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m unittest tests.test_fingerprint_matching -v`

Expected: FAIL because `MatchWeights`, exposed features, and the `weights` argument do not exist.

- [ ] **Step 3: Implement the dataclasses, validation, and pure weighted scorer**

Keep the current caps for insufficient observed/reference support inside `apply_match_weights`; do not move them into benchmark code.

- [ ] **Step 4: Run Match tests**

Run: `python -m unittest tests.test_fingerprint_matching tests.test_auto_search_ranker -v`

Expected: PASS.

- [ ] **Step 5: Commit only Task 1 files**

Commit message: `refactor: expose match score components`

### Task 2: Centralize Gain policy and expose a headless ranking API

**Files:**
- Create: `xrd_finder/finder/gain_policy.py`
- Create: `xrd_finder/finder/gain_ranking.py`
- Modify: `xrd_finder/ui/gain_scoring.py`
- Modify: `xrd_finder/services/gain_shortlist.py`
- Modify: `xrd_finder/ui/analysis_windows.py`
- Modify: `tests/test_gain_shortlist.py`
- Create: `tests/test_gain_policy.py`
- Create: `tests/test_gain_ranking.py`

**Interfaces:**
- Produces: `GainStage`, `GainPolicy`, and `DEFAULT_GAIN_POLICY` from `xrd_finder.finder.gain_policy`.
- `GainPolicy` owns `minimum_stage_records=2`, `sparse_strongest_fraction=0.45`, and `sparse_two_strongest_fraction=0.65` plus existing residual/profile thresholds.
- Produces: `GainQuery` and `rank_gain_candidates(query: GainQuery, candidates: Sequence[GainCandidate], policy: GainPolicy = DEFAULT_GAIN_POLICY) -> list[GainRankingResult]`.
- The GUI imports or re-exports these definitions and delegates scoring to the headless API.

- [ ] **Step 1: Write failing policy tests**

Assert direct at two direct records, overlap at fewer than two direct and at least two overlap records, hidden otherwise; assert sparse at exactly 45% strongest or 65% top-two and non-sparse immediately below both boundaries.

- [ ] **Step 2: Run policy tests and verify failure**

Run: `python -m unittest tests.test_gain_policy -v`

Expected: FAIL because the shared finder policy module does not exist.

- [ ] **Step 3: Move policy and sparse classification into the finder layer**

Keep compatibility re-exports in `xrd_finder/ui/gain_scoring.py`; replace numerical duplicates in GUI and shortlist code with policy fields.

- [ ] **Step 4: Write failing headless-vs-production ranking tests**

Use fixed synthetic arrays and candidates to assert identical stage, scale, profile contribution, bounded Gain, and ordering for direct, overlap, hidden, and sparse cases.

- [ ] **Step 5: Implement the headless Gain request/result types and GUI delegation**

Extract pure numerical work from `analysis_windows.py`; GUI code remains responsible only for collecting current state, progress presentation, and table updates.

- [ ] **Step 6: Run Gain and selected-phase tests**

Run: `python -m unittest tests.test_gain_policy tests.test_gain_shortlist tests.test_gain_ranking -v`

Expected: PASS.

- [ ] **Step 7: Commit only Task 2 files**

Commit message: `refactor: share gain ranking policy`

### Task 3: Build and validate the compact SQLite source dataset

**Files:**
- Create: `benchmarks/__init__.py`
- Create: `benchmarks/match/__init__.py`
- Create: `benchmarks/match/schema.sql`
- Create: `benchmarks/match/dataset.py`
- Create: `benchmarks/match/build_dataset.py`
- Create: `benchmarks/match/sources.py`
- Create: `benchmarks/match/source_manifest.json`
- Modify: `THIRD_PARTY_DATA_SOURCES.md`
- Create: `tests/benchmark/__init__.py`
- Create: `tests/benchmark/test_dataset.py`
- Create: `tests/benchmark/test_sources.py`

**Interfaces:**
- Produces: `BenchmarkDataset.open(path: Path, *, immutable: bool = True) -> BenchmarkDataset`.
- Produces: `build_dataset(config: BuildConfig) -> DatasetBuildResult` with content hash, row counts, and byte size.
- Produces: `fetch_pinned_source(spec: SourceSpec, cache_dir: Path) -> Path` with atomic rename and SHA-256 validation.
- Consumes: local COD `LocalPhaseCache.entries_with_peaks()` and `peak_records()`; measured RRUFF files; pinned IUCr aspirin, sucrose, and beta-caffeine XYE URLs.

- [ ] **Step 1: Write failing schema and source tests**

Assert foreign keys, immutable reopening, source hashes, no incomplete files after simulated download failure, exclusion of non-COD/private records, and failure above 20 MiB.

- [ ] **Step 2: Run dataset tests and verify failure**

Run: `python -m unittest tests.benchmark.test_dataset tests.benchmark.test_sources -v`

Expected: FAIL because benchmark dataset modules do not exist.

- [ ] **Step 3: Implement schema, typed reader, and atomic pinned-source fetcher**

Schema includes the tables listed in the spec and stores compressed little-endian float32 X/Y arrays for measured profiles.

- [ ] **Step 4: Implement the builder and provenance validation**

Normalize formulas, reject references with fewer than three usable reflections, collapse exact duplicate peak lists, store up to 64 lines, and require every measured target to match a verified phase family.

- [ ] **Step 5: Build a temporary database and run integrity checks**

Run: `python -m benchmarks.match.build_dataset --output build/benchmark-smoke.sqlite --smoke`

Expected: SQLite integrity `ok`, foreign-key violations `0`, no forbidden sources, size below 20 MiB.

- [ ] **Step 6: Commit Task 3 code and documentation without committing downloaded source caches**

Commit message: `feat: add benchmark dataset builder`

### Task 4: Create deterministic split families and scenario manifests

**Files:**
- Create: `benchmarks/match/splits.py`
- Create: `benchmarks/match/scenarios.py`
- Create: `tests/benchmark/test_splits.py`
- Create: `tests/benchmark/test_scenarios.py`

**Interfaces:**
- Produces: `assign_split_families(phases, *, seed: int) -> tuple[SplitAssignment, ...]`.
- Produces: `build_scenario_manifest(dataset: BenchmarkDataset, config: ScenarioConfig) -> tuple[ScenarioDefinition, ...]`.
- Groups by normalized formula plus diffraction-similarity family and writes fixed 60/20/20 query-generator assignments.

- [ ] **Step 1: Write failing split and determinism tests**

Assert no family leakage, stable hashes for repeated seeds, changed assignments for a different seed, 1–4 phase coverage, 8% minor components, all FWHM levels, and explicit organic strata.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m unittest tests.benchmark.test_splits tests.benchmark.test_scenarios -v`

Expected: FAIL because split and scenario modules do not exist.

- [ ] **Step 3: Implement similarity grouping and balanced deterministic sampling**

Avoid the full Cartesian product; ensure every principal factor occurs alone and paired with noise, overlap, phase count, and FWHM.

- [ ] **Step 4: Run split/scenario tests**

Run: `python -m unittest tests.benchmark.test_splits tests.benchmark.test_scenarios -v`

Expected: PASS with a stable scenario manifest hash.

- [ ] **Step 5: Commit Task 4 files**

Commit message: `feat: define benchmark scenarios`

### Task 5: Generate profiles and recover observed peaks through production code

**Files:**
- Create: `benchmarks/match/generate_profiles.py`
- Modify: `xrd_finder/finder/observed_pattern_processor.py`
- Modify: `xrd_finder/ui/peak_matching.py`
- Create: `tests/benchmark/test_generate_profiles.py`
- Modify: `tests/test_fingerprint_matching.py`

**Interfaces:**
- Produces: `generate_profile(dataset, scenario, *, seed: int) -> GeneratedPattern` containing X/Y, clean components, ground-truth lines, background, and perturbation metadata.
- Produces: a shared `PeakDetectionPolicy(minimum_separation_deg=0.11, ...)` consumed by both observed-pattern entry points.
- Produces: `detect_benchmark_peaks(pattern, policy, limit) -> list[ObservedLineRecord]` by calling production detection.

- [ ] **Step 1: Write failing profile tests**

Assert deterministic pseudo-Voigt profiles, requested FWHM within tolerance, component fractions before noise, correct zero/scale transformations, and preservation of broad/noisy scenarios even when fewer peaks are detected.

- [ ] **Step 2: Run profile tests and verify failure**

Run: `python -m unittest tests.benchmark.test_generate_profiles -v`

Expected: FAIL because the generator and shared detection policy do not exist.

- [ ] **Step 3: Implement generation using production pseudo-Voigt functions**

Apply components, intensity distortion, background, Poisson noise, detector noise, zero shift, and axis scale in the order fixed by the scenario definition.

- [ ] **Step 4: Centralize the detector separation parameter and call production peak detection**

Do not implement a benchmark-only detector. Record precision and recovery against synthetic ground-truth lines.

- [ ] **Step 5: Run profile and existing detection tests**

Run: `python -m unittest tests.benchmark.test_generate_profiles tests.test_fingerprint_matching tests.test_auto_search_ranker -v`

Expected: PASS.

- [ ] **Step 6: Commit Task 5 files**

Commit message: `feat: generate benchmark xrd profiles`

### Task 6: Cache Match features and optimize weights

**Files:**
- Create: `benchmarks/match/extract_features.py`
- Create: `benchmarks/match/metrics.py`
- Create: `benchmarks/match/optimize_weights.py`
- Create: `tests/benchmark/test_match_evaluation.py`
- Create: `tests/benchmark/test_weight_search.py`

**Interfaces:**
- Produces: `extract_match_features(dataset, scenarios, config) -> FeatureMatrix`.
- Produces: `rank_feature_matrix(matrix, weights: MatchWeights) -> RankingResults`.
- Produces: `optimize_weights(train, validation, config) -> WeightSelection` using simplex steps `0.025` then `0.005`.
- Produces: `fit_adaptive_policy(train, validation, config) -> AdaptivePolicySelection` using only pre-candidate FWHM, robust noise ratio, peak density, close-peak fraction, and angular step.
- Produces: macro MRR, Top-1/5/10, mixture Recall@5/10, median/P90 rank, bootstrap intervals, and stratum metrics.

- [ ] **Step 1: Write failing metric and leakage tests**

Use a hand-checkable feature matrix to assert ranks, ties, macro averaging by stratum, all-component recall, fixed bootstrap seeds, and rejection if test rows enter optimization.

- [ ] **Step 2: Run Match evaluation tests and verify failure**

Run: `python -m unittest tests.benchmark.test_match_evaluation tests.benchmark.test_weight_search -v`

Expected: FAIL because feature and optimizer modules do not exist.

- [ ] **Step 3: Implement one-time production feature extraction**

Cache component matrices and support/cap metadata so each weight vector only performs vectorized scoring and ranking.

- [ ] **Step 4: Implement the two-stage simplex search and deterministic tie-breaks**

Compare manuscript, current, equal, optimized, and four renormalized ablations; do not open the held-out test partition here.

- [ ] **Step 5: Fit the preregistered low-complexity adaptive candidates**

Compare clipped FWHM-dependent tolerance, FWHM-dependent detector separation, noise/peak-density line-count bins, two-bin weights, and affine interpolation between two weight vectors. Use nested grouped validation and penalize every added coefficient.

- [ ] **Step 6: Run a smoke optimization**

Run: `python -m benchmarks.match.optimize_weights --dataset build/benchmark-smoke.sqlite --smoke`

Expected: completes, sums selected weights to `1.0`, and writes train/validation results only.

- [ ] **Step 7: Commit Task 6 files**

Commit message: `feat: optimize match weights reproducibly`

### Task 7: Evaluate Gain and the full sensitivity matrix

**Files:**
- Create: `benchmarks/match/evaluate_gain.py`
- Create: `benchmarks/match/evaluate.py`
- Create: `tests/benchmark/test_gain_evaluation.py`
- Create: `tests/benchmark/test_sensitivity.py`

**Interfaces:**
- Produces: `evaluate_gain(dataset, mixture_scenarios, config) -> GainEvaluation` with the known dominant phase supplied as accepted.
- Produces: `run_evaluation(dataset, selected_weights, config) -> EvaluationBundle`.
- Compares the selected fixed policy with the selected adaptive policy on the untouched test set and difficult strata.
- Sweeps observed/reference line limits, detector minimum separation, Match tolerance, FWHM, noise, overlap, phase fraction, and phase count without fitting those settings as weights.

- [ ] **Step 1: Write failing Gain benchmark tests**

Assert the known next phase target, direct/overlap/hidden/sparse labels from `DEFAULT_GAIN_POLICY`, separate incorrect-major stress results, and no measured case in weight selection.

- [ ] **Step 2: Write failing FWHM and tolerance sensitivity tests**

Assert every configured factor level appears, interaction rows exist for FWHM×noise and FWHM×overlap, and peak-recovery metrics accompany ranking metrics.

Also assert adaptive predictors are computed from the observed query alone, coefficients are fixed before test evaluation, and a policy is rejected when its confidence interval overlaps while its worst-stratum Recall@5 decreases.

- [ ] **Step 3: Implement Gain evaluation through the headless production API**

Build residuals from jointly scaled accepted profiles and report next-phase Top-1/5/10 and MRR by stage.

- [ ] **Step 4: Implement held-out, measured-pattern, and sensitivity evaluation**

Open the held-out partition only here; report IUCr aspirin, sucrose, beta-caffeine and RRUFF independently from synthetic test scenarios.

- [ ] **Step 5: Run evaluation tests and smoke evaluation**

Run: `python -m unittest tests.benchmark.test_gain_evaluation tests.benchmark.test_sensitivity -v`

Run: `python -m benchmarks.match.evaluate --dataset build/benchmark-smoke.sqlite --smoke`

Expected: PASS and all required strata are present.

- [ ] **Step 6: Commit Task 7 files**

Commit message: `feat: evaluate gain and match sensitivity`

### Task 8: Produce reproducible reports and the public reference dataset

**Files:**
- Create: `benchmarks/match/report.py`
- Create: `benchmarks/match/README.md`
- Create: `benchmarks/match/data/match_benchmark.sqlite`
- Create: `benchmarks/match/reference_results/summary.md`
- Create: `benchmarks/match/reference_results/selected_weights.json`
- Create: `tests/benchmark/test_report.py`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces the output files named in the spec, including `experimental_external.csv`, `gain_definition.md`, `organic_cases.csv`, and `runtime.json`.
- Produces manuscript-ready tables but never edits the manuscript or application default weights automatically.

- [ ] **Step 1: Write failing report completeness tests**

Assert dataset hash and source versions appear in every summary, Gain thresholds equal the policy object, measured/synthetic organic labels differ, all baseline weight vectors are present, and full-cache timing records hardware/cache state.

- [ ] **Step 2: Implement CSV/JSON/Markdown rendering and CLI documentation**

Keep generated bulk outputs ignored; commit only the reviewed reference summary and selected-weight record.

- [ ] **Step 3: Build the release dataset and run the complete benchmark**

Run: `python -m benchmarks.match.build_dataset --output benchmarks/match/data/match_benchmark.sqlite`

Run: `python -m benchmarks.match.optimize_weights --dataset benchmarks/match/data/match_benchmark.sqlite`

Run: `python -m benchmarks.match.evaluate --dataset benchmarks/match/data/match_benchmark.sqlite --full`

Expected: SQLite at or below 20 MiB and every required output generated.

- [ ] **Step 4: Run complete verification**

Run: `python -m unittest discover -s tests -v`

Run: `python -m unittest discover -s tests/benchmark -v`

Expected: PASS.

- [ ] **Step 5: Inspect dataset and report invariants**

Verify SQLite integrity, zero foreign-key violations, zero forbidden-source rows, no split leakage, pinned source hashes, and agreement between reported and production Match/Gain constants.

- [ ] **Step 6: Commit the reviewed benchmark artifacts**

Commit message: `feat: publish match and gain benchmark`

