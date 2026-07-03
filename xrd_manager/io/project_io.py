from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from xrd_manager.core.project import Project


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    return value


def save_project_manifest(project: Project, path: str | Path) -> None:
    target = Path(path)
    target.write_text(json.dumps(_to_plain(project), indent=2), encoding="utf-8")

