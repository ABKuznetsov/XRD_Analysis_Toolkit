# Multi-channel Gain Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise Gain candidate-family Recall@24 from 62.5% to at least 80% by combining four cheap residual-evidence retrieval channels while leaving the final profile Gain unchanged.

**Architecture:** Four independent channel functions return ranked, timed `RetrievalHit` records. A deterministic union collapses equivalent diffraction fingerprints, applies a cheap line-level reranker with a soft missing-line penalty, and sends exactly 24 family representatives to the existing residual-window joint Gain. Benchmark attribution selects quotas on development data and evaluates the frozen configuration once on a new untouched family/seed split.

**Tech Stack:** Python 3.11, NumPy, SciPy, SQLite benchmark dataset, `unittest`, existing fingerprint/cell/profile services.

**Spec:** `docs/superpowers/specs/2026-10-02-multichannel-gain-retrieval-design.md`

## Global Constraints

- Keep `GAIN_PROFILE_CANDIDATE_LIMIT = 24`.
- Do not change final joint Gain scoring, Phase-SNR, reporting floors, profile construction, or UI behavior.
- No retrieval channel may access the network during ranking.
- Channel-local scores are not probabilities and are never added without normalization.
- Missing strong lines produce a soft penalty only; they never hard-filter a candidate.
- Accepted diffraction-pattern families must be excluded even when another database card has a different name, formula text, source, or identifier.
- Parameter selection uses development train/validation data only; final results use a newly generated untouched family/seed split once.
- Preserve deterministic ordering with `phase_id` as the final tie-breaker.

## Review Focus

- A noise-only or empty residual returns no candidates and does not manufacture geometry hashes — pinned in Task 2 and Task 3.
- A one-line residual still uses strong/rare retrieval while geometry returns empty — pinned in Task 3.
- An accepted phase cannot return through an equivalent COD/MP/USER card — pinned in Task 5.
- Broad, poorly fitted, and overlap-dominated residual peaks remain usable with reduced confidence rather than disappearing — pinned in Task 2 and Task 4.
- NaN/inf scores, missing widths, and tied channel ranks produce finite deterministic output — pinned in Task 1 and Task 5.

---

### Task 1: Define channel results and timing

**Files:**
- Create: `xrd_finder/services/gain_retrieval_channels.py`
- Test: `tests/test_gain_retrieval_channels.py`

**Interfaces:**
- Produces: `RetrievalHit(phase_id: str, channel: str, score: float, rank: int, evidence_count: int)`.
- Produces: `RetrievalChannelRun(channel: str, hits: tuple[RetrievalHit, ...], elapsed_seconds: float, diagnostic: str = "")`.
- Produces: `rank_channel_scores(channel: str, scores: Mapping[str, float], evidence_counts: Mapping[str, int], *, limit: int) -> RetrievalChannelRun`.
- Produces: stable channel names `strong`, `rare`, `geometry`, and `overlap`.

- [ ] **Step 1: Write failing result-model tests**

Add tests asserting that `rank_channel_scores` removes non-finite/non-positive scores, assigns one-based ranks, truncates at `limit`, and resolves equal scores by `phase_id`. Assert empty input produces an empty run with finite non-negative time.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_gain_retrieval_channels -v`

Expected: FAIL because `gain_retrieval_channels` does not exist.

- [ ] **Step 3: Implement the immutable result models and rank helper**

Create the two frozen slotted dataclasses and `rank_channel_scores` with the exact signatures above. Normalize identifiers to strings, coerce finite numeric values, and keep timing outside ranking decisions.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m unittest tests.test_gain_retrieval_channels -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add xrd_finder/services/gain_retrieval_channels.py tests/test_gain_retrieval_channels.py
git commit -m "feat: define Gain retrieval channel results"
```

### Task 2: Instrument strong and rare residual channels

**Files:**
- Modify: `xrd_finder/services/gain_retrieval_channels.py`
- Modify: `xrd_finder/services/gain_shortlist.py`
- Test: `tests/test_gain_retrieval_channels.py`
- Test: `tests/test_gain_shortlist.py`

**Interfaces:**
- Consumes: `RetrievalChannelRun` and `rank_channel_scores` from Task 1.
- Produces: `strong_residual_channel(candidate_peaks, residual_records, *, limit: int, tolerance: float = 0.45) -> RetrievalChannelRun`.
- Produces: `rare_line_channel(candidate_peaks, residual_records, *, limit: int, tolerance: float = 0.45) -> RetrievalChannelRun`.
- Preserves: existing `rare_line_candidate_scores(...)` behavior for current callers.

