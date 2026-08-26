from __future__ import annotations

import hashlib
import importlib.metadata
import os
import pickle
import tempfile
from pathlib import Path
from typing import Callable

from crystal_viewer.analysis.structural_analysis import (
    StructuralAnalysis,
    StructuralAnalysisSettings,
)
from crystal_viewer.core.app_paths import crystal_blocks_data_dir
from crystal_viewer.core.model import CrystalStructure


STRUCTURAL_CACHE_SCHEMA = "structural-analysis-cache-v12"


def _dependency_versions() -> tuple[tuple[str, str], ...]:
    versions = []
    for package in ("numpy", "networkx", "pymatgen"):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = "missing"
        versions.append((package, version))
    return tuple(versions)


def structural_cache_key(
    structure: CrystalStructure,
    settings: StructuralAnalysisSettings,
) -> str:
    payload = (
        STRUCTURAL_CACHE_SCHEMA,
        _dependency_versions(),
        settings,
        structure.cell,
        tuple(structure.asymmetric_sites),
        tuple(structure.sites),
        tuple(structure.symmetry_operations),
        structure.formula,
        structure.space_group,
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


class StructuralAnalysisCache:
    def __init__(self, directory: str | Path, *, maximum_entries: int = 32) -> None:
        if maximum_entries < 1:
            raise ValueError("maximum_entries must be positive")
        self.directory = Path(directory)
        self.maximum_entries = maximum_entries

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("cache key must be a lowercase SHA-256 digest")
        return self.directory / f"{key}.pickle"

    def get(self, key: str) -> StructuralAnalysis | None:
        path = self._path(key)
        try:
            value = pickle.loads(path.read_bytes())
            if not isinstance(value, StructuralAnalysis):
                raise TypeError("unexpected cache payload")
            os.utime(path, None)
            return value
        except FileNotFoundError:
            return None
        except Exception:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return None

    def put(self, key: str, value: StructuralAnalysis) -> None:
        path = self._path(key)
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".structural-", dir=self.directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        entries = sorted(
            self.directory.glob("*.pickle"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
        )
        for stale in entries[: max(0, len(entries) - self.maximum_entries)]:
            stale.unlink()


def cached_analyze_structure(
    structure: CrystalStructure,
    settings: StructuralAnalysisSettings | None = None,
    *,
    cache: StructuralAnalysisCache | None = None,
    compute: Callable[[CrystalStructure, StructuralAnalysisSettings], StructuralAnalysis] | None = None,
) -> StructuralAnalysis:
    settings = settings or StructuralAnalysisSettings()
    settings.validate()
    cache = cache or StructuralAnalysisCache(crystal_blocks_data_dir() / "cache" / "structural")
    key = structural_cache_key(structure, settings)
    try:
        cached = cache.get(key)
    except OSError:
        cached = None
    if cached is not None:
        return cached
    if compute is None:
        from crystal_viewer.analysis.structural_analysis import analyze_structure

        compute = analyze_structure
    result = compute(structure, settings)
    try:
        cache.put(key, result)
    except OSError:
        # Read-only installations and locked profiles must still be usable;
        # persistence is an optimization, never a scientific requirement.
        pass
    return result


__all__ = ["StructuralAnalysisCache", "cached_analyze_structure", "structural_cache_key"]
