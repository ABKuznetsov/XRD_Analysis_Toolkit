from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QTimer


class VisibleProfileCalculationQueue(QObject):
    """Run deferred visible-profile calculations one event-loop turn at a time."""

    def __init__(
        self,
        calculate: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._calculate = calculate
        self._pending: list[str] = []
        self._current: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._process_next)

    @property
    def is_busy(self) -> bool:
        return self._current is not None or bool(self._pending) or self._timer.isActive()

    def schedule(self, pattern_ids: Iterable[str]) -> None:
        queued = set(self._pending)
        if self._current is not None:
            queued.add(self._current)
        for pattern_id in pattern_ids:
            value = str(pattern_id or "")
            if value and value not in queued:
                self._pending.append(value)
                queued.add(value)
        if self._pending and self._current is None and not self._timer.isActive():
            self._timer.start(0)

    def clear(self) -> None:
        self._timer.stop()
        self._pending.clear()

    def _process_next(self) -> None:
        if self._current is not None or not self._pending:
            return
        self._current = self._pending.pop(0)
        try:
            self._calculate(self._current)
        finally:
            self._current = None
            if self._pending:
                self._timer.start(0)
