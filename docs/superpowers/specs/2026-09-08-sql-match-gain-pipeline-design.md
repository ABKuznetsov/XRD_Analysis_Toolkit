# SQL-backed Match/Gain Pipeline

## Scope

XRD Phase Finder already stores downloaded CIF files in its managed cache and
stores phase metadata, cached lines and normalized peak rows in
`LocalPhaseCache`. This change does not replace that storage model or alter the
scientific definitions of Match and Gain.

The change removes the repeated CIF-to-sticks calculation from ordinary
candidate ranking. Match and Gain consume the line data already stored in
SQLite. CrIStMa remains responsible for calculating and indexing a newly
downloaded structure, rebuilding an obsolete derived index, and producing an
exact profile for a shortlisted or selected candidate.

## User Flow

1. The user selects elements and starts a search.
2. Matching entries already indexed in SQLite are returned immediately.
3. Match is calculated from their indexed line sets. Gain is also calculated
   when one or more phases have already been selected.
4. Enabled remote sources are queried in the background.
5. New structures are downloaded into the existing managed CIF cache,
   calculated through CrIStMa and committed to `LocalPhaseCache`.
6. Newly indexed candidates are scored and appended to the active result set in
   batches.
7. The table is re-ranked while preserving selection and scroll context by the
   stable `SOURCE:ENTRY` key.

Remote metadata without an indexed line set is not inserted as a scored result.
It remains represented by background progress until indexing succeeds.

## Calculation Boundary

SQLite is the source of the candidate line data, but Match and Gain remain
dynamic application calculations:

```text
SQLite phase_peaks + current observed evidence -> Match
SQLite phase_peaks + current residual evidence -> Gain
```

The scores are not persisted as properties of a phase because they depend on
the active experimental pattern, preprocessing, instrument context and selected
phases.

Before any phase is selected, candidates are ordered by Match. After a phase is
selected, Gain is recalculated against the residual evidence and becomes the
primary ordering criterion. Match remains visible as the candidate's score
against the complete observed pattern.

## Indexed Line Contract

The existing `phase_peaks` rows are exposed to the finder layer as an immutable
line set. A line contains at least:

- `d` and cached `two_theta`;
- normalized and raw intensity;
- `h`, `k`, `l`;
- multiplicity;
- the derived-cache version and calculation provenance.

The finder candidate input accepts either an indexed line set or a CIF path.
An indexed line set is preferred. The CIF path is a compatibility fallback for
user entries and old caches that have not yet been indexed.

The current Cu K-alpha line index remains usable during migration. The line-set
contract must retain `d` so future radiation-specific indexes can be generated
without changing the Match/Gain API.

## Background Pipeline

Each search owns a monotonically increasing session token. Background work may
finish after a new search starts, but only results matching the active token may
update the table. Successfully indexed structures are retained in the cache
even when their original search is no longer active.

SQLite writes use one serialized writer. Reads continue through independent
connections. Candidate UI updates are coalesced into small batches rather than
emitted for every downloaded structure.

The status bar reports aggregate work, for example:

```text
Found locally: 128 | Downloading: 24 | Indexing: 8 | Ranking: 16
```

On completion:

```text
Ready: 176 candidates | Local: 128 | Downloaded: 48
```

Network and individual-source failures do not discard local results and do not
open blocking dialogs during a normal search. The status reports that online
sources are unavailable or partially complete.

## Component Boundaries

The change is split into focused components rather than added to
`analysis_windows.py`:

- `LocalPhaseCache` reads and writes indexed line sets.
- A finder-side line-set adapter converts SQL rows into the existing peak model.
- The existing Match/Gain calculators consume those peaks without knowing
  whether they came from SQL or a compatibility CIF fallback.
- A search-session coordinator merges indexed batches and rejects stale UI
  updates.
- A status presenter formats aggregate background progress for the existing
  status bar.

CrIStMa is not called from the broad Match/Gain loop when a current SQL line set
exists.

## Cache Compatibility

Entries with the current `DERIVED_CACHE_VERSION` and non-empty indexed peaks are
used directly. Missing or obsolete derived data is queued for reindexing. The UI
continues to show other ready candidates while this happens.

Existing project files and existing cache directories remain compatible. No
bulk database migration is required for the first implementation slice.

## Verification

Focused tests cover:

- indexed candidates can be ranked without opening or parsing their CIF;
- indexed and compatibility-CIF inputs produce equivalent candidate identity
  and stable peak ordering;
- Gain is recalculated after selected phases change;
- completed indexing adds candidates only to the matching active search;
- batched updates preserve the selected `SOURCE:ENTRY` row;
- offline and failed remote sources leave local results usable;
- CrIStMa is invoked for a missing/obsolete index but not for a current one.

Representative real-pattern checks compare ranking before and after the data
path change. They are regression checks for unintended data loss, not a reason
to tune the Match/Gain formula in this task.
