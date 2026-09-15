from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CandidateBatchStatus:
    local: int = 0
    queued: int = 0
    downloading: int = 0
    indexing: int = 0
    ready: int = 0
    ranking: int = 0
    indexed: int = 0
    pending_display: int = 0
    displayed: int = 0
    failed: int = 0
    notice: str = ""


def candidate_batch_status_text(status: CandidateBatchStatus) -> str:
    return (
        "Candidates: "
        f"local {status.local}, queued {status.queued}, "
        f"downloading {status.downloading}, indexing {status.indexing}, "
        f"ready {status.ready}, ranking {status.ranking}, "
        f"pending display {status.pending_display}, added {status.displayed}, "
        f"failed {status.failed}"
    )


def candidate_batch_detail_text(status: CandidateBatchStatus) -> str:
    found = status.local + status.displayed
    loading = status.queued + status.downloading + status.indexing + status.pending_display + status.ranking
    ready = max(status.ready, status.displayed)
    parts = [f"Found {found}", f"Loading {loading}", f"Ready {ready}"]
    if status.failed:
        parts.append(f"Failed {status.failed}")
    if status.notice:
        parts.append(status.notice)
    return " | ".join(parts)


def candidate_batch_title_text(
    status: CandidateBatchStatus,
    *,
    searching: bool = False,
) -> str:
    active = (
        status.queued
        + status.downloading
        + status.indexing
        + status.pending_display
        + status.ranking
    )
    loaded = status.local + status.displayed
    suffix = f" ({status.notice})" if status.notice else ""
    if searching:
        if not loaded:
            return f"Candidate list: searching{suffix}"
        if not active:
            return f"Candidate list: loading {loaded}{suffix}"
        return f"Candidate list: loading {loaded}/{loaded + active}{suffix}"
    if loaded:
        return f"Candidate list: best {loaded}{suffix}"
    return f"Candidate list{suffix}"
