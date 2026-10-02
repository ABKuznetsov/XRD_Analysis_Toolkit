# Joint Phase Beam Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a benchmark-only joint phase-combination search that ranks additional phases by conditional improvement of a jointly fitted full-profile model and compares it with the existing greedy Gain.

**Architecture:** A pure `xrd_finder.finder.joint_phase_search` module owns validation, weighted NNLS, combination scoring, beam expansion and conditional candidate Gain. The existing synthetic Gain benchmark prepares aligned coarse profiles and invokes either the unchanged greedy engine or the new joint engine through an adapter. UI integration remains outside this plan until the benchmark satisfies the design criteria.

**Tech Stack:** Python 3.11–3.12, NumPy, SciPy `nnls`, existing phase-pattern equivalence and Phase-SNR helpers, `unittest`, CSV/Markdown benchmark reports.

**Spec:** `docs/superpowers/specs/2026-10-02-joint-phase-beam-search-design.md`

## Global Constraints

- The first implementation is benchmark-only and must not alter Qt/UI behavior.
- Keep one zero shift for the complete XRD pattern; do not optimize phase-specific constant 2θ shifts.
- Use fixed coarse candidate profiles in the beam; do not refine cell parameters or FWHM inside a node.
- Default limits are `beam_width=5`, `max_added_phases=3`, `minimum_phase_snr=3.0`, and `minimum_relative_improvement=0.003`.
- Default score parameters are derivative weight `0.10`, complexity penalty `0.003`, and excess multiplier `3.0`.
- Collapse duplicate cards by diffraction-pattern equivalence, never by phase name, formula, or entry number.
- Required/accepted phases stay in every state and their NNLS scales are jointly refitted.
- Direct, overlap, hidden and rare-line evidence may propose candidates but may not gate joint profile evaluation.
- Do not show/report Gain below 3% or Phase-SNR below 3.
- Keep current `greedy` Gain as the unchanged baseline.
- Do not add a visible mode, badge, or extra column to the application.

## Review Focus

- **Overlapping intensity:** a required phase sharing a strong reflection with the true next phase must release intensity when NNLS adds that phase; covered by Task 2 shared-reflection test.
- **Equivalent cards:** two entry IDs/names with the same powder fingerprint must never appear together or reappear after one is accepted; covered by Task 3 family tests and Task 4 adapter test.
- **Order stability:** candidate iteration order and accepted-phase order must not alter ranked family results; covered by Task 3 deterministic permutation test and Task 6 scenario variants.
- **Noise-only residual:** a single accidental line must not produce reportable Gain; covered by Task 3 Phase-SNR test and Task 6 noise stress case.
- **Degenerate numerical input:** empty arrays, NaN, mismatched shapes, zero target and singular profile columns must return a deterministic result or a specific `ValueError`; covered by Task 1 validation tests.

---

### Task 1: Define the pure joint-search data model and input validation

**Files:**
- Create: `xrd_finder/finder/joint_phase_search.py`
- Create: `tests/test_joint_phase_search.py`
- Modify: `xrd_finder/finder/__init__.py`

**Interfaces:**
- Produces: `JointPhaseCandidate`, `JointPhaseSearchConfig`, `JointPhaseCombination`, `JointPhaseCandidateGain`, `JointPhaseSearchResult`, and `search_phase_combinations(...)`.
- Consumes: NumPy arrays only at this stage; no Qt, benchmark, database, CIF, or UI objects.

- [ ] **Step 1: Write failing construction and validation tests**

Add tests asserting:

```python
def test_rejects_mismatched_target_weights_and_profiles(): ...
def test_rejects_nonfinite_candidate_profile(): ...
def test_zero_target_returns_empty_deterministic_result(): ...
def test_empty_optional_pool_returns_required_baseline_only(): ...
def test_candidate_and_result_objects_are_immutable(): ...
```

