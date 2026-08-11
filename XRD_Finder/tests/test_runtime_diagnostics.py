from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

from xrd_finder.services.runtime_diagnostics import (
    configure_diagnostics,
    install_exception_hooks,
    restore_exception_hooks,
    trace_operation,
)


class RuntimeDiagnosticsTests(unittest.TestCase):
    def tearDown(self) -> None:
        restore_exception_hooks()

    def test_slow_and_failed_operations_are_logged_without_full_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = configure_diagnostics("test", root, slow_ms=0.0)
            private_path = root / "private" / "sample.xy"
            with trace_operation("plot.observed", file_path=private_path, patterns=2):
                pass
            with self.assertRaisesRegex(RuntimeError, "broken"):
                with trace_operation("gain.rank", slow_ms=10_000.0):
                    raise RuntimeError("broken")
            session.stop(timeout=1.0)

            text = session.path.read_text(encoding="utf-8")
            self.assertIn("operation=plot.observed", text)
            self.assertIn("operation=gain.rank", text)
            self.assertIn("status=failed", text)
            self.assertIn("file=sample.xy", text)
            self.assertNotIn(str(root), text)

    def test_fast_success_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = configure_diagnostics("test", Path(directory), slow_ms=10_000.0)
            with trace_operation("fast.operation"):
                pass
            session.stop(timeout=1.0)
            self.assertNotIn("fast.operation", session.path.read_text(encoding="utf-8"))

    def test_rotation_only_removes_old_session_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(12):
                path = root / f"xrd_finder-20260101-0000{index:02d}-old.log"
                path.write_text("old", encoding="utf-8")
            (root / "setup.log").write_text("keep", encoding="utf-8")

            session = configure_diagnostics("test", root)
            session.stop(timeout=1.0)

            self.assertLessEqual(len(list(root.glob("xrd_finder-*.log"))), 10)
            self.assertTrue((root / "setup.log").exists())

    def test_nested_operations_share_a_correlation_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = configure_diagnostics("test", Path(directory), slow_ms=0.0)
            with trace_operation("outer"):
                with trace_operation("inner"):
                    pass
            session.stop(timeout=1.0)
            lines = [
                line for line in session.path.read_text(encoding="utf-8").splitlines()
                if "event=operation" in line
            ]
            correlations = {
                token.split("=", 1)[1]
                for line in lines
                for token in line.split()
                if token.startswith("correlation=")
            }
            self.assertEqual(len(correlations), 1)

    def test_uncaught_exception_hooks_write_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = configure_diagnostics("test", Path(directory), slow_ms=0.0)
            install_exception_hooks()
            try:
                raise RuntimeError("main hook failure")
            except RuntimeError:
                exc_type, exc_value, exc_tb = sys.exc_info()
                sys.excepthook(exc_type, exc_value, exc_tb)

            try:
                raise RuntimeError("thread hook failure")
            except RuntimeError:
                exc_type, exc_value, exc_tb = sys.exc_info()
                args = type(
                    "ExceptHookArgs",
                    (),
                    {
                        "exc_type": exc_type,
                        "exc_value": exc_value,
                        "exc_traceback": exc_tb,
                        "thread": threading.current_thread(),
                    },
                )()
                threading.excepthook(args)

            restore_exception_hooks()
            session.stop(timeout=1.0)
            text = session.path.read_text(encoding="utf-8")
            self.assertIn("event=uncaught_exception", text)
            self.assertIn("main hook failure", text)
            self.assertIn("thread hook failure", text)


if __name__ == "__main__":
    unittest.main()