- [ ] **Step 1: Write failing strong/rare channel tests**

Use fixtures containing one narrow high-SNR line, one broad low-quality line, one missing-FWHM record, and noise-only records. Assert the narrow supported candidate ranks first, the broad line still contributes fewer evidence points, rare lines rescue a candidate absent from the strong channel prefix, and noise-only input yields empty runs.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_gain_retrieval_channels tests.test_gain_shortlist -v`

Expected: FAIL on the missing channel functions.

- [ ] **Step 3: Add confidence-weighted strong scoring**

Implement `strong_residual_channel` using residual area/prominence, local SNR, FWHM reliability, and fit quality. Reuse existing peak parsing conventions and return channel-local evidence counts without changing profile Gain.

- [ ] **Step 4: Wrap the existing IDF-style rare-line scorer**

Implement `rare_line_channel` around `rare_line_candidate_scores`, retaining inverse database frequency and adding evidence counts for matched significant residual records.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_gain_retrieval_channels tests.test_gain_shortlist -v`

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add xrd_finder/services/gain_retrieval_channels.py xrd_finder/services/gain_shortlist.py tests/test_gain_retrieval_channels.py tests/test_gain_shortlist.py
git commit -m "feat: expose strong and rare Gain retrieval channels"
```

### Task 3: Add zero-shift-invariant two/three-line geometry

**Files:**
- Create: `xrd_finder/services/residual_geometry.py`
- Modify: `xrd_finder/services/gain_retrieval_channels.py`
- Test: `tests/test_residual_geometry.py`
- Modify: `tests/test_gain_retrieval_channels.py`

**Interfaces:**
- Produces: `ResidualGeometryIndex` containing candidate pair/triplet hash postings.
- Produces: `build_residual_geometry_index(candidate_peaks, *, max_lines: int = 14, pair_bin_deg: float = 0.08, ratio_bin: float = 0.02) -> ResidualGeometryIndex`.
- Produces: `residual_geometry_scores(index, residual_records, *, max_lines: int = 10) -> tuple[dict[str, float], dict[str, int]]`.
- Produces: `geometry_channel(index, residual_records, *, limit: int) -> RetrievalChannelRun`.

- [ ] **Step 1: Write failing geometry-hash tests**

Assert pair hashes are unchanged by adding one constant zero shift to all lines, triplet normalized-gap hashes are unchanged by common affine shift/scale inside bin tolerance, neighboring query bins tolerate small angle-dependent displacement, and geometrically different line sets do not receive coherent votes.

- [ ] **Step 2: Add sparse and invalid-input tests**

Assert zero/one usable residual line returns no geometry hits; two lines can vote through pair hashes; three lines add triplet evidence; NaN/duplicate lines are ignored deterministically.

- [ ] **Step 3: Run focused geometry tests and verify RED**

Run: `python -m unittest tests.test_residual_geometry tests.test_gain_retrieval_channels -v`

Expected: FAIL because `residual_geometry` and `geometry_channel` are missing.

- [ ] **Step 4: Implement the compact pair/triplet index**

Use binned 2theta pair separations for common-zero invariance and normalized triplet gaps plus coarse span bins for discrimination. Precompute candidate postings once; expand query bins by one neighbor without scanning all combinations repeatedly.

- [ ] **Step 5: Implement the channel wrapper**

Return geometry vote strength and coherent pair/triplet evidence count through the Task 1 models. Do not synthesize evidence for a one-line residual.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_residual_geometry tests.test_gain_retrieval_channels -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add xrd_finder/services/residual_geometry.py xrd_finder/services/gain_retrieval_channels.py tests/test_residual_geometry.py tests/test_gain_retrieval_channels.py
git commit -m "feat: retrieve Gain candidates by residual geometry"
```

### Task 4: Add overlap-deficit retrieval

**Files:**
- Modify: `xrd_finder/services/gain_retrieval_channels.py`
- Modify: `xrd_finder/services/gain_shortlist.py`
- Test: `tests/test_gain_retrieval_channels.py`
- Modify: `tests/test_gain_unknown_peaks.py`

**Interfaces:**
- Consumes: accepted-profile overlap classification and local-noise evidence already produced by the residual pipeline.
- Produces: `overlap_deficit_channel(candidate_peaks, overlap_records, *, limit: int, tolerance: float = 0.45) -> RetrievalChannelRun`.

- [ ] **Step 1: Write failing deficit-evidence tests**

