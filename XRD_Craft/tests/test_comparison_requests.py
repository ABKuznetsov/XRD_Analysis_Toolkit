from __future__ import annotations

from dataclasses import dataclass
import gc
import os
import threading
import time
from typing import Callable
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from crystal_viewer.ui import main_window as main_module


@dataclass
class _Job:
    work: Callable[[], object]
    succeeded: Callable[[object], None]
    failed: Callable[[BaseException], None]


class _FakeExecutor:
    def __init__(self) -> None:
        self.jobs: list[_Job] = []
        self.close_calls: list[int] = []

    def submit(self, work, succeeded, failed) -> None:
        self.jobs.append(_Job(work, succeeded, failed))

    def close(self, timeout_ms: int) -> bool:
        self.close_calls.append(timeout_ms)
        return False


def _manager(executor: _FakeExecutor, ready: list, errors: list):
    return main_module.ComparisonRequestManager(
        executor,
        lambda signature, bundle: ready.append((signature, bundle)),
        lambda signature, error: errors.append((signature, str(error))),
    )


def test_one_active_request_queues_latest_signature_and_ignores_stale_result() -> None:
    executor = _FakeExecutor()
    ready: list[tuple[object, object]] = []
    errors: list[tuple[object, str]] = []
    manager = _manager(executor, ready, errors)

    manager.request("pair-a", lambda: "bundle-a")
    manager.request("pair-a", lambda: "duplicate-a")
    manager.request("pair-b", lambda: "bundle-b")

    assert len(executor.jobs) == 1
    executor.jobs[0].succeeded("bundle-a")
    assert ready == []
    assert len(executor.jobs) == 2

    executor.jobs[1].succeeded("bundle-b")

    assert ready == [("pair-b", "bundle-b")]
    assert errors == []


def test_successful_repeat_uses_bundle_cache_without_second_worker() -> None:
    executor = _FakeExecutor()
    ready: list[tuple[object, object]] = []
    manager = _manager(executor, ready, [])

    manager.request("pair", lambda: "bundle")
    executor.jobs[0].succeeded("bundle")
    manager.request("pair", lambda: "must-not-run")

    assert len(executor.jobs) == 1
    assert ready == [("pair", "bundle"), ("pair", "bundle")]


def test_failure_is_not_cached_retry_can_succeed_and_close_ignores_late_results() -> None:
    executor = _FakeExecutor()
    ready: list[tuple[object, object]] = []
    errors: list[tuple[object, str]] = []
    manager = _manager(executor, ready, errors)

    manager.request("pair", lambda: "first")
    executor.jobs[0].failed(RuntimeError("matcher failed"))
    manager.request("pair", lambda: "retry")
    executor.jobs[1].succeeded("retry")

    assert errors == [("pair", "matcher failed")]
    assert ready == [("pair", "retry")]
    assert len(executor.jobs) == 2

    manager.request("another", lambda: "late")
    manager.close(timeout_ms=75)
    executor.jobs[2].succeeded("late")

    assert executor.close_calls == [75]
    assert ready == [("pair", "retry")]


def test_qt_executor_runs_work_off_gui_thread_and_delivers_on_gui_thread() -> None:
    application = QApplication.instance() or QApplication([])
    executor = main_module.QtComparisonExecutor()
    loop = QEventLoop()
    gui_thread = threading.get_ident()
    worker_threads: list[int] = []
    callback_threads: list[int] = []
    results: list[object] = []

    def work() -> str:
        worker_threads.append(threading.get_ident())
        return "done"

    def succeeded(result: object) -> None:
        callback_threads.append(threading.get_ident())
        results.append(result)
        loop.quit()

    executor.submit(work, succeeded, lambda _error: loop.quit())
    QTimer.singleShot(2_000, loop.quit)
    loop.exec()

    assert application.thread().isCurrentThread()
    assert worker_threads and worker_threads[0] != gui_thread
    assert callback_threads == [gui_thread]
    assert results == ["done"]
    assert executor.close(1_000) is True


def test_close_and_executor_deletion_are_bounded_while_job_finishes_silently() -> None:
    application = QApplication.instance() or QApplication([])
    started = threading.Event()
    finished = threading.Event()
    callbacks: list[object] = []
    qt_messages: list[str] = []
    previous_handler = qInstallMessageHandler(
        lambda _kind, _context, message: qt_messages.append(message)
    )

    executor = main_module.QtComparisonExecutor()

    def work() -> str:
        started.set()
        time.sleep(0.5)
        finished.set()
        return "late"

    try:
        executor.submit(work, callbacks.append, callbacks.append)
        assert started.wait(0.5)
        reference = weakref.ref(executor)

        before = time.perf_counter()
        assert executor.close(10) is False
        del executor
        gc.collect()
        close_and_delete_seconds = time.perf_counter() - before

        assert close_and_delete_seconds < 0.2
        assert reference() is None
        assert finished.wait(1.0)
        application.processEvents()
        assert callbacks == []
        assert not any("thread" in message.lower() for message in qt_messages)
    finally:
        qInstallMessageHandler(previous_handler)
