from __future__ import annotations

from contextlib import AbstractContextManager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
import logging
from logging.handlers import QueueHandler
import os
from pathlib import Path
import platform
from queue import SimpleQueue
import re
import sys
import threading
import time
import traceback
from types import TracebackType
from typing import Any
from uuid import uuid4

from xrd_finder.services.cache_paths import (
    default_data_root,
    default_diagnostic_log_root,
)


_LOGGER_NAME = "xrd_finder.runtime"
_MAX_LOG_BYTES = 10 * 1024 * 1024
_KEEP_SESSION_LOGS = 10
_STOP = object()
_CORRELATION: ContextVar[str | None] = ContextVar("xrd_finder_correlation", default=None)
_CURRENT_SESSION: "DiagnosticSession | None" = None
_HOOK_LOCK = threading.RLock()
_ORIGINAL_SYS_HOOK: Any = None
_ORIGINAL_THREAD_HOOK: Any = None
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\r\n\t\"']+")
_POSIX_HOME_RE = re.compile(r"/(?:home|Users)/[^/\s]+/[^\r\n\t\"']+")


def _redact_path_match(match: re.Match[str]) -> str:
    raw = match.group(0).rstrip(".,:;)")
    suffix = match.group(0)[len(raw):]
    name = raw.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return f"<path>/{name}{suffix}"


