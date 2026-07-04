from __future__ import annotations

import os
from pathlib import Path


APP_DATA_ENV = "XRD_FINDER_DATA_DIR"
APP_DATA_DIR_NAME = "data"


def default_data_root() -> Path:
    env_path = os.environ.get(APP_DATA_ENV)
    if env_path:
        return Path(env_path).expanduser()

    return Path(__file__).resolve().parents[2] / APP_DATA_DIR_NAME


def default_phase_cache_root() -> Path:
    return default_data_root() / "cod_cache"
