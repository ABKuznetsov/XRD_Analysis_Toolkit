from __future__ import annotations

from pathlib import Path

from crystal_viewer.analysis.structural_cache import StructuralAnalysisCache
from crystal_viewer.analysis.organic.cache import OrganicAnalysisCache
from crystal_viewer.core.progressive_load import LoadStage, iter_load_updates


DATA = Path(__file__).parent / "data" / "structures" / "lithium_triborate.cif"
ORGANIC_DATA = Path(__file__).parent / "data" / "organic" / "finite_molecule.cif"


def test_cif_load_emits_atoms_before_each_scientific_stage(tmp_path) -> None:
    updates = tuple(
        iter_load_updates(DATA, cache=StructuralAnalysisCache(tmp_path / "cache"))
    )

    assert [item.stage for item in updates] == [
        LoadStage.PARSED,
        LoadStage.BONDS,
        LoadStage.POLYHEDRA,
        LoadStage.UNITS,
        LoadStage.TOPOLOGY,
    ]
    assert updates[0].structure.asymmetric_sites
    assert updates[0].snapshot is None
    assert updates[-1].snapshot.structural_analysis is not None


def test_second_load_uses_complete_cache_after_parsed_preview(tmp_path) -> None:
    cache = StructuralAnalysisCache(tmp_path / "cache")
    tuple(iter_load_updates(DATA, cache=cache))

    updates = tuple(iter_load_updates(DATA, cache=cache))

    assert [item.stage for item in updates] == [LoadStage.PARSED, LoadStage.TOPOLOGY]


def test_organic_load_keeps_preview_then_delivers_incremental_reports(tmp_path) -> None:
    updates = tuple(
        iter_load_updates(
            ORGANIC_DATA,
            cache=StructuralAnalysisCache(tmp_path / "cache"),
        )
    )

    assert [item.stage for item in updates] == [
        LoadStage.PARSED,
        LoadStage.BONDS_PROFILE,
        LoadStage.COMPONENTS,
        LoadStage.CONTACTS,
        LoadStage.PACKING,
    ]
    assert updates[0].organic_bundle is None
    assert updates[1].organic_bundle.report.components is None
    assert updates[2].organic_bundle.report.components is not None
    assert updates[3].organic_bundle.report.packing is None
    assert updates[4].organic_bundle.report.complete


def test_second_organic_load_uses_final_report_cache_after_preview(tmp_path) -> None:
    structural_cache = StructuralAnalysisCache(tmp_path / "structural")
    organic_cache = OrganicAnalysisCache(tmp_path / "organic")
    tuple(
        iter_load_updates(
            ORGANIC_DATA, cache=structural_cache, organic_cache=organic_cache
        )
    )

    updates = tuple(
        iter_load_updates(
            ORGANIC_DATA, cache=structural_cache, organic_cache=organic_cache
        )
    )

    assert [item.stage for item in updates] == [LoadStage.PARSED, LoadStage.PACKING]
    assert updates[-1].organic_bundle.report.complete
    assert updates[-1].organic_bundle.report.packing is not None


def test_shelx_load_emits_the_atom_preview_before_background_analysis(tmp_path) -> None:
    source = tmp_path / "simple.res"
    source.write_text(
        "TITL simple\nCELL 0.71073 10 10 10 90 90 90\nLATT -1\n"
        "SFAC C O\nC1 1 0.1 0.2 0.3 11.0 0.05\n"
        "O1 2 0.2 0.2 0.3 11.0 0.05\nHKLF 4\nEND\n",
        encoding="utf-8",
    )

    first = next(iter_load_updates(source))

    assert first.stage is LoadStage.PARSED
    assert [site.element for site in first.structure.sites] == ["C", "O"]
