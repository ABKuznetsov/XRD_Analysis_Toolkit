from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import gettempdir


def capture_analysis_preview(
    image,
    *,
    project_id: str,
    pattern_id: str,
    cache_root: str | Path | None = None,
) -> str | None:
    """Save a compact per-pattern image for later embedding into an XPFF file."""
    if image is None or image.isNull():
        return None
    root = Path(cache_root) if cache_root is not None else Path(gettempdir()) / "XRDPhaseFinder" / "previews"
    project_key = sha256(str(project_id).encode("utf-8")).hexdigest()[:16]
    pattern_key = sha256(str(pattern_id).encode("utf-8")).hexdigest()[:24]
    path = root / project_key / f"{pattern_key}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        return None
    return str(path)
