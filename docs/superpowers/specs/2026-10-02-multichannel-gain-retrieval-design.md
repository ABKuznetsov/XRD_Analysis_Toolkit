# Multi-channel Gain retrieval design

## Purpose

Improve the probability that the correct next phase reaches the fixed
24-candidate profile shortlist without changing the validated final Gain
calculation or the user interface.

The current residual-window joint Gain ranks a correct powder-pattern family
well once it reaches profile scoring, but its measured Recall@24 is 62.5% on
the development smoke set. Retrieval is therefore the optimization target.
The profile Gain formula, reporting thresholds, phase-SNR policy, and joint
profile competition remain frozen during this work.

## Success criteria

The implementation is accepted only when all of the following hold:

- Recall@24 is at least 80% on the locked evaluation procedure.
- Median end-to-end Gain latency is at most 2.5 seconds on the current test
  machine; approximately 2 seconds remains the target.
- Conditional Top-5 among cases whose true family reaches the profile pool
  does not meaningfully degrade from the current residual-window Gain result.
- Every retained retrieval channel contributes unique rescued cases. A channel
  that adds no material unique recall is removed even if its individual recall
  is high.
- Parameters and channel quotas are selected without using the untouched final
  test set.

## Scope

This change covers candidate retrieval and benchmark reporting only. It does
not change:

- the application UI;
- the 24-profile shortlist size;
- final joint Gain scoring or its numerical thresholds;
- automatic phase acceptance, because the operator remains responsible for
  accepting a candidate;
- Match ranking of the original diffraction pattern.

## Data flow

1. Jointly fit the phases already accepted by the operator.
2. Build the signed residual and detect significant positive residual maxima.
3. Measure each residual maximum on the unsmoothed residual and retain its
   position, height, area, prominence, FWHM, fit quality, and local noise.
4. Pass the same residual evidence to four independent cheap retrieval
   channels.
5. Collect approximately 50–80 unique raw cards from the channel union.
6. Collapse cards with practically equivalent calculated diffraction
   fingerprints into pattern families.
7. Apply one cheap line-level reranker with a soft missing-strong-line penalty.
8. Keep exactly 24 family representatives for the unchanged profile Gain.

When no significant residual maxima survive the existing noise policy, the
retrieval result is empty and Gain remains unreported.

## Common retrieval interface

Each channel returns an ordered sequence of immutable records with:

- `phase_id` — database/card identifier;
- `channel` — stable channel name;
- `score` — channel-local finite score, used only inside that channel;
- `rank` — one-based channel rank;
- `evidence_count` — number of residual features supporting the result;
- `elapsed_seconds` — channel wall time recorded once and copied into the
  channel report, not used for ranking.

Channel scores are not treated as probabilities and are not directly added
together. The union stage first uses ranks and channel presence so that score
scales from different algorithms cannot dominate one another accidentally.

## Retrieval channels

### Strong residual peaks

This is the baseline channel. It evaluates how well the strongest significant
residual maxima are covered by strong candidate lines. Residual peaks are
weighted by area/prominence, local signal-to-noise ratio, and reliability of
their measured width. Broad or poorly fitted maxima remain usable but receive
less influence.

### Rare lines

This channel weights a matched residual line by its inverse frequency among
database phases. Frequency is precomputed for angular bins in the compact
index. It is a rescue channel for a small number of informative lines and does
not require a separate user-visible mode.

### Two/three-line geometry

This channel hashes the relative geometry of pairs and triplets of residual
lines. The representation removes a common zero shift and tolerates small
angle-dependent displacement. Candidate hashes are precomputed from their
strong calculated lines. One-line residuals do not enter this channel.

The existing four-line affine fingerprint implementation may be reused where
it provides the required invariance, but the benchmark must measure two- and
three-line retrieval separately because sparse residuals often contain fewer
than four trustworthy lines.

### Overlap deficit

This channel uses maxima or shoulders close to accepted-phase reflections when
the observed intensity exceeds the jointly fitted accepted-phase profile by a
noise-significant amount. It scores candidates whose calculated strong lines
explain these intensity deficits. Positional overlap alone is insufficient;
the residual intensity deficit must pass the existing local-noise criterion.

## Union and family collapse

Each channel contributes a bounded prefix to the raw union. The initial quota
is deliberately generous enough to produce 50–80 unique cards before family
collapse. Channel quotas are development parameters and are selected on the
validation set from unique rescue and latency, not from individual recall
alone.

Cards are collapsed by calculated diffraction fingerprint rather than phase
name, formula, database source, or entry number. Equivalence uses strong-line
position/intensity agreement with the existing common-shift-aware pattern
comparison. The best representative is chosen using retrieval evidence; all
other card identifiers remain available as alternative records of the same
pattern family.

Accepted pattern families are excluded before the 24-profile shortlist is
formed, preventing the same phase from returning under another database card.

## Cheap line-level reranking

The reranker operates only on the collapsed 50–80-family union. Its evidence
contains:

- weighted coverage of significant residual maxima;
- support from independent retrieval channels;
- agreement with rare and geometric residual evidence;
- overlap-deficit coverage;
- a soft missing-strong-line penalty.

The missing-line term is never a hard filter. Its penalty is reduced when an
expected line is below the estimated detection limit, lies in an accepted-phase
overlap region, or belongs to a weak candidate reflection. This preserves
recall for minor phases while demoting cards that predict several strong,
clearly observable absent lines.

The first implementation uses deterministic rank fusion plus a small set of
physically interpretable line-level terms. It does not fit a learned model.
Weights or quotas are selected only on train/validation data and then locked.

## Benchmark and attribution

Every scenario records the following for each channel:

- individual family recall;
- target rank in the channel;
- unique rescued cases relative to the other channels;
- candidate count;
- channel latency.

The union report records:

- recall before collapse;
- recall after diffraction-family collapse;
- recall after reranking at 24;
- conditional Top-1/Top-5/Top-10 after unchanged profile Gain;
- retrieval, profile construction, and Gain time separately;
- end-to-end median and p95 latency.

The current 24-case smoke set is a development diagnostic only. Parameter and
quota selection uses deterministic train and validation cases spanning phase
count, phase fraction/effective diffraction contribution, noise, FWHM,
overlap, and residual-line count. Once retrieval is frozen, final numbers are
computed once on a newly generated untouched set with new phase families and
random seeds.

Results are reported by phase count and by observability strata, including
strongest residual-line SNR and number of significant characteristic lines.
Cases below the defined observability threshold are reported separately rather
than silently counted as ordinary retrieval failures.

## Failure handling and determinism

- A channel failure produces an empty result for that channel and a diagnostic;
  the remaining channels still run.
- Non-finite scores are treated as zero and cannot enter the union by score.
- Ties are resolved by stable phase identifier after family-level evidence.
- Repeated runs over the same dataset and configuration must produce identical
  candidate families and ranks.
- No channel may trigger network access during ranking; all required indices
  are local and precomputed.

## Delivery sequence

1. Add common channel-result and attribution data structures.
2. Instrument the existing strong and rare channels without changing their
   rankings.
3. Add two/three-line geometry and overlap-deficit channels.
4. Add union, diffraction-family collapse, and cheap reranking.
5. Run validation attribution and remove channels without unique rescue value.
6. Lock retrieval parameters and run the untouched final evaluation.
7. Integrate the single selected retrieval path into the application only after
   the benchmark criteria pass.
