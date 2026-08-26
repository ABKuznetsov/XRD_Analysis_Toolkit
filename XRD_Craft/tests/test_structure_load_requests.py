from __future__ import annotations

from dataclasses import dataclass
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from crystal_viewer.ui.structure_load_requests import (
    QtStructureLoadExecutor,
    StructureLoadRequestManager,
)


@dataclass
class _Job:
    work: object
    progressed: object
    succeeded: object
    failed: object


class _Executor:
    def __init__(self) -> None:
        self.jobs: list[_Job] = []
        self.close_calls: list[int] = []

    def submit(self, work, progressed, succeeded, failed) -> None:
        self.jobs.append(_Job(work, progressed, succeeded, failed))

    def close(self, timeout_ms: int) -> bool:
        self.close_calls.append(timeout_ms)
        return False


def test_new_request_suppresses_old_progress_and_runs_latest_pending() -> None:
    executor = _Executor()
    progress = []
    ready = []
    errors = []
    manager = StructureLoadRequestManager(
        executor,
        lambda signature, update: progress.append((signature, update)),
        ready.append,
        lambda signature, error: errors.append((signature, str(error))),
    )

    manager.request("A", lambda emit: emit("A-work"))
    executor.jobs[0].progressed("A-atoms")
    manager.request("B", lambda emit: emit("B-work"))
    executor.jobs[0].progressed("A-bonds")
    executor.jobs[0].succeeded(None)

    assert progress == [("A", "A-atoms")]
    assert ready == []
    assert len(executor.jobs) == 2

    executor.jobs[1].progressed("B-atoms")
    executor.jobs[1].succeeded(None)
    assert progress[-1] == ("B", "B-atoms")
    assert ready == ["B"]
    assert errors == []


def test_close_ignores_late_callbacks() -> None:
    executor = _Executor()
    progress = []
    ready = []
    manager = StructureLoadRequestManager(
        executor,
        lambda *value: progress.append(value),
        ready.append,
        lambda *_: None,
    )
    manager.request("A", lambda _emit: None)

    manager.close(25)
    executor.jobs[0].progressed("late")
    executor.jobs[0].succeeded(None)

    assert progress == []
    assert ready == []
    assert executor.close_calls == [25]


def test_qt_executor_runs_work_off_gui_thread_and_progress_on_gui_thread() -> None:
    app = QApplication.instance() or QApplication([])
    executor = QtStructureLoadExecutor()
    loop = QEventLoop()
    gui_thread = threading.get_ident()
    worker_threads = []
    callback_threads = []
    updates = []

    def work(emit):
        worker_threads.append(threading.get_ident())
        emit("atoms")

    def progressed(update):
        callback_threads.append(threading.get_ident())
        updates.append(update)

    executor.submit(work, progressed, lambda _result: loop.quit(), lambda _error: loop.quit())
    QTimer.singleShot(2_000, loop.quit)
    loop.exec()

    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != gui_thread
    assert callback_threads == [gui_thread]
    assert updates == ["atoms"]
    assert executor.close(1_000) is True
    assert app.thread().isCurrentThread()

