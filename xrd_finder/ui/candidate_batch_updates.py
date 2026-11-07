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
        rows_loader: Callable[[tuple[tuple[str, str], ...]], list[list[str]]] | None = None,
        status_callback: Callable[[str], None] | None = None,
        title_callback: Callable[[str], None] | None = None,
        detail_callback: Callable[[str], None] | None = None,
        state_callback: Callable[[str], None] | None = None,
        interval_ms: int = 50,
        max_batch_rows: int = 100,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._row_loader = row_loader
        self._rows_loader = rows_loader
        self._rows_ready = rows_ready
        self._status_callback = status_callback
        self._title_callback = title_callback
        self._detail_callback = detail_callback
        self._state_callback = state_callback
        self._max_batch_rows = max(1, int(max_batch_rows))
        self._active_session_token: int | None = None
        self._searching = False
        self._pending: dict[tuple[str, str], None] = {}
        self._found_keys = set()
        self._ready_keys = set()
        self._failed_keys = set()
        self._notified_keys = set()
        self._identified_counts = False
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
        self._search_error = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(1, int(interval_ms)))
        self._timer.timeout.connect(self.flush_now)

    def start_session(self, session_token: int) -> None:
        self._timer.stop()
        self._active_session_token = int(session_token)
        self._pending.clear()
        self._found_keys.clear()
        self._ready_keys.clear()
        self._failed_keys.clear()
        self._notified_keys.clear()
        self._identified_counts = False
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
        self._search_error = ""
        self._searching = True
        self._emit_status()

    def set_local_rows(self, count: int) -> None:
        self._local = max(0, int(count))
        self._emit_status()

    def set_candidate_rows(self, rows, *, prepared_keys=()) -> None:
        """Catalog rows and later ready updates refer to the same identities."""
        self._identified_counts = True
        self._found_keys.update((str(row[0]).strip().upper(), str(row[1]).strip())
            for row in rows if len(row) > 1 and str(row[0]).strip() and str(row[1]).strip())
        self._ready_keys.update(set(prepared_keys) & self._found_keys)
        self._local = len(self._found_keys)
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
        if self._active_session_token is None:
            return
        self._queued = max(0, int(progress.queued))
        self._downloading = max(0, int(progress.downloading))
        self._indexing = max(0, int(progress.indexing))
        if not self._identified_counts:
            self._ready = max(self._ready, int(progress.ready))
            self._failed = max(self._failed, int(progress.failed))
        self._emit_status()

    def accept_notice(self, notice: CandidatePreparedNotice) -> bool:
        token = self._active_session_token
        if token is None or token not in notice.session_tokens:
            return False
        key = notice.source.strip().upper(), notice.entry_id.strip()
        if not all(key):
            return False
        self._found_keys.add(key)
        if notice.stage is CandidatePreparationStage.FAILED:
            if key in self._failed_keys:
                return True
            self._failed_keys.add(key)
            self._failed += 1
            self._emit_status()
            return True
        if notice.stage is not CandidatePreparationStage.READY:
            return False
        self._ready_keys.add(key)
        self._failed_keys.discard(key)
        if key in self._notified_keys:
            return True
        self._notified_keys.add(key)
        if key not in self._pending:
            self._pending[key] = None
            self._indexed += 1
        if not self._timer.isActive():
            self._timer.start()
        self._emit_status()
        return True

    def flush_now(self) -> int:
        self._timer.stop()
        keys = tuple(self._pending)[: self._max_batch_rows]
        for key in keys:
            self._pending.pop(key, None)
        rows: list[list[str]] = []
        if keys and self._rows_loader is not None:
            rows = self._rows_loader(keys)
        else:
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
        if self._pending:
            self._timer.start()
        self._emit_status()
        return len(rows)

    def finish(self) -> int:
        self._searching = False
        self._emit_status()
        displayed = 0
        while self._pending:
            displayed += self.flush_now()
        return displayed

    def mark_search_complete(self, session_token: int | None = None, *, error: str = "") -> bool:
        if session_token is not None and session_token != self._active_session_token:
            return False
        self._searching = False
        if error:
            self._search_error = str(error)
            self._notice = " ".join(str(error).split())
        self._emit_status()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._active_session_token = None
        self._pending.clear()
        self._found_keys.clear()
        self._ready_keys.clear()
        self._failed_keys.clear()
        self._notified_keys.clear()
        self._identified_counts = False
        self._searching = False
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
        self._search_error = ""
        if self._title_callback is not None:
            self._title_callback("Candidate list")
        if self._detail_callback is not None:
            self._detail_callback("")
        if self._state_callback is not None:
            self._state_callback("idle")

    @property
    def activity_state(self) -> str:
        if self._active_session_token is None:
            return "idle"
        if self._searching or self._queued + self._downloading + self._indexing + self._ranking + len(self._pending):
            return "busy"
        failed = len(self._failed_keys) if self._identified_counts else self._failed
        return "error" if failed or self._search_error else "complete"

    def _emit_status(self) -> None:
        status = CandidateBatchStatus(
            found=len(self._found_keys) if self._identified_counts else None,
            local=self._local,
            queued=self._queued,
            downloading=self._downloading,
            indexing=self._indexing,
            ready=len(self._ready_keys) if self._identified_counts else self._ready,
            ranking=self._ranking,
            indexed=self._indexed,
            pending_display=len(self._pending),
            displayed=self._displayed,
            failed=len(self._failed_keys) if self._identified_counts else self._failed,
            notice=self._notice,
        )
        if self._state_callback is not None:
            self._state_callback(self.activity_state)
        if self._status_callback is not None:
            self._status_callback(candidate_batch_status_text(status))
        if self._title_callback is not None:
            self._title_callback(
                candidate_batch_title_text(status, searching=self._searching)
            )
        if self._detail_callback is not None:
            self._detail_callback(candidate_batch_detail_text(status))