Use the public API names from the Interfaces block. Assert exact `ValueError` messages for mismatched shapes and nonfinite values so benchmark failures remain diagnosable.

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m unittest tests.test_joint_phase_search -v`

Expected: import failure for `xrd_finder.finder.joint_phase_search`.

- [ ] **Step 3: Implement immutable public models and validation**

Implement in `joint_phase_search.py`:

```python
@dataclass(frozen=True, slots=True)
class JointPhaseCandidate:
    key: str
    family_key: str
    profile: np.ndarray
    peak_positions: np.ndarray
    peak_amplitudes: np.ndarray
    payload: object | None = None

@dataclass(frozen=True, slots=True)
class JointPhaseSearchConfig:
    beam_width: int = 5
    max_added_phases: int = 3
    derivative_weight: float = 0.10
    complexity_penalty: float = 0.003
    excess_penalty: float = 3.0
    minimum_phase_snr: float = 3.0
    minimum_relative_improvement: float = 0.003
    minimum_reported_gain: float = 3.0
```

Define the result dataclasses with family-key tuples, card-key tuples, scales, score, Phase-SNR diagnostics, candidate gains, evaluated-combination count, and elapsed search seconds. Add a private normalization/validation function. Export the public names from `xrd_finder/finder/__init__.py`.

- [ ] **Step 4: Run validation tests and verify GREEN**

Run: `python -m unittest tests.test_joint_phase_search -v`

Expected: all Task 1 tests pass; search-specific tests may still be absent.

- [ ] **Step 5: Commit Task 1**

```powershell
git add xrd_finder/finder/joint_phase_search.py xrd_finder/finder/__init__.py tests/test_joint_phase_search.py
git commit -m "feat: define joint phase search model"
```

### Task 2: Implement weighted NNLS and the combination score

**Files:**
- Modify: `xrd_finder/finder/joint_phase_search.py`
- Modify: `tests/test_joint_phase_search.py`

**Interfaces:**
- Consumes: validated `target`, `weights`, required and optional `JointPhaseCandidate` profiles.
- Produces: private `_fit_combination(...) -> JointPhaseCombination` used by Task 3.

- [ ] **Step 1: Write failing joint-fit tests**

Add:

```python
def test_joint_nnls_releases_shared_intensity_to_supported_second_phase(): ...
def test_excess_profile_intensity_is_penalized_more_than_underfit(): ...
def test_derivative_term_penalizes_a_missing_sharp_line(): ...
def test_complexity_penalty_prefers_the_smaller_equal_fit(): ...
def test_singular_duplicate_columns_return_finite_deterministic_scales(): ...
```

The shared-reflection fixture must contain one required profile, one candidate sharing its strongest line, and at least one independent candidate line. Assert both recovered scales within a numerical tolerance and a lower child score than the required-only baseline.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_joint_phase_search.JointPhaseFitTests -v`

Expected: failures because combination fitting/scoring is not implemented.

- [ ] **Step 3: Implement weighted NNLS and scoring**

Use `scipy.optimize.nnls` on `sqrt(weights) * H` and `sqrt(weights) * target`, with a clipped least-squares fallback matching existing project behavior. Compute:

```text
under = max(target - calculated, 0)
over  = max(calculated - target, 0)
E = sum(w * (under**2 + excess_penalty * over**2)) / max(sum(w * target**2), eps)
D = sum(abs(diff(target) - diff(calculated))) / max(sum(abs(diff(target))), eps)
score = E + derivative_weight * D + complexity_penalty * optional_phase_count
```

Keep required phases out of `optional_phase_count`. Preserve signed residual in diagnostics; do not clip it before scoring.

- [ ] **Step 4: Run focused and existing scaling tests**

Run:

```powershell
python -m unittest tests.test_joint_phase_search.JointPhaseFitTests -v
python -m unittest tests.benchmark.test_gain_evaluation.GainEvaluationTests.test_joint_scales_recover_two_selected_profiles -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add xrd_finder/finder/joint_phase_search.py tests/test_joint_phase_search.py
git commit -m "feat: score jointly fitted phase combinations"
```

### Task 3: Implement deterministic beam expansion and conditional Gain