def _redact_text(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", "\\n")
    text = _WINDOWS_PATH_RE.sub(_redact_path_match, text)
    text = _POSIX_HOME_RE.sub(_redact_path_match, text)
    return text.replace(" ", "_")


def _redact_message(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", "\\n")
    text = _WINDOWS_PATH_RE.sub(_redact_path_match, text)
    return _POSIX_HOME_RE.sub(_redact_path_match, text)


def safe_file_label(path: str | Path) -> str:
    return Path(path).name or "unknown"


def classify_source_path(path: str | Path) -> str:
    candidate = Path(path).expanduser()
    try:
        managed_root = default_data_root().expanduser().resolve(strict=False)
        resolved = candidate.resolve(strict=False)
        if resolved == managed_root or managed_root in resolved.parents:
            return "managed"
    except OSError:
        pass

    if os.name != "nt":
        return "local"
    try:
        import ctypes

        drive = candidate.drive
        if not drive:
            return "unknown"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
        return {
            2: "removable",
            3: "local",
            4: "network",
            5: "optical",
            6: "ramdisk",
        }.get(int(drive_type), "unknown")
    except Exception:
        return "unknown"


def _safe_fields(fields: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, Path) or key.endswith("_path") or key in {"path", "file"}:
            result["file" if key.endswith("_path") else key] = safe_file_label(value)
            result.setdefault("source", classify_source_path(value))
        elif isinstance(value, (str, int, float, bool)):
            result[key] = value
        else:
            result[key] = repr(value)
    return result


def _format_fields(fields: dict[str, object]) -> str:
    return " ".join(f"{key}={_redact_text(value)}" for key, value in fields.items())


class _CappedFileWriter:
    def __init__(self, path: Path, max_bytes: int) -> None:
        self.path = path
        self.max_bytes = max(1024, int(max_bytes))
        self._stream = path.open("a", encoding="utf-8", newline="\n")
        self._bytes = path.stat().st_size if path.exists() else 0
        self._truncated = False

    def write(self, text: str) -> None:
        if self._truncated:
            return
        payload = text.encode("utf-8", errors="replace")
        if self._bytes + len(payload) > self.max_bytes:
            marker = "diagnostic_log_truncated=true\n".encode("utf-8")
            remaining = max(0, self.max_bytes - self._bytes)
            if remaining:
                self._stream.buffer.write(marker[:remaining])
                self._stream.flush()
            self._truncated = True
            return
        self._stream.write(text)
        self._stream.flush()
        self._bytes += len(payload)

    def close(self) -> None:
        self._stream.close()


class _QueueWriter(threading.Thread):
    def __init__(self, queue: SimpleQueue[object], writer: _CappedFileWriter) -> None:
        super().__init__(name="xrd-diagnostics-writer", daemon=True)
        self._queue = queue
        self._writer = writer

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                break
            if isinstance(item, logging.LogRecord):
                self._writer.write(_record_to_line(item))
        self._writer.close()


def _record_to_line(record: logging.LogRecord) -> str:
    timestamp = datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds")
    message = record.getMessage()
    if record.exc_info:
        message += " traceback=" + "".join(traceback.format_exception(*record.exc_info))
    return f"{timestamp} level={record.levelname} {_redact_message(message)}\n"


@dataclass(slots=True)
class DiagnosticSession:
    path: Path
    logger: logging.Logger
    queue: SimpleQueue[object]
    writer: _QueueWriter
    slow_ms: float
    _stopped: bool = False

    def stop(self, timeout: float = 1.0) -> None:
        global _CURRENT_SESSION
        if self._stopped:
            return
        self._stopped = True
        self.logger.handlers.clear()
        self.queue.put(_STOP)
        self.writer.join(max(0.0, timeout))
        if _CURRENT_SESSION is self:
            _CURRENT_SESSION = None


def _rotate_session_logs(root: Path) -> None:
    logs = sorted(
        (path for path in root.glob("xrd_finder-*.log") if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for path in logs[_KEEP_SESSION_LOGS - 1:]:
        try:
            path.unlink()
        except OSError:
            continue


def configure_diagnostics(
    app_version: str,
    log_dir: Path | None = None,
    slow_ms: float = 300.0,
) -> DiagnosticSession:
    global _CURRENT_SESSION
    if _CURRENT_SESSION is not None:
        _CURRENT_SESSION.stop(timeout=1.0)

    root = Path(log_dir) if log_dir is not None else default_diagnostic_log_root()
    root.mkdir(parents=True, exist_ok=True)
    _rotate_session_logs(root)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = root / f"xrd_finder-{stamp}-{os.getpid()}.log"
    queue: SimpleQueue[object] = SimpleQueue()
    writer = _QueueWriter(queue, _CappedFileWriter(path, _MAX_LOG_BYTES))
    logger = logging.getLogger(_LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(QueueHandler(queue))
    session = DiagnosticSession(path, logger, queue, writer, float(slow_ms))
    _CURRENT_SESSION = session
    writer.start()
    logger.info(
        "event=session_start version=%s python=%s os=%s architecture=%s pid=%s",
        app_version,
        platform.python_version(),
        platform.platform(),
        platform.machine(),
        os.getpid(),
    )
    return session


def diagnostic_logger() -> logging.Logger:
    if _CURRENT_SESSION is not None:
        return _CURRENT_SESSION.logger
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


class _OperationTrace(AbstractContextManager[None]):
    def __init__(self, name: str, fields: dict[str, object]) -> None:
        self.name = name
        self.slow_ms = float(fields.pop("slow_ms", _CURRENT_SESSION.slow_ms if _CURRENT_SESSION else 300.0))
        self.fields = _safe_fields(fields)
        self.started = 0.0
        self.correlation = ""
        self._token: Token[str | None] | None = None

    def __enter__(self) -> None:
        current = _CORRELATION.get()
        self.correlation = current or uuid4().hex[:12]
        if current is None:
            self._token = _CORRELATION.set(self.correlation)
        self.started = time.perf_counter()
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        elapsed_ms = (time.perf_counter() - self.started) * 1000.0
        fields = {
            "event": "operation",
            "operation": self.name,
            "status": "failed" if exc_type else "ok",
            "elapsed_ms": f"{elapsed_ms:.1f}",
            "correlation": self.correlation,
            **self.fields,
        }
        try:
            if exc_type is not None:
                diagnostic_logger().error(_format_fields(fields), exc_info=(exc_type, exc_value, exc_tb))
            elif elapsed_ms >= self.slow_ms:
                diagnostic_logger().info(_format_fields(fields))
        finally:
            if self._token is not None:
                _CORRELATION.reset(self._token)
        return False


def trace_operation(name: str, **fields: object) -> AbstractContextManager[None]:
    return _OperationTrace(name, fields)


def traced_operation(name: str):
    """Time a method boundary without changing its public signature."""

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            fields: dict[str, object] = {}
            owner = args[0] if args else None
            project = getattr(owner, "project", None)
            if project is not None:
                fields["patterns"] = len(getattr(project, "patterns", ()) or ())
                fields["phases"] = len(getattr(project, "phases", ()) or ())
            with trace_operation(name, **fields):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def install_exception_hooks() -> None:
    global _ORIGINAL_SYS_HOOK, _ORIGINAL_THREAD_HOOK
    with _HOOK_LOCK:
        if _ORIGINAL_SYS_HOOK is not None:
            return
        _ORIGINAL_SYS_HOOK = sys.excepthook
        _ORIGINAL_THREAD_HOOK = threading.excepthook

        def sys_hook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType) -> None:
            diagnostic_logger().critical(
                "event=uncaught_exception thread=main",
                exc_info=(exc_type, exc_value, exc_tb),
            )

        def thread_hook(args: threading.ExceptHookArgs) -> None:
            diagnostic_logger().critical(
                "event=uncaught_exception thread=%s",
                getattr(args.thread, "name", "unknown"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook


def restore_exception_hooks() -> None:
    global _ORIGINAL_SYS_HOOK, _ORIGINAL_THREAD_HOOK
    with _HOOK_LOCK:
        if _ORIGINAL_SYS_HOOK is None:
            return
        sys.excepthook = _ORIGINAL_SYS_HOOK
        threading.excepthook = _ORIGINAL_THREAD_HOOK
        _ORIGINAL_SYS_HOOK = None
        _ORIGINAL_THREAD_HOOK = None
