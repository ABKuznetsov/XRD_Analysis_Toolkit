from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
import itertools
import queue
import threading


class CandidatePreparationStage(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CandidatePreparationJob:
    source: str
    entry_id: str
    index: Callable[[object], object]
    fetch: Callable[[], object] | None = None
    existing_payload: object | None = None
    priority: int = 100

    @property
    def key(self) -> tuple[str, str]:
        return self.source.strip().upper(), self.entry_id.strip()


@dataclass(frozen=True, slots=True)
class CandidatePreparationProgress:
    queued: int = 0
    downloading: int = 0
    indexing: int = 0
    ready: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class CandidatePreparedNotice:
    session_tokens: tuple[int, ...]
    source: str
    entry_id: str
    stage: CandidatePreparationStage
    result: object | None = None
    error: str = ""


@dataclass(slots=True)
class _PendingJob:
    job: CandidatePreparationJob
    stage: CandidatePreparationStage = CandidatePreparationStage.QUEUED
    session_tokens: set[int] = field(default_factory=set)


class CandidatePreparationQueue:
    """Serial download/index queue shared by overlapping search sessions."""

    def __init__(
        self,
        *,
        notice_callback: Callable[[CandidatePreparedNotice], None] | None = None,
        progress_callback: Callable[[CandidatePreparationProgress], None] | None = None,
    ) -> None:
        self._notice_callback = notice_callback
        self._progress_callback = progress_callback
        self._lock = threading.Lock()
        self._jobs: dict[tuple[str, str], _PendingJob] = {}
        self._ready = 0
        self._failed = 0
        self._sequence = itertools.count()
        self._queue: queue.PriorityQueue[tuple[int, int, tuple[str, str] | None]] = queue.PriorityQueue()
        self._shutdown = False
        self._thread = threading.Thread(
            target=self._run,
            name="xrd-candidate-preparation",
            daemon=True,
        )
        self._thread.start()

    def submit(self, job: CandidatePreparationJob, *, session_token: int | None = None) -> bool:
        key = job.key
        if not key[0] or not key[1]:
            raise ValueError("Candidate preparation requires source and entry_id.")
        with self._lock:
            if self._shutdown:
                return False
            pending = self._jobs.get(key)
            if pending is not None:
                if session_token is not None:
                    pending.session_tokens.add(int(session_token))
                return False
            pending = _PendingJob(job=job)
            if session_token is not None:
                pending.session_tokens.add(int(session_token))
            self._jobs[key] = pending
            self._queue.put((int(job.priority), next(self._sequence), key))
            progress = self._progress_locked()
        self._emit_progress(progress)
        return True

    def progress(self) -> CandidatePreparationProgress:
        with self._lock:
            return self._progress_locked()

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._queue.put((2**31 - 1, next(self._sequence), None))
        if wait and threading.current_thread() is not self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            _priority, _sequence, key = self._queue.get()
            try:
                if key is None:
                    return
                with self._lock:
                    pending = self._jobs.get(key)
                if pending is None:
                    continue
                payload = pending.job.existing_payload
                if pending.job.fetch is not None:
                    self._set_stage(key, CandidatePreparationStage.DOWNLOADING)
                    payload = pending.job.fetch()
                self._set_stage(key, CandidatePreparationStage.INDEXING)
                result = pending.job.index(payload)
                self._finish(key, CandidatePreparationStage.READY, result=result)
            except Exception as exc:
                if key is not None:
                    self._finish(key, CandidatePreparationStage.FAILED, error=str(exc))
            finally:
                self._queue.task_done()

    def _set_stage(self, key: tuple[str, str], stage: CandidatePreparationStage) -> None:
        with self._lock:
            pending = self._jobs.get(key)
            if pending is None:
                return
            pending.stage = stage
            progress = self._progress_locked()
        self._emit_progress(progress)

    def _finish(
        self,
        key: tuple[str, str],
        stage: CandidatePreparationStage,
        *,
        result: object | None = None,
        error: str = "",
    ) -> None:
        with self._lock:
            pending = self._jobs.pop(key, None)
            if pending is None:
                return
            if stage is CandidatePreparationStage.READY:
                self._ready += 1
            else:
                self._failed += 1
            notice = CandidatePreparedNotice(
                session_tokens=tuple(sorted(pending.session_tokens)),
                source=key[0],
                entry_id=key[1],
                stage=stage,
                result=result,
                error=error,
            )
            progress = self._progress_locked()
        self._emit_notice(notice)
        self._emit_progress(progress)

    def _progress_locked(self) -> CandidatePreparationProgress:
        stages = [pending.stage for pending in self._jobs.values()]
        return CandidatePreparationProgress(
            queued=stages.count(CandidatePreparationStage.QUEUED),
            downloading=stages.count(CandidatePreparationStage.DOWNLOADING),
            indexing=stages.count(CandidatePreparationStage.INDEXING),
            ready=self._ready,
            failed=self._failed,
        )

    def _emit_notice(self, notice: CandidatePreparedNotice) -> None:
        if self._notice_callback is None:
            return
        try:
            self._notice_callback(notice)
        except Exception:
            pass

    def _emit_progress(self, progress: CandidatePreparationProgress) -> None:
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(progress)
        except Exception:
            pass
