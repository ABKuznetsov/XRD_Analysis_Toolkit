# Match benchmark summary

Dataset SHA-256: `7d1c4017d58f8369ace1c763b030da2b4e599c817a7c2cf333d9a75b592238ad`

Selected weights (observed/reference/lines/seed): `0.100/0.710/0.165/0.025`

| Weights | Queries | MRR | Top-1 | Top-5 | Top-10 | Recall@10 |
|---|---:|---:|---:|---:|---:|---:|
| manuscript | 64 | 0.5884 | 0.5156 | 0.6562 | 0.7344 | 0.4258 |
| current | 64 | 0.5916 | 0.5156 | 0.6406 | 0.7812 | 0.4518 |
| equal | 64 | 0.5409 | 0.4531 | 0.6406 | 0.7344 | 0.4206 |
| selected | 64 | 0.5904 | 0.5000 | 0.6875 | 0.7969 | 0.4687 |

## Single-pattern runtime

Measured over 16 synthetic patterns; each pattern was searched against all 1058 candidates.

- Total sequential time: 66.200 s
- Mean per pattern: 4.137 s
- Median total: 4.146 s
- 95th percentile total: 5.257 s
- Median fingerprint retrieval: 0.021 s
- Median quick all-candidate ranking: 1.706 s (1.612 ms/candidate)
- Median shortlist refinement: 2.168 s for 97 candidates (22.854 ms/refined candidate)

## Full benchmark runtime

The complete benchmark contains 192 patterns. At the measured single-process median, processing every pattern against the full database is estimated to take 795.9 s (13.27 min).
