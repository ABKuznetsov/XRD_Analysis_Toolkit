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
    batch_index: Callable | None = None
    native_request: dict | None = None

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
    """Shared download queue with optional batches of native preparation work."""

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

    def has_pending(self, keys) -> bool:
        """Whether a bounded download batch still has consumers."""
        with self._lock:
            return not self._shutdown and any(key in self._jobs for key in keys)

    def cancel_session(self, session_token: int) -> int:
        """Detach a search session and discard jobs used only by that session."""
        token = int(session_token)
        cancelled = 0
        with self._lock:
            for key, pending in tuple(self._jobs.items()):
                if token not in pending.session_tokens:
                    continue
                pending.session_tokens.discard(token)
                if pending.session_tokens:
                    continue
                self._jobs.pop(key, None)
                cancelled += 1
            progress = self._progress_locked()
        self._emit_progress(progress)
        return cancelled

    def clear(self) -> int:
        """Discard all queued work and detach any preparation already in flight."""
        with self._lock:
            cancelled = len(self._jobs)
            self._jobs.clear()
            self._ready = 0
            self._failed = 0
            progress = self._progress_locked()
        self._emit_progress(progress)
        return cancelled

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
            pending: _PendingJob | None = None
            try:
                if key is None:
                    return
                with self._lock:
                    pending = self._jobs.get(key)
                if pending is None:
                    continue
                if pending.job.batch_index is not None:
                    self._run_native_batch(key, pending)
                    continue
                payload = pending.job.existing_payload
                if pending.job.fetch is not None:
                    self._set_stage(key, CandidatePreparationStage.DOWNLOADING)
                    if not self._is_current(key, pending):
                        continue
                    payload = pending.job.fetch()
                    if not self._is_current(key, pending):
                        continue
                self._set_stage(key, CandidatePreparationStage.INDEXING)
                if not self._is_current(key, pending):
                    continue
                result = pending.job.index(payload)
                self._finish(
                    key,
                    CandidatePreparationStage.READY,
                    result=result,
                    expected=pending,
                )
            except Exception as exc:
                if key is not None:
                    self._finish(
                        key,
                        CandidatePreparationStage.FAILED,
                        error=str(exc),
                        expected=pending,
                    )
            finally:
                self._queue.task_done()

    def _run_native_batch(self, first_key, first_pending):
        """Fetch up to 100 CIFs, then let persistent native processes prepare them."""
        handler = first_pending.job.batch_index
        prepared = []
        taken = 0
        key, pending = first_key, first_pending
        try:
            for position in range(100):
                if self._is_current(key, pending):
                    try:
                        payload = pending.job.existing_payload
                        if pending.job.fetch is not None:
                            self._set_stage(key, CandidatePreparationStage.DOWNLOADING)
                            payload = pending.job.fetch()
                        if self._is_current(key, pending):
                            self._set_stage(key, CandidatePreparationStage.INDEXING)
                            prepared.append((key, pending, payload))
                    except Exception as error:
                        self._finish(key, CandidatePreparationStage.FAILED, error=str(error), expected=pending)
                if position == 99:
                    break
                try:
                    queued = self._queue.get_nowait()
                except queue.Empty:
                    break
                priority, sequence, next_key = queued
                with self._lock:
                    next_pending = self._jobs.get(next_key)
                if next_key is None or next_pending is not None and next_pending.job.batch_index != handler:
                    # Preserve the original priority/order of unrelated jobs.
                    self._queue.put(queued)
                    self._queue.task_done()
                    break
                taken += 1
                key, pending = next_key, next_pending
                if pending is None:
                    # A cancelled entry consumes no native work.
                    pending = _PendingJob(first_pending.job)
            prepared = [item for item in prepared if self._is_current(item[0], item[1])]
            if not prepared:
                return
            def cancelled():
                return self._shutdown or not any(self._is_current(key, pending) for key, pending, _ in prepared)
            def ready(index, success, error):
                key, pending, payload = prepared[int(index)]
                self._finish(key, CandidatePreparationStage.READY if success else CandidatePreparationStage.FAILED,
                             result=payload if success else None, error=error, expected=pending)
            requests = [(pending.job.native_request, payload) for _, pending, payload in prepared]
            handler(requests, ready, cancelled)
        except Exception as error:
            for key, pending, _ in prepared:
                self._finish(key, CandidatePreparationStage.FAILED, error=str(error), expected=pending)
        finally:
            for _ in range(taken):
                self._queue.task_done()

    def _is_current(self, key: tuple[str, str], pending: _PendingJob) -> bool:
        with self._lock:
            return self._jobs.get(key) is pending

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
        expected: _PendingJob | None = None,
    ) -> None:
        with self._lock:
            pending = self._jobs.get(key)
            if expected is not None and pending is not expected:
                return
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