**Files:**
- Modify: `xrd_finder/finder/joint_phase_search.py`
- Modify: `tests/test_joint_phase_search.py`

**Interfaces:**
- Consumes: `_fit_combination`, existing `phase_signal_to_noise`, required keys, family-keyed candidate pool, and `JointPhaseSearchConfig`.
- Produces: complete `search_phase_combinations(...) -> JointPhaseSearchResult`.

- [ ] **Step 1: Write failing beam-search behavior tests**

Add:

```python
def test_candidate_iteration_order_does_not_change_ranked_families(): ...
def test_required_phase_order_does_not_change_best_combination(): ...
def test_same_family_cards_never_share_a_combination(): ...
def test_accepted_family_is_not_returned_as_gain_candidate(): ...
def test_overlap_candidate_can_win_without_independent_direct_gate(): ...
def test_noise_only_candidate_fails_phase_snr_and_reporting_floor(): ...
def test_candidate_gain_uses_parent_to_child_edge_not_companion_credit(): ...
def test_beam_stops_when_no_child_reaches_minimum_improvement(): ...
```

Use fixed synthetic profiles and deterministic Gaussian noise seeds. The companion-credit test must add a useful candidate after another candidate and assert Gain equals the best marginal edge improvement rather than baseline-to-full-combination improvement.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_joint_phase_search.JointPhaseBeamSearchTests -v`

Expected: failures from the incomplete search implementation.

- [ ] **Step 3: Implement beam search**

At each depth, expand every retained family set by every unused family representative, fit the child, compute the candidate Phase-SNR with `phase_signal_to_noise`, discard sub-threshold children, deduplicate by sorted family tuple, and retain `beam_width` states ordered by `(score, family_keys, card_keys)`.

Track each evaluated parent→child edge. Calculate candidate Gain as:

```text
100 * (parent.score - child.score) / max(baseline.score, eps)
```

Keep the maximum positive edge for each family, its supporting combination, Phase-SNR, and rejection reason. Apply the existing 3% reporting floor only to the reportable candidate list; retain raw diagnostics.

- [ ] **Step 4: Run all core joint-search tests**

Run: `python -m unittest tests.test_joint_phase_search -v`

Expected: PASS with deterministic repeated results.

- [ ] **Step 5: Commit Task 3**

```powershell
git add xrd_finder/finder/joint_phase_search.py tests/test_joint_phase_search.py
git commit -m "feat: search competing phase combinations"
```

### Task 4: Build the benchmark candidate-pool and profile adapter

**Files:**
- Create: `benchmarks/match/joint_gain.py`
- Create: `tests/benchmark/test_joint_gain.py`
- Modify: `benchmarks/match/gain_retrieval.py`
- Modify: `tests/benchmark/test_gain_retrieval.py`

**Interfaces:**
- Consumes: original Match scores, residual scores, accepted phase IDs, `xrd_finder.services.phase_pattern_equivalence.phase_patterns_equivalent`, and candidate profiles already aligned and constructed by `evaluate_gain.py`.
- Produces: `build_joint_candidate_pool(...)` and `evaluate_joint_gain(...)` returning core candidates plus search timing and retrieval diagnostics. It must not import private helpers from `evaluate_gain.py`.

- [ ] **Step 1: Write failing global-pool tests**

Add tests asserting that the pool:

- contains leaders from original Match and residual retrieval;
- includes rare-line rescue candidates when supplied;
- always includes required phases outside the 60-optional-family cap;
- keeps one representative per family using the best original Match score and deterministic key tie-break;
- excludes the already accepted family even when its card has a different name and entry ID;
- reports whether the true target was lost before or during family collapse.

- [ ] **Step 2: Run retrieval tests and verify RED**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_retrieval tests.benchmark.test_joint_gain -v
```

Expected: import/function failures for the new adapter.

- [ ] **Step 3: Implement pool fusion and family collapse**

