from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir


def crystal_blocks_data_dir(*, base: str | Path | None = None) -> Path:
    """Return the portable per-user Sci data directory for CRAFT."""
    sci_root = Path(base) / "Sci" if base is not None else Path(user_data_dir("Sci", appauthor=False))
    return sci_root / "craft"


def crystal_blocks_presets_dir(*, base: str | Path | None = None) -> Path:
    """User-authored knowledge lives outside disposable computed caches."""
    return crystal_blocks_data_dir(base=base) / "presets"


def crystal_blocks_knowledge_index(*, base: str | Path | None = None) -> Path:
    """Return the rebuildable index of user-authored structural knowledge."""
    return crystal_blocks_data_dir(base=base) / "knowledge-index.json"


__all__ = [
    "crystal_blocks_data_dir",
    "crystal_blocks_knowledge_index",
    "crystal_blocks_presets_dir",
]
