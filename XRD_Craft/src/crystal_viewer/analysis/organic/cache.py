from __future__ import annotations

import hashlib
import importlib.metadata
import os
import pickle
import tempfile
from pathlib import Path

from crystal_viewer.analysis.organic.pipeline import OrganicAnalysisReport
from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings
from crystal_viewer.core.model import CrystalStructure


ORGANIC_CACHE_SCHEMA = "organic-analysis-cache-v1"


def _dependency_versions() -> tuple[tuple[str, str], ...]:
    versions = []
    for package in ("numpy", "networkx", "pymatgen"):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = "missing"
        versions.append((package, version))
    return tuple(versions)


def organic_cache_key(
    structure: CrystalStructure,
    settings: StructuralAnalysisSettings,
) -> str:
    payload = (
        ORGANIC_CACHE_SCHEMA,
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


class OrganicAnalysisCache:
    def __init__(self, directory: str | Path, *, maximum_entries: int = 32) -> None:
        if maximum_entries < 1:
            raise ValueError("maximum_entries must be positive")
        self.directory = Path(directory)
        self.maximum_entries = maximum_entries

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("cache key must be a lowercase SHA-256 digest")
        return self.directory / f"{key}.pickle"

    def get(self, key: str) -> OrganicAnalysisReport | None:
        path = self._path(key)
        try:
            value = pickle.loads(path.read_bytes())
            if not isinstance(value, OrganicAnalysisReport) or not value.complete:
                raise TypeError("unexpected or incomplete cache payload")
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

    def put(self, key: str, value: OrganicAnalysisReport) -> None:
        if not isinstance(value, OrganicAnalysisReport) or not value.complete:
            raise ValueError("only complete organic reports may be cached")
        path = self._path(key)
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".organic-", dir=self.directory)
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


__all__ = ["OrganicAnalysisCache", "organic_cache_key"]