Construct one accepted-phase peak whose calculated height matches observation, one with a deficit below local noise, and one with a significant positive deficit. Assert only the significant deficit contributes retrieval evidence and that a broad overlap remains eligible with reduced weight.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_gain_retrieval_channels tests.test_gain_unknown_peaks -v`

Expected: FAIL on the missing overlap channel.

- [ ] **Step 3: Implement overlap-deficit scoring**

Reuse `residual_peak_is_explained` and existing overlap records. Score candidate line coverage of noise-significant deficits; do not treat positional overlap without residual intensity as evidence.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_gain_retrieval_channels tests.test_gain_unknown_peaks -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```powershell
git add xrd_finder/services/gain_retrieval_channels.py xrd_finder/services/gain_shortlist.py tests/test_gain_retrieval_channels.py tests/test_gain_unknown_peaks.py
git commit -m "feat: retrieve candidates from overlap deficits"
```

### Task 5: Fuse channels, collapse diffraction families, and rerank to 24

**Files:**
- Create: `xrd_finder/services/gain_retrieval_union.py`
- Modify: `benchmarks/match/gain_retrieval.py`
- Test: `tests/test_gain_retrieval_union.py`
- Modify: `tests/benchmark/test_gain_retrieval.py`

**Interfaces:**
- Consumes: `tuple[RetrievalChannelRun, ...]`, reference lines, accepted IDs, residual records, and overlap positions.
- Produces: `GainRetrievalConfig(channel_limits: tuple[tuple[str, int], ...], union_limit: int = 80, profile_limit: int = 24, missing_line_weight: float = 0.15, rank_corroboration: float = 0.20, pair_bin_deg: float = 0.08, ratio_bin: float = 0.02)`.
- Produces: `GainRetrievalPool(optional_ids: tuple[str, ...], family_assignments: tuple[tuple[str, str], ...], channel_runs: tuple[RetrievalChannelRun, ...], raw_union_count: int, collapsed_family_count: int)`.
- Produces: `build_gain_retrieval_pool(..., *, config: GainRetrievalConfig) -> GainRetrievalPool`.

- [ ] **Step 1: Write failing fusion and quota tests**

Assert a candidate uniquely supplied by each channel survives the initial union, rank fusion is deterministic across score scales, raw union never exceeds 80, and the final pool contains at most 24 family representatives.

- [ ] **Step 2: Write failing family and missing-line tests**

Assert equivalent COD/MP/USER cards consume one slot, every card equivalent to an accepted phase is excluded, a clearly absent strong line demotes but does not eliminate a candidate, and a predicted line below detection or inside accepted overlap is not fully penalized.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `python -m unittest tests.test_gain_retrieval_union tests.benchmark.test_gain_retrieval -v`

Expected: FAIL because the union service is missing.

- [ ] **Step 4: Implement reciprocal-rank union and family collapse**

Use bounded channel prefixes, channel-presence corroboration, existing powder-pattern equivalence, and the stable representative selection rules. Keep alternatives in `family_assignments` for diagnostics.

- [ ] **Step 5: Implement cheap line-level reranking**

Combine normalized residual coverage, channel support, rare/geometry/overlap evidence, and the soft missing-line term. Clamp each term to finite deterministic ranges and return exactly the highest 24 families when at least 24 exist.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_gain_retrieval_union tests.benchmark.test_gain_retrieval -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```powershell
git add xrd_finder/services/gain_retrieval_union.py benchmarks/match/gain_retrieval.py tests/test_gain_retrieval_union.py tests/benchmark/test_gain_retrieval.py
git commit -m "feat: fuse Gain retrieval channels"
```

### Task 6: Wire multichannel retrieval into benchmark-only Gain

**Files:**
- Modify: `benchmarks/match/evaluate_gain.py`
- Modify: `benchmarks/match/joint_gain.py`
- Modify: `tests/benchmark/test_gain_evaluation.py`
- Modify: `tests/benchmark/test_joint_gain.py`

**Interfaces:**
- Consumes: `build_gain_retrieval_pool` from Task 5 and unchanged `evaluate_joint_gain`.
- Produces: `GainRetrievalDiagnostics` on each `GainScenarioResult`, including per-channel ranks/times, union counts, collapse counts, target presence before/after compression, and Recall@24 evidence.
- Preserves: final profile shortlist size 24 and current joint Gain config byte-for-byte.

- [ ] **Step 1: Write failing end-to-end benchmark adapter tests**

Assert all four channel diagnostics are present, unique rescue is attributable, the final optional pool is 24, and the same prepared profiles produce identical final Gain values/ranks when the retrieved 24 IDs are held constant.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.benchmark.test_gain_evaluation tests.benchmark.test_joint_gain -v`