Add a `joint_gain_candidate_pool` helper to `gain_retrieval.py` with defaults: 40 original families, 40 residual families, 12 rare-line families, 60 optional families after deduplication. Build deterministic family keys by comparing powder fingerprints with `phase_patterns_equivalent`; never infer equivalence from entry ID, phase name or formula. Keep current shortlist functions unchanged.

Implement `benchmarks.match.joint_gain` as a thin adapter that converts the prepared profile mapping into core candidates, calls `search_phase_combinations`, and returns family/card rank plus diagnostics. Keep line alignment and profile construction in `evaluate_gain.py`, which already owns the current common-zero and candidate-cell-estimate logic; this avoids a circular import and guarantees both engines use identical prepared inputs.

- [ ] **Step 4: Run adapter and existing retrieval tests**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_retrieval tests.benchmark.test_joint_gain -v
```

Expected: PASS; existing shortlist behavior remains unchanged.

- [ ] **Step 5: Commit Task 4**

```powershell
git add benchmarks/match/joint_gain.py benchmarks/match/gain_retrieval.py tests/benchmark/test_joint_gain.py tests/benchmark/test_gain_retrieval.py
git commit -m "feat: prepare joint Gain benchmark pool"
```

### Task 5: Integrate the joint engine into the synthetic Gain benchmark

**Files:**
- Modify: `benchmarks/match/evaluate_gain.py`
- Modify: `tests/benchmark/test_gain_evaluation.py`
- Modify: `tests/benchmark/test_match_gain_pipeline.py`

**Interfaces:**
- Consumes: `evaluate_joint_gain` from Task 4, the unchanged greedy code path, and the existing alignment/profile builders already local to `evaluate_gain.py`.
- Produces: `gain_engine="greedy" | "joint-beam"` support in `evaluate_gain_scenario`, `run_gain_benchmark`, worker chunks and CLI.

- [ ] **Step 1: Write failing engine-selection and diagnostics tests**

Add tests asserting:

```python
def test_greedy_engine_preserves_existing_result_fields_and_rank(): ...
def test_joint_engine_recovers_overlap_phase_after_joint_refit(): ...
def test_joint_engine_records_retrieval_profile_and_search_timings(): ...
def test_joint_engine_records_best_combination_and_evaluated_count(): ...
def test_unknown_gain_engine_raises_value_error(): ...
```

Extend `GainScenarioResult` assertions for `gain_engine`, `retrieval_seconds`, `profile_seconds`, `search_seconds`, `evaluated_combinations`, and `best_combination`.

- [ ] **Step 2: Run integration tests and verify RED**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_evaluation tests.benchmark.test_match_gain_pipeline -v
```

Expected: missing `gain_engine` argument/diagnostic fields.

- [ ] **Step 3: Add the benchmark engine branch**

Keep the current body as the `greedy` path. Reuse its generated pattern, common zero, accepted profiles, residual records and original Match scores for `joint-beam`; do not regenerate the synthetic pattern. After pool fusion, align each retained candidate with the existing common-zero/cell-estimate path and build its fixed profile once in `evaluate_gain.py`, record that as `profile_seconds`, then pass the prepared profile mapping to `evaluate_joint_gain`. Pass Task 3 configuration from `run_gain_benchmark` through process-worker argument tuples.

Add CLI options:

```text
--gain-engine {greedy,joint-beam}
--beam-width 5
--max-added-phases 3
--derivative-weight 0.10
--complexity-penalty 0.003
--excess-penalty 3.0
--minimum-phase-snr 3.0
--minimum-relative-improvement 0.003
```

Leave existing CLI defaults equivalent to the current `greedy` run unless `--gain-engine joint-beam` is specified.

