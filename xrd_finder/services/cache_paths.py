from __future__ import annotations

import os
from pathlib import Path
import sys


APP_DATA_ENV = "XRD_FINDER_DATA_DIR"
LOG_DIR_ENV = "XRD_FINDER_LOG_DIR"
APP_DATA_DIR_NAME = "data"


def default_data_root() -> Path:
    env_path = os.environ.get(APP_DATA_ENV)
    if env_path:
        return Path(env_path).expanduser()

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local_app_data:
            return Path(local_app_data) / "Sci" / "apps" / "xrd_phase_finder" / APP_DATA_DIR_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "XRD Phase Finder" / APP_DATA_DIR_NAME

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "xrd_phase_finder" / APP_DATA_DIR_NAME
    if sys.platform.startswith("linux"):
        return Path.home() / ".local" / "share" / "xrd_phase_finder" / APP_DATA_DIR_NAME

    return Path(__file__).resolve().parents[2] / APP_DATA_DIR_NAME


def default_phase_cache_root() -> Path:
    return default_data_root() / "cod_cache"


def default_diagnostic_log_root() -> Path:
    env_path = os.environ.get(LOG_DIR_ENV)
    if env_path:
        return Path(env_path).expanduser()
    return default_data_root().parent / "logs"


def default_xrd_import_root() -> Path:
    return default_data_root() / "imports" / "xrd"


def default_instrument_profile_library_path() -> Path:
    return default_data_root() / "settings" / "instrument_profiles.json"
