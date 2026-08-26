from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import threading
import time
from typing import Protocol

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot


ComparisonSignature = tuple[object, ...] | str
ComparisonBundle = object


class ComparisonExecutor(Protocol):
    def submit(
        self,
        work: Callable[[], ComparisonBundle],
        succeeded: Callable[[ComparisonBundle], None],
        failed: Callable[[BaseException], None],
    ) -> None: ...

    def close(self, timeout_ms: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class _Request:
    signature: ComparisonSignature
    work: Callable[[], ComparisonBundle]


class ComparisonRequestManager:
    """Serialize comparison work and publish only the latest requested signature."""

    def __init__(
        self,
        executor: ComparisonExecutor,
        ready: Callable[[ComparisonSignature, ComparisonBundle], None],
        failed: Callable[[ComparisonSignature, BaseException], None],
        *,
        max_cached: int = 8,
    ) -> None:
        self._executor = executor
        self._ready = ready
        self._failed = failed
        self._max_cached = max(1, int(max_cached))
        self._accepting = True
        self._current_signature: ComparisonSignature | None = None
        self._active: _Request | None = None
        self._pending: _Request | None = None
        self._cache: dict[ComparisonSignature, ComparisonBundle] = {}

    def request(
        self,
        signature: ComparisonSignature,
        work: Callable[[], ComparisonBundle],
    ) -> None:
        if not self._accepting:
            return
        self._current_signature = signature
        cached = self._cache.get(signature)
        if cached is not None:
            self._pending = None
            self._ready(signature, cached)
            return
        request = _Request(signature, work)
        if self._active is not None:
            self._pending = None if self._active.signature == signature else request
            return
        self._start(request)

    def close(self, timeout_ms: int = 100) -> bool:
        self._accepting = False
        self._pending = None
        return self._executor.close(timeout_ms)

    def _start(self, request: _Request) -> None:
        self._active = request
        self._executor.submit(
            request.work,
            lambda bundle: self._succeeded(request, bundle),
            lambda error: self._errored(request, error),
        )

    def _succeeded(self, request: _Request, bundle: ComparisonBundle) -> None:
        if request is not self._active:
            return
        self._active = None
        if not self._accepting:
            return
        self._cache[request.signature] = bundle
        while len(self._cache) > self._max_cached:
            self._cache.pop(next(iter(self._cache)))
        if request.signature == self._current_signature:
            self._ready(request.signature, bundle)
        self._start_pending()

    def _errored(self, request: _Request, error: BaseException) -> None:
        if request is not self._active:
            return
        self._active = None
        if not self._accepting:
            return
        if request.signature == self._current_signature:
            self._failed(request.signature, error)
        self._start_pending()

    def _start_pending(self) -> None:
        request = self._pending
        self._pending = None
        if request is not None and request.signature == self._current_signature:
            self._start(request)


class _ExecutorSignals(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, object)


@dataclass(frozen=True, slots=True)
class _ExecutorJob:
    succeeded: Callable[[ComparisonBundle], None]
    failed: Callable[[BaseException], None]
    cancelled: threading.Event


def _run_comparison_job(
    job_id: int,
    work: Callable[[], ComparisonBundle],
    signals: _ExecutorSignals,
    cancelled: threading.Event,
) -> None:
    try:
        bundle = work()
    except BaseException as error:
        if not cancelled.is_set():
            signals.failed.emit(job_id, error)
    else:
        if not cancelled.is_set():
            signals.succeeded.emit(job_id, bundle)


class QtComparisonExecutor(QObject):
    """Run comparison work in a daemon and marshal callbacks to the GUI thread."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # The application owns the bridge so its QObject is always destroyed on
        # the GUI thread, even when a cancelled daemon still retains its wrapper.
        self._signals = _ExecutorSignals(QCoreApplication.instance())
        self._signals.succeeded.connect(
            self._deliver_success,
            Qt.ConnectionType.QueuedConnection,
        )
        self._signals.failed.connect(
            self._deliver_failure,
            Qt.ConnectionType.QueuedConnection,
        )
        self._jobs: dict[int, _ExecutorJob] = {}
        self._threads: list[threading.Thread] = []
        self._next_job_id = 0
        self._accepting = True
        self._signals_connected = True

    def submit(
        self,
        work: Callable[[], ComparisonBundle],
        succeeded: Callable[[ComparisonBundle], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        if not self._accepting:
            return
        job_id = self._next_job_id
        self._next_job_id += 1
        cancelled = threading.Event()
        self._jobs[job_id] = _ExecutorJob(succeeded, failed, cancelled)
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(
            target=_run_comparison_job,
            args=(job_id, work, self._signals, cancelled),
            name=f"crystal-comparison-{job_id}",
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

    def close(self, timeout_ms: int = 100) -> bool:
        self._accepting = False
        jobs = tuple(self._jobs.values())
        self._jobs.clear()
        for job in jobs:
            job.cancelled.set()
        if self._signals_connected:
            self._signals.succeeded.disconnect(self._deliver_success)
            self._signals.failed.disconnect(self._deliver_failure)
            self._signals_connected = False
        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1_000.0
        threads = tuple(self._threads)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        return all(not thread.is_alive() for thread in threads)

    @Slot(int, object)
    def _deliver_success(self, job_id: int, bundle: ComparisonBundle) -> None:
        job = self._jobs.pop(job_id, None)
        if job is not None and self._accepting and not job.cancelled.is_set():
            job.succeeded(bundle)

    @Slot(int, object)
    def _deliver_failure(self, job_id: int, error: BaseException) -> None:
        job = self._jobs.pop(job_id, None)
        if job is not None and self._accepting and not job.cancelled.is_set():
            job.failed(error)


__all__ = [
    "ComparisonExecutor",
    "ComparisonRequestManager",
    "ComparisonSignature",
    "QtComparisonExecutor",
]