Expected: FAIL on missing multichannel diagnostics and pool construction.

- [ ] **Step 3: Replace benchmark prefilter with the multichannel pool**

Build the four channels from the already measured residual/direct/overlap records, call the Task 5 union, and pass its 24 representatives into existing profile construction and `evaluate_joint_gain`. Do not modify profile scoring or reportability rules.

- [ ] **Step 4: Extend CSV serialization safely**

Encode channel dictionaries as stable JSON columns and add flat union/collapse/Recall@24 columns. Preserve all existing columns for comparison scripts.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m unittest tests.benchmark.test_gain_evaluation tests.benchmark.test_joint_gain -v`

Expected: PASS.

- [ ] **Step 6: Run existing Gain regressions**

Run: `python -m unittest tests.test_gain_policy tests.test_gain_ranking tests.test_gain_shortlist tests.test_gain_unknown_peaks tests.test_phase_pattern_equivalence tests.test_phase_signal_to_noise -v`

Expected: PASS with unchanged final Gain behavior.

- [ ] **Step 7: Commit Task 6**

```powershell
git add benchmarks/match/evaluate_gain.py benchmarks/match/joint_gain.py tests/benchmark/test_gain_evaluation.py tests/benchmark/test_joint_gain.py
git commit -m "bench: evaluate multichannel Gain retrieval"
```

### Task 7: Add channel-attribution reporting and validation selection

**Files:**
- Create: `benchmarks/match/gain_retrieval_attribution.py`
- Create: `tests/benchmark/test_gain_retrieval_attribution.py`
- Modify: `benchmarks/match/report.py`
- Modify: `tests/benchmark/test_report.py`
- Modify: `benchmarks/match/README.md`

**Interfaces:**
- Produces: `RetrievalAttributionRow` with individual recall/rank, unique rescue, union/collapse/Recall@24, channel time, conditional Gain ranks, and observability fields.
- Produces: `select_retrieval_config(validation_rows) -> GainRetrievalConfig` using Recall@24, conditional Top-5 guard, unique rescue, then latency.
- Produces: CSV/Markdown tables `channel → individual recall → unique rescues → union Recall@24 → latency`.

- [ ] **Step 1: Write failing attribution tests**

Assert unique rescue counts only targets absent from every other channel, union recall is computed before and after collapse/compression, and cases below observability threshold are reported in their own stratum.

- [ ] **Step 2: Write failing selection tests**

Provide validation rows where one channel has high duplicate recall but zero unique rescue and assert the selected config removes it. Assert a faster config cannot win if Recall@24 is below 80%, and an absolute conditional Top-5 drop greater than 5 percentage points rejects an otherwise higher-recall config.

- [ ] **Step 3: Run attribution/report tests and verify RED**

Run: `python -m unittest tests.benchmark.test_gain_retrieval_attribution tests.benchmark.test_report -v`

Expected: FAIL because the attribution module and report fields are missing.

- [ ] **Step 4: Implement attribution and deterministic config selection**

Evaluate channel prefixes/quotas and soft-penalty weights only on development train/validation scenarios. Select in order: passes conditional Top-5 guard, highest Recall@24, most unique rescues, lowest median latency, stable lexical config key.

- [ ] **Step 5: Implement Markdown/CSV reporting**

Report channel, phase-count, residual-line-count, strongest-line-SNR, FWHM/noise, and effective-contribution strata with retrieval/profile/Gain timing separated.

- [ ] **Step 6: Run attribution/report tests and verify GREEN**

Run: `python -m unittest tests.benchmark.test_gain_retrieval_attribution tests.benchmark.test_report -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```powershell
git add benchmarks/match/gain_retrieval_attribution.py benchmarks/match/report.py benchmarks/match/README.md tests/benchmark/test_gain_retrieval_attribution.py tests/benchmark/test_report.py
git commit -m "bench: report Gain retrieval channel attribution"
```

### Task 8: Run the locked benchmark gate and decide integration

**Files:**
- Modify: `benchmarks/match/README.md`
- Create on passing gate: `benchmarks/match/reference_results/gain_retrieval_summary.md`
- Create on passing gate: `benchmarks/match/reference_results/gain_retrieval_selected_config.json`
- Create on passing gate: `benchmarks/match/reference_results/gain_retrieval_channel_attribution.csv`
- Create on passing gate: `benchmarks/match/reference_results/gain_retrieval_final_results.csv`

