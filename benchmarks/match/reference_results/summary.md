# Match benchmark summary

Dataset SHA-256: `7d1c4017d58f8369ace1c763b030da2b4e599c817a7c2cf333d9a75b592238ad`

Selected weights (observed/reference/lines/seed): `0.170/0.830/0.000/0.000`

| Weights | Queries | MRR | Top-1 | Top-5 | Top-10 | Recall@10 |
|---|---:|---:|---:|---:|---:|---:|
| manuscript | 64 | 0.6777 | 0.5781 | 0.7812 | 0.8281 | 0.4805 |
| current | 64 | 0.7015 | 0.6094 | 0.7969 | 0.8438 | 0.4844 |
| equal | 64 | 0.6200 | 0.5156 | 0.7500 | 0.8281 | 0.4609 |
| selected | 64 | 0.7216 | 0.6562 | 0.7969 | 0.8594 | 0.4948 |

## Single-pattern runtime

Measured over 16 synthetic patterns; each pattern was searched against all 1058 candidates.

- Total sequential time: 34.519 s
- Mean per pattern: 2.157 s
- Median total: 2.043 s
- 95th percentile total: 2.715 s
- Median fingerprint retrieval: 0.010 s
- Median quick all-candidate ranking: 0.798 s (0.755 ms/candidate)
- Median shortlist refinement: 1.160 s for 97 candidates (12.531 ms/refined candidate)

## Full benchmark runtime

The complete benchmark contains 192 patterns. At the measured single-process median, processing every pattern against the full database is estimated to take 392.3 s (6.54 min).
