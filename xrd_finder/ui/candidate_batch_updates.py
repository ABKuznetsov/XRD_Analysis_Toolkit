from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from xrd_finder.services.candidate_preparation_queue import (
    CandidatePreparationProgress,
    CandidatePreparationStage,
    CandidatePreparedNotice,
)
from xrd_finder.ui.candidate_search_status import (
    CandidateBatchStatus,
    candidate_batch_detail_text,
    candidate_batch_status_text,
    candidate_batch_title_text,
)


class CandidateBatchUpdateController(QObject):
    """Coalesce indexed candidates before updating the visible table."""

    def __init__(
        self,
        *,
        row_loader: Callable[[str, str], list[str] | None],
        rows_ready: Callable[[list[list[str]]], None],
        status_callback: Callable[[str], None] | None = None,
        title_callback: Callable[[str], None] | None = None,
        detail_callback: Callable[[str], None] | None = None,
        interval_ms: int = 250,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._row_loader = row_loader
        self._rows_ready = rows_ready
        self._status_callback = status_callback
        self._title_callback = title_callback
        self._detail_callback = detail_callback
        self._active_session_token: int | None = None
        self._searching = False
        self._pending: dict[tuple[str, str], None] = {}
        self._local = 0
        self._queued = 0
        self._downloading = 0
        self._indexing = 0
        self._ready = 0
        self._ranking = 0
        self._indexed = 0
        self._displayed = 0
        self._failed = 0
        self._notice = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(1, int(interval_ms)))
        self._timer.timeout.connect(self.flush_now)

    def start_session(self, session_token: int) -> None:
        self._timer.stop()
        self._active_session_token = int(session_token)
        self._pending.clear()
        self._local = 0
        self._queued = 0
        self._downloading = 0
        self._indexing = 0
        self._ready = 0
        self._ranking = 0
        self._indexed = 0
        self._displayed = 0
        self._failed = 0
        self._notice = ""
        self._searching = True
        self._emit_status()

    def set_local_rows(self, count: int) -> None:
        self._local = max(0, int(count))
        self._emit_status()

    def set_notice(self, message: str) -> None:
        self._notice = " ".join(str(message or "").split())
        self._emit_status()

    def clear_notice(self) -> None:
        if not self._notice:
            return
        self._notice = ""
        self._emit_status()

    def accept_progress(self, progress: CandidatePreparationProgress) -> None:
        self._queued = max(0, int(progress.queued))
        self._downloading = max(0, int(progress.downloading))
        self._indexing = max(0, int(progress.indexing))
        self._ready = max(self._ready, int(progress.ready))
        self._failed = max(self._failed, int(progress.failed))
        self._emit_status()

    def accept_notice(self, notice: CandidatePreparedNotice) -> bool:
        token = self._active_session_token
        if token is None or token not in notice.session_tokens:
            return False
        if notice.stage is CandidatePreparationStage.FAILED:
            self._failed += 1
            self._emit_status()
            return True
        if notice.stage is not CandidatePreparationStage.READY:
            return False
        key = notice.source.strip().upper(), notice.entry_id.strip()
        if not key[0] or not key[1]:
            return False
        if key not in self._pending:
            self._pending[key] = None
            self._indexed += 1
        if not self._timer.isActive():
            self._timer.start()
        self._emit_status()
        return True

    def flush_now(self) -> int:
        self._timer.stop()
        keys = tuple(self._pending)
        self._pending.clear()
        rows: list[list[str]] = []
        for source, entry_id in keys:
            row = self._row_loader(source, entry_id)
            if row:
                rows.append(row)
        if rows:
            self._ranking = len(rows)
            self._emit_status()
            self._rows_ready(rows)
            self._displayed += len(rows)
            self._ranking = 0
        self._emit_status()
        return len(rows)

    def finish(self) -> int:
        self._searching = False
        self._emit_status()
        return self.flush_now()

    def mark_search_complete(self, session_token: int | None = None) -> bool:
        if session_token is not None and session_token != self._active_session_token:
            return False
        self._searching = False
        self._emit_status()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._active_session_token = None
        self._pending.clear()
        self._searching = False
        self._notice = ""
        if self._title_callback is not None:
            self._title_callback("Candidate list")
        if self._detail_callback is not None:
            self._detail_callback("")

    def _emit_status(self) -> None:
        status = CandidateBatchStatus(
            local=self._local,
            queued=self._queued,
            downloading=self._downloading,
            indexing=self._indexing,
            ready=self._ready,
            ranking=self._ranking,
            indexed=self._indexed,
            pending_display=len(self._pending),
            displayed=self._displayed,
            failed=self._failed,
            notice=self._notice,
        )
        if self._status_callback is not None:
            self._status_callback(candidate_batch_status_text(status))
        if self._title_callback is not None:
            self._title_callback(
                candidate_batch_title_text(status, searching=self._searching)
            )
        if self._detail_callback is not None:
            self._detail_callback(candidate_batch_detail_text(status))
