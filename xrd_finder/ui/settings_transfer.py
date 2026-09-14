from __future__ import annotations

from base64 import b64decode, b64encode
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray

from xrd_finder import __version__
from xrd_finder.instrument.library import InstrumentProfileLibrary
from xrd_finder.services.cache_paths import default_instrument_profile_library_path
from xrd_finder.ui.app_settings import app_settings


SETTINGS_BUNDLE_SCHEMA_VERSION = 1


def export_user_settings_bundle(path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = app_settings()
    payload: dict[str, Any] = {
        "schema_version": SETTINGS_BUNDLE_SCHEMA_VERSION,
        "application": "XRD Phase Finder",
        "application_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "qt_settings": {
            key: _serialize_qsettings_value(settings.value(key))
            for key in sorted(settings.allKeys())
        },
        "instrument_profiles": _read_instrument_profiles_payload(),
    }
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def import_user_settings_bundle(path: Path | str) -> None:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SETTINGS_BUNDLE_SCHEMA_VERSION:
        raise ValueError("Unsupported settings bundle format")

    raw_settings = payload.get("qt_settings")
    if not isinstance(raw_settings, dict):
        raise ValueError("Settings bundle does not contain Qt settings")
    settings = app_settings()
    settings.clear()
    for key, encoded in raw_settings.items():
        if not isinstance(key, str):
            continue
        settings.setValue(key, _deserialize_qsettings_value(encoded))
    settings.sync()

    profiles_payload = payload.get("instrument_profiles")
    if profiles_payload is not None:
        _write_instrument_profiles_payload(profiles_payload)


def _serialize_qsettings_value(value: Any) -> dict[str, Any]:
    if isinstance(value, QByteArray):
        return {
            "type": "qbytearray",
            "value": bytes(value.toBase64()).decode("ascii"),
        }
    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "value": b64encode(value).decode("ascii"),
        }
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if value is None:
        return {"type": "none", "value": None}
    return {"type": "str", "value": str(value)}


def _deserialize_qsettings_value(encoded: Any) -> Any:
    if not isinstance(encoded, dict):
        return str(encoded)
    value_type = str(encoded.get("type") or "str")
    value = encoded.get("value")
    if value_type == "qbytearray":
        return QByteArray.fromBase64(QByteArray(str(value or "").encode("ascii")))
    if value_type == "bytes":
        return b64decode(str(value or "").encode("ascii"))
    if value_type == "bool":
        return bool(value)
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "none":
        return None
    return str(value or "")


def _read_instrument_profiles_payload() -> dict[str, Any]:
    library_path = default_instrument_profile_library_path()
    if library_path.is_file():
        try:
            payload = json.loads(library_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    library = InstrumentProfileLibrary(library_path)
    return {
        "schema_version": 1,
        "profiles": [profile.to_dict() for profile in library.list_profiles()],
    }


def _write_instrument_profiles_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Settings bundle contains invalid instrument profiles")
    library_path = default_instrument_profile_library_path()
    library_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = library_path.with_suffix(library_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(library_path)
    InstrumentProfileLibrary(library_path)
