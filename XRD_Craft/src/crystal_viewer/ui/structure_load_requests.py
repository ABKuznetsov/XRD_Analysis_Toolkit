from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import threading
import time
from typing import Protocol

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot


LoadSignature = tuple[object, ...] | str
ProgressCallback = Callable[[object], None]
LoadWork = Callable[[ProgressCallback], object]


class StructureLoadExecutor(Protocol):
    def submit(
        self,
        work: LoadWork,
        progressed: ProgressCallback,
        succeeded: Callable[[object], None],
        failed: Callable[[BaseException], None],
    ) -> None: ...

    def close(self, timeout_ms: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class _Request:
    signature: LoadSignature
    work: LoadWork


class StructureLoadRequestManager:
    """Serialize loads and publish progress only for the latest request."""

    def __init__(
        self,
        executor: StructureLoadExecutor,
        progressed: Callable[[LoadSignature, object], None],
        ready: Callable[[LoadSignature], None],
        failed: Callable[[LoadSignature, BaseException], None],
    ) -> None:
        self._executor = executor
        self._progressed = progressed
        self._ready = ready
        self._failed = failed
        self._accepting = True
        self._current_signature: LoadSignature | None = None
        self._active: _Request | None = None
        self._pending: _Request | None = None

    def request(self, signature: LoadSignature, work: LoadWork) -> None:
        if not self._accepting:
            return
        self._current_signature = signature
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
            lambda update: self._progress(request, update),
            lambda result: self._succeeded(request, result),
            lambda error: self._errored(request, error),
        )

    def _progress(self, request: _Request, update: object) -> None:
        if (
            self._accepting
            and request is self._active
            and request.signature == self._current_signature
        ):
            self._progressed(request.signature, update)

    def _succeeded(self, request: _Request, _result: object) -> None:
        if request is not self._active:
            return
        self._active = None
        if not self._accepting:
            return
        if request.signature == self._current_signature:
            self._ready(request.signature)
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


class _Signals(QObject):
    progressed = Signal(int, object)
    succeeded = Signal(int, object)
    failed = Signal(int, object)


@dataclass(frozen=True, slots=True)
class _Job:
    progressed: ProgressCallback
    succeeded: Callable[[object], None]
    failed: Callable[[BaseException], None]
    cancelled: threading.Event


def _run_job(
    job_id: int,
    work: LoadWork,
    signals: _Signals,
    cancelled: threading.Event,
) -> None:
    def emit(update: object) -> None:
        if not cancelled.is_set():
            signals.progressed.emit(job_id, update)

    try:
        result = work(emit)
    except BaseException as error:
        if not cancelled.is_set():
            signals.failed.emit(job_id, error)
    else:
        if not cancelled.is_set():
            signals.succeeded.emit(job_id, result)


class QtStructureLoadExecutor(QObject):
    """Run staged loading in a daemon and deliver updates on the Qt thread."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._signals = _Signals(QCoreApplication.instance())
        self._signals.progressed.connect(self._deliver_progress, Qt.ConnectionType.QueuedConnection)
        self._signals.succeeded.connect(self._deliver_success, Qt.ConnectionType.QueuedConnection)
        self._signals.failed.connect(self._deliver_failure, Qt.ConnectionType.QueuedConnection)
        self._jobs: dict[int, _Job] = {}
        self._threads: list[threading.Thread] = []
        self._next_job_id = 0
        self._accepting = True
        self._signals_connected = True

    def submit(self, work, progressed, succeeded, failed) -> None:
        if not self._accepting:
            return
        job_id = self._next_job_id
        self._next_job_id += 1
        cancelled = threading.Event()
        self._jobs[job_id] = _Job(progressed, succeeded, failed, cancelled)
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(
            target=_run_job,
            args=(job_id, work, self._signals, cancelled),
            name=f"crystal-load-{job_id}",
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
            self._signals.progressed.disconnect(self._deliver_progress)
            self._signals.succeeded.disconnect(self._deliver_success)
            self._signals.failed.disconnect(self._deliver_failure)
            self._signals_connected = False
        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1_000.0
        for thread in tuple(self._threads):
            thread.join(max(0.0, deadline - time.monotonic()))
        return all(not thread.is_alive() for thread in self._threads)

    @Slot(int, object)
    def _deliver_progress(self, job_id: int, update: object) -> None:
        job = self._jobs.get(job_id)
        if job is not None and self._accepting and not job.cancelled.is_set():
            job.progressed(update)

    @Slot(int, object)
    def _deliver_success(self, job_id: int, result: object) -> None:
        job = self._jobs.pop(job_id, None)
        if job is not None and self._accepting and not job.cancelled.is_set():
            job.succeeded(result)

    @Slot(int, object)
    def _deliver_failure(self, job_id: int, error: BaseException) -> None:
        job = self._jobs.pop(job_id, None)
        if job is not None and self._accepting and not job.cancelled.is_set():
            job.failed(error)


__all__ = [
    "QtStructureLoadExecutor",
    "StructureLoadExecutor",
    "StructureLoadRequestManager",
]
