from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crystal_viewer.analysis.comparison import compare_documents
from crystal_viewer.analysis.descriptors.builders import build_descriptors
from crystal_viewer.analysis.motif_graph import build_motif_graph
from crystal_viewer.core.document import load_document
from crystal_viewer.ui.main_window import MainWindow


NA6_PATH = Path(
    "/Users/artem/Yandex.Disk.localized/paper/Мои публикации/Финальные версии статей/2024/"
    "Na6Mo11O36_Cz/структура/Na6Mo11O36_monoclinic.cif"
)
NALI_PATH = Path(
    "/Users/artem/Yandex.Disk.localized/paper/Мои публикации/Финальные версии статей/2026/"
    "Li-Na/NaLiMoO_romb.cif"
)


@pytest.mark.skipif(
    not NA6_PATH.exists() or not NALI_PATH.exists(),
    reason="User molybdate CIFs are not mounted",
)
def test_molybdates_load_and_expose_mo_o_descriptors() -> None:
    documents = tuple(load_document(path) for path in (NA6_PATH, NALI_PATH))

    for document in documents:
        descriptors = build_descriptors(document)
        assert descriptors["mo_o.d6_minus_d5"].value.count > 0
        assert document.periodic_graph is not None
    report = compare_documents(documents)
    assert report.row("mo_o.d6_minus_d5").expanded_records


@pytest.mark.skipif(
    not NA6_PATH.exists() or not NALI_PATH.exists(),
    reason="User molybdate CIFs are not mounted",
)
def test_application_limits_reach_a_real_match_beyond_the_old_96_node_graph_limit() -> None:
    documents = tuple(load_document(path) for path in (NA6_PATH, NALI_PATH))
    assert len(build_motif_graph(documents[1]).nodes) == 120
    state = SimpleNamespace()

    bundle = MainWindow._comparison_bundle(state, documents)
    reused = MainWindow._comparison_bundle(state, documents)
    report, motif_report = bundle

    assert reused is bundle
    assert motif_report.graph_complete is True
    assert "max_nodes" not in motif_report.limit_reasons
    assert motif_report.matches
    assert motif_report.exact is (
        not motif_report.approximate and not motif_report.ambiguous
    )
    if motif_report.approximate:
        assert any("approximate" in warning.lower() for warning in report.warnings)
    if motif_report.ambiguous:
        assert any("ambiguous" in warning.lower() for warning in report.warnings)
