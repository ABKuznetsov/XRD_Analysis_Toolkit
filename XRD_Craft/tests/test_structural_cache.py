from __future__ import annotations

from pathlib import Path

from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings, analyze_structure
from crystal_viewer.analysis.structural_cache import (
    StructuralAnalysisCache,
    cached_analyze_structure,
    structural_cache_key,
)
from crystal_viewer.core.app_paths import crystal_blocks_data_dir, crystal_blocks_presets_dir
from crystal_viewer.core.cif import load_cif


ROOT = Path(__file__).resolve().parents[1]


def test_portable_data_layout_keeps_cache_separate_from_user_presets(tmp_path: Path) -> None:
    data = crystal_blocks_data_dir(base=tmp_path)

    assert data == tmp_path / "Sci" / "craft"
    assert crystal_blocks_presets_dir(base=tmp_path) == data / "presets"


def test_structural_cache_round_trip_recovers_from_corruption_and_evicts(tmp_path: Path) -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    settings = StructuralAnalysisSettings(maximum_seconds=20.0)
    result = analyze_structure(structure, settings)
    cache = StructuralAnalysisCache(tmp_path / "cache", maximum_entries=2)
    first_key = structural_cache_key(structure, settings)

    cache.put(first_key, result)
    assert cache.get(first_key) == result
    (tmp_path / "cache" / f"{first_key}.pickle").write_bytes(b"broken")
    assert cache.get(first_key) is None

    for suffix in range(3):
        cache.put(f"{'a' * 63}{suffix}", result)
    assert len(list((tmp_path / "cache").glob("*.pickle"))) == 2


def test_structural_cache_key_changes_with_settings() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")

    assert structural_cache_key(structure, StructuralAnalysisSettings()) != structural_cache_key(
        structure,
        StructuralAnalysisSettings(maximum_ring_size=8),
    )


def test_cached_analysis_does_not_recompute_the_same_structure(tmp_path: Path) -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    cache = StructuralAnalysisCache(tmp_path / "cache")
    calls = 0

    def compute(source, settings):
        nonlocal calls
        calls += 1
        return analyze_structure(source, settings)

    first = cached_analyze_structure(structure, cache=cache, compute=compute)
    second = cached_analyze_structure(structure, cache=cache, compute=compute)

    assert second == first
    assert calls == 1