**Interfaces:**
- Consumes: locked `GainRetrievalConfig` from Task 7.
- Produces: a PASS/FAIL decision against Recall@24, latency, conditional Top-5, unique rescue, determinism, and untouched-set requirements.

- [ ] **Step 1: Run the complete focused suite**

Run: `python -m unittest tests.test_gain_retrieval_channels tests.test_residual_geometry tests.test_gain_retrieval_union tests.benchmark.test_gain_retrieval tests.benchmark.test_gain_evaluation tests.benchmark.test_joint_gain tests.benchmark.test_gain_retrieval_attribution tests.benchmark.test_report tests.test_gain_policy tests.test_gain_ranking tests.test_gain_shortlist tests.test_gain_unknown_peaks tests.test_phase_pattern_equivalence tests.test_phase_signal_to_noise -v`

Expected: PASS with zero failures.

- [ ] **Step 2: Run validation selection**

Run the attribution benchmark on the deterministic development train/validation manifest. Lock channel quotas, geometry bins, rank-fusion constants, and missing-line weight before any untouched-set run.

- [ ] **Step 3: Remove channels without unique rescue value**

Re-run validation after removal and keep the smaller channel set only when Recall@24 and the conditional Top-5 guard are preserved.

- [ ] **Step 4: Generate and run the untouched final set once**

Use scenario seed `15036` and only test-split phase families absent from every development/smoke manifest row. Save the exact family list, manifest checksum, and selected-config checksum with the final results.

- [ ] **Step 5: Check the acceptance gates**

Require Recall@24 ≥ 80%, median end-to-end latency ≤ 2.5 seconds, an absolute conditional Top-5 drop no larger than 5 percentage points from the frozen residual-window baseline, deterministic repeat ranks, and at least one validation unique rescue for every retained channel. Report untouched-set unique rescues without retuning channel membership.

- [ ] **Step 6: Record the decision**

On PASS, commit the compact reference artifacts and state that application integration of this single retrieval path is justified. On FAIL, commit only the README diagnosis, retain raw output under ignored `build/`, and do not modify the application.

- [ ] **Step 7: Commit Task 8**

```powershell
git add benchmarks/match/README.md benchmarks/match/reference_results/gain_retrieval_summary.md benchmarks/match/reference_results/gain_retrieval_selected_config.json benchmarks/match/reference_results/gain_retrieval_channel_attribution.csv benchmarks/match/reference_results/gain_retrieval_final_results.csv
git commit -m "bench: validate multichannel Gain retrieval"
```

### Task 9: Integrate the single retrieval path after a passing gate

**Files:**
- Modify: `xrd_finder/services/gain_shortlist.py`
- Modify: `xrd_finder/ui/gain_scoring.py`
- Modify: `xrd_finder/ui/candidate_search_actions.py`
- Test: `tests/test_gain_shortlist.py`
- Test: `tests/test_candidate_gain_refresh.py`

**Interfaces:**
- Consumes: passing locked `GainRetrievalConfig` and `build_gain_retrieval_pool`.
- Produces: one application Gain retrieval path with no user-visible mode switch.

- [ ] **Step 1: Begin only if Task 8 passes**

Verify the committed reference summary records PASS for every acceptance gate. If any gate failed, stop this task without modifying application files.

- [ ] **Step 2: Write failing application integration tests**

Assert candidate refresh calls one multichannel retrieval service, produces no more than 24 profile calculations, keeps dashes when residual evidence is absent, excludes accepted equivalent cards, and does not restart retrieval when unrelated card enrichment finishes.

- [ ] **Step 3: Run integration tests and verify RED**

Run: `python -m unittest tests.test_gain_shortlist tests.test_candidate_gain_refresh -v`

Expected: FAIL because production still uses the previous shortlist path.

- [ ] **Step 4: Wire the locked retrieval config into production**

Replace the production prefilter with the single selected multichannel pool. Keep UI labels, final Gain scoring, and the 24-profile limit unchanged; do not expose old/new or fast/full controls.

- [ ] **Step 5: Run integration and regression tests**

Run: `python -m unittest tests.test_gain_shortlist tests.test_candidate_gain_refresh tests.test_candidate_ui_responsiveness tests.test_auto_search_retry -v`

Expected: PASS.

- [ ] **Step 6: Commit Task 9**

```powershell
git add xrd_finder/services/gain_shortlist.py xrd_finder/ui/gain_scoring.py xrd_finder/ui/candidate_search_actions.py tests/test_gain_shortlist.py tests/test_candidate_gain_refresh.py
git commit -m "feat: use multichannel Gain retrieval"
```
