from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass


RETRIEVAL_CHANNELS = ("strong", "rare", "geometry", "overlap")


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    phase_id: str
    channel: str
    score: float
    rank: int
    evidence_count: int


@dataclass(frozen=True, slots=True)
class RetrievalChannelRun:
    channel: str
    hits: tuple[RetrievalHit, ...]
    elapsed_seconds: float
    diagnostic: str = ""


def rank_channel_scores(
    channel: str,
    scores: Mapping[str, float],
    evidence_counts: Mapping[str, int],
    *,
    limit: int,
) -> RetrievalChannelRun:
    """Return finite positive channel scores in deterministic rank order."""

    started = time.perf_counter()
    ranked: list[tuple[float, str, int]] = []
    for raw_phase_id, raw_score in scores.items():
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score) or score <= 0.0:
            continue
        phase_id = str(raw_phase_id)
        raw_evidence = evidence_counts.get(
            raw_phase_id, evidence_counts.get(phase_id, 0)
        )
        try:
            evidence_count = max(0, int(raw_evidence))
        except (TypeError, ValueError, OverflowError):
            evidence_count = 0
        ranked.append((score, phase_id, evidence_count))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = ranked[: max(0, int(limit))]
    hits = tuple(
        RetrievalHit(
            phase_id=phase_id,
            channel=str(channel),
            score=score,
            rank=rank,
            evidence_count=evidence_count,
        )
        for rank, (score, phase_id, evidence_count) in enumerate(
            selected, start=1
        )
    )
    elapsed = max(0.0, time.perf_counter() - started)
    return RetrievalChannelRun(
        channel=str(channel),
        hits=hits,
        elapsed_seconds=elapsed,
    )


__all__ = [
    "RETRIEVAL_CHANNELS",
    "RetrievalChannelRun",
    "RetrievalHit",
    "rank_channel_scores",
]
