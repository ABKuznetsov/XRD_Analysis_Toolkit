from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import sys
from typing import TextIO


_STARTUP_LOG_STREAM: TextIO | None = None


def configure_startup_logging() -> Path | None:
    """Redirect early startup diagnostics when a launcher provides a log path."""
    global _STARTUP_LOG_STREAM

    raw_path = os.environ.get("XRD_FINDER_STARTUP_LOG", "").strip()
    if not raw_path:
        return None

    log_path = Path(raw_path).expanduser()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("a", encoding="utf-8", buffering=1)
    except OSError:
        return None

    _STARTUP_LOG_STREAM = stream
    sys.stdout = stream
    sys.stderr = stream
    try:
        faulthandler.enable(stream)
    except (OSError, RuntimeError):
        pass
    print("\n=== XRD Phase Finder startup ===", flush=True)
    return log_path