- [ ] **Step 4: Run Gain integration regression tests**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_evaluation tests.benchmark.test_match_gain_pipeline tests.test_gain_ranking tests.test_gain_policy -v
```

Expected: PASS for both engines and unchanged greedy expectations.

- [ ] **Step 5: Commit Task 5**

```powershell
git add benchmarks/match/evaluate_gain.py tests/benchmark/test_gain_evaluation.py tests/benchmark/test_match_gain_pipeline.py
git commit -m "feat: benchmark joint and greedy Gain engines"
```

### Task 6: Add order/card-variant stress cases and score sensitivity

**Files:**
- Create: `benchmarks/match/joint_gain_sensitivity.py`
- Create: `tests/benchmark/test_joint_gain_sensitivity.py`
- Modify: `benchmarks/match/gain_scenarios.py`
- Modify: `tests/benchmark/test_gain_scenarios.py`

**Interfaces:**
- Consumes: `evaluate_gain_scenario(..., gain_engine="joint-beam")`, targeted scenarios, accepted phase permutations, and equivalent-card variants.
- Produces: validation-selected `JointPhaseSearchConfig`, held-out sensitivity rows, order/card stability metrics, and deterministic stress-case IDs.

- [ ] **Step 1: Write failing stress-set tests**

Add deterministic scenarios for:

- one accepted phase sharing a dominant line with quartz-like target;
- two accepted phases supplied in both orders;
- an accepted Na/Ca-like equivalent-card pair with different calculated intensities;
- one-line noise-only residual;
- a three/four-phase overlap mixture where the next phase has weak independent lines.

Assert that generated variants share the same true target family and differ only in the intended accepted-card/order dimension.

- [ ] **Step 2: Run scenario tests and verify RED**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_scenarios tests.benchmark.test_joint_gain_sensitivity -v
```

Expected: missing stress scenarios and sensitivity runner.

- [ ] **Step 3: Implement the validation-only parameter sweep**

Evaluate the design grid:

- derivative weight: `0, 0.05, 0.10, 0.20`;
- complexity penalty: `0, 0.001, 0.003, 0.01`;
- excess multiplier: `1, 2, 3, 5`.

Select on validation using, in order: full phase-set recovery, target Top-5, fewer false-positive families, lower median search time. Lock the selected configuration before evaluating test. Never select parameters on held-out test.

- [ ] **Step 4: Add stability calculations**

Report:

- Top-5 retention under accepted-phase permutation;
- absolute rank delta under equivalent-card replacement;
- Jaccard similarity of the first five families;
- count of formerly visible candidates suppressed by Phase-SNR/reporting floor.

- [ ] **Step 5: Run sensitivity tests**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_scenarios tests.benchmark.test_joint_gain_sensitivity -v
```

Expected: PASS with deterministic selected configuration on the small fixture.

- [ ] **Step 6: Commit Task 6**

```powershell
git add benchmarks/match/joint_gain_sensitivity.py benchmarks/match/gain_scenarios.py tests/benchmark/test_joint_gain_sensitivity.py tests/benchmark/test_gain_scenarios.py
git commit -m "test: stress joint Gain order and card stability"
```

### Task 7: Extend CSV/Markdown reporting and document reproducible commands

**Files:**
- Modify: `benchmarks/match/evaluate_gain.py`
- Modify: `benchmarks/match/README.md`
- Modify: `tests/benchmark/test_gain_evaluation.py`
- Modify: `tests/benchmark/test_report.py`

**Interfaces:**
- Consumes: timing and combination diagnostics added in Task 5.
- Produces: inspectable `gain_results.csv`, `gain_summary.md`, selected sensitivity JSON/CSV, and documented commands.

- [ ] **Step 1: Write failing report tests**

Assert the summary includes separate columns/lines for retrieval, profile-build and beam-search median/p95 times, evaluated combinations, pool recall, Top-1/5/10, full-set recovery, false-positive families, order stability and card-variant stability. Assert CSV round-trips quoted combination keys without losing separators.

- [ ] **Step 2: Run report tests and verify RED**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_evaluation tests.benchmark.test_report -v
```

Expected: missing joint diagnostic content.

- [ ] **Step 3: Implement reporting and README commands**

Document smoke and full runs, including:

