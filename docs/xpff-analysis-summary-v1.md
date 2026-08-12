# XPFF `analysis_summary` contract, schema version 1

XRD Phase Finder is the sole producer of the scientific result. SCI Manager reads the result from the portable `.xpff` container and does not repeat Match, Gain, profile fitting or phase quantification.

## Container responsibilities

An `.xpff` file remains a ZIP container with `project.json` as its manifest. It carries the source XRD patterns, processed state, series, referenced CIF files, Finder state, per-pattern PNG previews and one optional `analysis_summary` object. Existing XPFF files without this object remain valid.

The container does not store its own `file_sha256`: SCI Manager calculates SHA-256 over the finished `.xpff` file. This avoids a self-referential file hash.

## Summary shape

```json
{
  "schema_version": 1,
  "analysis_id": "ANALYSIS-uuid",
  "revision_id": "REVISION-uuid",
  "generated_at": "2026-08-12T10:30:00Z",
  "producer": {
    "application": "XRD Phase Finder",
    "version": "1.4.0"
  },
  "phase_catalog": [
    {
      "phase_id": "PHASE-uuid",
      "name": "BaSiO3",
      "formula": "BaSiO3",
      "source": "COD",
      "source_id": "1004027"
    }
  ],
  "patterns": [
    {
      "pattern_id": "PATTERN-uuid",
      "title": "003-00125",
      "sample_ref": {
        "project_uid": "PRJ-uuid",
        "sample_uid": "SMP-uuid",
        "sample_code": "003-00125"
      },
      "phases": [
        {
          "phase_id": "PHASE-uuid",
          "fraction_percent": 61.0
        }
      ],
      "quantification": {
        "method": "profile_scale_cell_mass",
        "is_estimate": true
      },
      "fit": {
        "score_percent": 94.0,
        "explained_peaks": 52,
        "total_peaks": 58,
        "unknown_peak_count": 2
      },
      "unknown_peaks": [
        {
          "two_theta": 31.7,
          "intensity": 20.0,
          "significance": null
        }
      ],
      "preview_path": "previews/PATTERN-uuid.png"
    }
  ],
  "result_sha256": "64 lowercase hexadecimal characters"
}
```

`phase_catalog` contains each used phase once. Pattern results reference it by `phase_id`. One phase may be referenced by any number of patterns. A missing quantitative value is `null`, never zero. An unlinked pattern has `sample_ref: null`; linking or relinking a physical sample is metadata and does not create a scientific revision.

## `result_sha256`

Both applications calculate the same hash using this procedure:

1. Recursively omit `analysis_id`, `revision_id`, `generated_at`, `producer`, `result_sha256`, `preview_path` and `sample_ref`.
2. Keep only phase-catalog records referenced by pattern results.
3. Sort `phase_catalog` by `phase_id`, `patterns` by `pattern_id`, every pattern's `phases` by `phase_id`, and `unknown_peaks` by `two_theta` then `intensity`.
4. Encode the resulting JSON as UTF-8 with RFC 8785 JSON Canonicalization Scheme (JCS). NaN and infinity are invalid.
5. Calculate SHA-256 and serialize it as lowercase hexadecimal.

`analysis_id` remains stable for the analysis. `revision_id` and `generated_at` remain unchanged when the scientific hash is unchanged and are replaced when it changes.

SCI Manager applies the following rule:

```text
same file_sha256
-> file unchanged

changed file_sha256, same result_sha256
-> technical update

changed result_sha256
-> new scientific revision
```

Preview PNG files are presentation assets. They and their paths do not affect the scientific hash.
