from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from toolkit import launch_xrd_finder_preview_macos as preview


def test_fetch_url_bytes_converts_curl_failure_to_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_urlopen(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(preview, "urlopen", fail_urlopen)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=6,
            stdout=b"",
            stderr=b"Could not resolve host",
        ),
    )

    with pytest.raises(URLError, match="Could not resolve host"):
        preview.fetch_url_bytes("https://example.invalid/update.json", timeout=1)


def test_update_check_continues_when_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "apps": {
                    preview.APP_ID: {
                        "update_manifest_url": "https://example.invalid/update.json",
                        "release_url": "https://example.invalid/release",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    statuses: list[tuple[int, str, str, str]] = []
    app = SimpleNamespace(
        local_version="1.2.0",
        manifest_path=manifest_path,
        update_root=tmp_path / "updates",
        set_step=lambda index, status, detail="", tone="blue": statuses.append(
            (index, status, detail, tone)
        ),
    )
    app.update_root.mkdir()
    monkeypatch.setattr(
        preview,
        "fetch_json",
        lambda url: (_ for _ in ()).throw(URLError("offline")),
    )

    assert preview.PreviewApp.check_updates(app) is False
    assert statuses[-1][1] == "Offline"
    assert "continuing" in statuses[-1][2]


def test_runtime_probe_reports_failed_import(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="ImportError: incompatible architecture",
        ),
    )

    ready, detail = preview.runtime_is_usable(python)

    assert ready is False
    assert detail == "ImportError: incompatible architecture"
