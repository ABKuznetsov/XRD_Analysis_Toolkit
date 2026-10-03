from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from benchmarks.match.extract_features import FeatureMatrix, FeatureRow, QueryTiming
from xrd_finder.finder.fingerprint_matching import FingerprintMatchFeatures


def save_feature_matrix(
    path: Path | str,
    matrix: FeatureMatrix,
    *,
    cache_key: str,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(
            """
            pragma journal_mode=off;
            create table metadata(key text primary key, value text not null);
            create table feature_rows(
                query_id text not null,
                candidate_id text not null,
                candidate_family text not null,
                dominant_family text not null,
                true_families_json text not null,
                split text not null,
                stratum text not null,
                observed_coverage real not null,
                reference_coverage real not null,
                sufficient_lines real not null,
                alignment_seed real not null,
                observed_matched integer not null,
                reference_matched integer not null,
                anchor_count integer not null,
                refined integer not null,
                primary key(query_id, candidate_id)
            );
            create index feature_rows_split_query on feature_rows(split, query_id);
            create table query_timings(
                query_id text primary key,
                candidate_count integer not null,
                refined_count integer not null,
                generation_seconds real not null,
                retrieval_seconds real not null,
                quick_seconds real not null,
                refine_seconds real not null,
                total_seconds real not null
            );
            """
        )
        connection.execute("insert into metadata values('cache_key', ?)", (str(cache_key),))
        connection.executemany(
            "insert into feature_rows values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    row.query_id,
                    row.candidate_id,
                    row.candidate_family,
                    row.dominant_family,
                    json.dumps(row.true_families),
                    row.split,
                    row.stratum,
                    row.features.observed_coverage,
                    row.features.reference_coverage,
                    row.features.sufficient_lines,
                    row.features.alignment_seed,
                    row.features.observed_matched,
                    row.features.reference_matched,
                    row.features.anchor_count,
                    int(row.refined),
                )
                for row in matrix.rows
            ),
        )
        connection.executemany(
            "insert into query_timings values(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    item.query_id,
                    item.candidate_count,
                    item.refined_count,
                    item.generation_seconds,
                    item.retrieval_seconds,
                    item.quick_seconds,
                    item.refine_seconds,
                    item.total_seconds,
                )
                for item in matrix.timings
            ),
        )
        connection.commit()
    finally:
        connection.close()
    temporary.replace(output)
    return output


def load_feature_matrix(
    path: Path | str,
    *,
    expected_cache_key: str | None = None,
) -> FeatureMatrix:
    connection = sqlite3.connect(Path(path))
    try:
        row = connection.execute("select value from metadata where key='cache_key'").fetchone()
        cache_key = str(row[0]) if row else ""
        if expected_cache_key is not None and cache_key != expected_cache_key:
            raise ValueError("Feature cache does not match this dataset and scenario manifest.")
        feature_rows = tuple(
            FeatureRow(
                query_id=item[0],
                candidate_id=item[1],
                candidate_family=item[2],
                dominant_family=item[3],
                true_families=tuple(json.loads(item[4])),
                split=item[5],
                stratum=item[6],
                features=FingerprintMatchFeatures(*item[7:14]),
                refined=bool(item[14]),
            )
            for item in connection.execute("select * from feature_rows order by query_id, candidate_id")
        )
        timings = tuple(
            QueryTiming(*item)
            for item in connection.execute("select * from query_timings order by query_id")
        )
        return FeatureMatrix(feature_rows, timings)
    finally:
        connection.close()


__all__ = ["load_feature_matrix", "save_feature_matrix"]
