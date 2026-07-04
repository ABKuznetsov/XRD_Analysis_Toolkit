from __future__ import annotations

from pathlib import Path


def ensure_export_dir(project_root: str | Path) -> Path:
    export_dir = Path(project_root) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir
