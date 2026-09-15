from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from xrd_finder.services.cache_paths import default_data_root


OFFLINE_ENV = "XRD_FINDER_OFFLINE"
SECURITY_SETTINGS_RELATIVE = Path("settings") / "security.json"


def env_offline_mode_enabled() -> bool:
    return _env_flag(OFFLINE_ENV)


def security_settings_path(data_root: str | Path | None = None) -> Path:
    root = Path(data_root).expanduser() if data_root is not None else default_data_root()
    return root / SECURITY_SETTINGS_RELATIVE


def saved_offline_mode_enabled(data_root: str | Path | None = None) -> bool:
    payload = read_security_settings(data_root)
    return bool(payload.get("offline_mode"))


def offline_mode_enabled(data_root: str | Path | None = None) -> bool:
    return env_offline_mode_enabled() or saved_offline_mode_enabled(data_root)


def set_saved_offline_mode_enabled(enabled: bool, data_root: str | Path | None = None) -> Path:
    path = security_settings_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = read_security_settings(data_root)
    payload.update(
        {
            "schema": 1,
            "offline_mode": bool(enabled),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_security_settings(data_root: str | Path | None = None) -> dict[str, Any]:
    path = security_settings_path(data_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}
