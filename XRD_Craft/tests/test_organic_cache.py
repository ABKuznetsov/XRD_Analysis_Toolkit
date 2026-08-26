from __future__ import annotations

from crystal_viewer.analysis.organic.cache import OrganicAnalysisCache, organic_cache_key
from crystal_viewer.analysis.organic.pipeline import iter_analyze_organic
from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _structure() -> CrystalStructure:
    sites = [
        AtomSite("C1", "C", (0.10, 0.50, 0.50)),
        AtomSite("C2", "C", (0.24, 0.50, 0.50)),
        AtomSite("O1", "O", (0.38, 0.50, 0.50)),
    ]
    return CrystalStructure("cached organic", UnitCell(10, 10, 10), sites, sites)


def test_organic_cache_round_trip_and_corruption_recovery(tmp_path) -> None:
    structure = _structure()
    settings = StructuralAnalysisSettings()
    key = organic_cache_key(structure, settings)
    report = tuple(iter_analyze_organic(structure, settings))[-1].report
    cache = OrganicAnalysisCache(tmp_path / "organic")

    cache.put(key, report)
    assert cache.get(key) == report

    cache._path(key).write_bytes(b"not a pickle")
    assert cache.get(key) is None
    assert not cache._path(key).exists()


def test_organic_cache_key_changes_with_structure_or_settings() -> None:
    structure = _structure()
    moved_sites = list(structure.sites)
    moved_sites[0] = AtomSite("C1", "C", (0.11, 0.50, 0.50))
    moved = CrystalStructure("cached organic", structure.cell, moved_sites, moved_sites)

    assert organic_cache_key(structure, StructuralAnalysisSettings()) != organic_cache_key(
        moved, StructuralAnalysisSettings()
    )
