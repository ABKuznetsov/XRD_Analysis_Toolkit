from __future__ import annotations

from dataclasses import dataclass

from crystal_viewer.ui.knowledge_requests import KnowledgeRequestManager


@dataclass
class _Job:
    work: object
    succeeded: object
    failed: object


class _Executor:
    def __init__(self):
        self.jobs = []
        self.closed = []

    def submit(self, work, succeeded, failed):
        self.jobs.append(_Job(work, succeeded, failed))

    def close(self, timeout_ms):
        self.closed.append(timeout_ms)
        return False


def test_latest_document_suppresses_stale_knowledge_result():
    executor = _Executor()
    ready = []
    manager = KnowledgeRequestManager(
        executor,
        lambda signature, proposal: ready.append((signature, proposal)),
        lambda *_args: None,
    )

    manager.request("document-a", lambda: "proposal-a")
    manager.request("document-b", lambda: "proposal-b")
    executor.jobs[0].succeeded("proposal-a")
    executor.jobs[1].succeeded("proposal-b")

    assert ready == [("document-b", "proposal-b")]


def test_success_is_cached_but_failure_can_be_retried():
    executor = _Executor()
    ready = []
    errors = []
    manager = KnowledgeRequestManager(
        executor,
        lambda signature, proposal: ready.append((signature, proposal)),
        lambda signature, error: errors.append((signature, str(error))),
    )

    manager.request("bad", lambda: None)
    executor.jobs[0].failed(RuntimeError("invalid preset"))
    manager.request("bad", lambda: "recovered")
    executor.jobs[1].succeeded("recovered")
    manager.request("bad", lambda: "must not execute")

    assert errors == [("bad", "invalid preset")]
    assert ready == [("bad", "recovered"), ("bad", "recovered")]
    assert len(executor.jobs) == 2


def test_close_is_bounded_and_ignores_late_delivery():
    executor = _Executor()
    ready = []
    manager = KnowledgeRequestManager(
        executor,
        lambda *_args: ready.append("unexpected"),
        lambda *_args: None,
    )
    manager.request("document", lambda: "late")

    assert manager.close(25) is False
    executor.jobs[0].succeeded("late")

    assert executor.closed == [25]
    assert ready == []