```powershell
python -m benchmarks.match.evaluate_gain --dataset benchmarks/match/data/match_benchmark.sqlite --output build/gain-joint-smoke --scenario-set targeted --splits validation --shortlist 60 --gain-engine joint-beam --workers 1
python -m benchmarks.match.joint_gain_sensitivity --dataset benchmarks/match/data/match_benchmark.sqlite --output build/gain-joint-sensitivity --workers 4
```

Describe load/profile/search timing separately and state that batch runtime is not the interactive latency for one pattern.

- [ ] **Step 4: Run report tests**

Run:

```powershell
python -m unittest tests.benchmark.test_gain_evaluation tests.benchmark.test_report -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```powershell
git add benchmarks/match/evaluate_gain.py benchmarks/match/README.md tests/benchmark/test_gain_evaluation.py tests/benchmark/test_report.py
git commit -m "docs: report joint Gain benchmark diagnostics"
```

### Task 8: Run the benchmark gate and record the decision

**Files:**
- Modify: `benchmarks/match/README.md`
- Create when successful: `benchmarks/match/reference_results/joint_gain_summary.md`
- Create when successful: `benchmarks/match/reference_results/joint_gain_selected_config.json`
- Create when successful: `benchmarks/match/reference_results/joint_gain_comparison.csv`

**Interfaces:**
- Consumes: completed test suite, greedy and joint benchmark engines.
- Produces: evidence for either UI integration or rejection/revision of the prototype.

- [ ] **Step 1: Run the focused automated suite**

Run:

```powershell
python -m unittest tests.test_joint_phase_search tests.benchmark.test_joint_gain tests.benchmark.test_joint_gain_sensitivity tests.benchmark.test_gain_evaluation tests.benchmark.test_gain_retrieval tests.benchmark.test_gain_scenarios tests.benchmark.test_match_gain_pipeline tests.benchmark.test_report -v
```

Expected: all tests pass with no warnings or tracebacks.

- [ ] **Step 2: Run the existing Gain regressions**

Run:

```powershell
python -m unittest tests.test_gain_policy tests.test_gain_ranking tests.test_gain_shortlist tests.test_gain_unknown_peaks tests.test_phase_pattern_equivalence tests.test_phase_signal_to_noise -v
```

Expected: PASS; current greedy behavior remains available.

- [ ] **Step 3: Run a single-process validation smoke benchmark**

Run the smoke command from Task 7. Inspect CSV rows for retrieval loss, family collapse, Phase-SNR rejection, combination count, timings and target rank before starting the full sweep.

- [ ] **Step 4: Run validation sensitivity and held-out comparison**

Run the sensitivity command from Task 7. The runner must select parameters on validation, then evaluate greedy and the locked joint configuration on test.

- [ ] **Step 5: Check the six design gates**

Record PASS/FAIL for:

1. quartz-like target remains Top-5 across Na/Ca-like accepted variants and accepted-phase order;
2. overlap Top-10 is no worse than greedy and correct-next-phase recovery improves;
3. reportable false-positive family count grows by no more than 10%;
4. repeat runs are deterministic;
5. timings are split into retrieval/profile/search;
6. added single-pattern time is at most the softer bound of 50% current Gain time or 1.5 seconds.

- [ ] **Step 6: Write the benchmark decision**

If all gates pass, commit the compact reference summary/config/comparison and state that a separate UI-integration spec is now justified. If any gate fails, leave large raw outputs under ignored `build/`, document the failed gate and diagnostic cause in `benchmarks/match/README.md`, and do not change the application.

- [ ] **Step 7: Commit Task 8**

On a passing gate, commit the compact reference artifacts:

```powershell
git add benchmarks/match/README.md benchmarks/match/reference_results/joint_gain_summary.md benchmarks/match/reference_results/joint_gain_selected_config.json benchmarks/match/reference_results/joint_gain_comparison.csv
git commit -m "bench: compare joint and greedy Gain search"
```

On a failing gate, commit only the README diagnosis; keep raw benchmark output under ignored `build/`:

```powershell
git add benchmarks/match/README.md
git commit -m "bench: document joint Gain benchmark failure"
```

