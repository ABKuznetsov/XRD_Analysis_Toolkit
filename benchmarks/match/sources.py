from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import urllib.request


@dataclass(frozen=True, slots=True)
class SourceSpec:
    source_id: str
    url: str
    sha256: str
    filename: str


def fetch_pinned_source(spec: SourceSpec, cache_dir: Path | str) -> Path:
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / spec.filename
    partial = root / f"{spec.filename}.part"
    if destination.exists() and _sha256(destination) == spec.sha256.lower():
        return destination
    destination.unlink(missing_ok=True)
    partial.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(spec.url, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        actual = _sha256(partial)
        if actual != spec.sha256.lower():
            raise ValueError(
                f"SHA-256 mismatch for {spec.source_id}: expected {spec.sha256.lower()}, got {actual}."
            )
        partial.replace(destination)
        return destination
    except Exception:
        partial.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["SourceSpec", "fetch_pinned_source"]
