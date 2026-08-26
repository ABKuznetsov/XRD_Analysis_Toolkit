from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from crystal_viewer.analysis.structural_analysis import (
    StructuralAnalysisSettings,
    analyze_structure,
)
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.document import load_document


ROOT = Path(__file__).resolve().parents[1]


def test_structural_analysis_is_immutable_and_contains_periodic_bonds() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")

    result = analyze_structure(structure)

    assert len(result.periodic_bonds.bonds) == 8
    assert len(result.polyhedron_roles) == 2
    assert {item.role for item in result.polyhedron_roles} == {"structural"}
    assert all(item.mean_bond_valence >= 0.45 for item in result.polyhedron_roles)
    assert result.settings == StructuralAnalysisSettings()
    assert result.complete is True
    assert result.exact is True
    with pytest.raises(FrozenInstanceError):
        result.complete = False  # type: ignore[misc]


@pytest.mark.parametrize(
    "settings",
    (
        StructuralAnalysisSettings(maximum_ring_size=2),
        StructuralAnalysisSettings(maximum_states=0),
        StructuralAnalysisSettings(maximum_seconds=0.0),
    ),
)
def test_structural_analysis_settings_reject_invalid_limits(settings: StructuralAnalysisSettings) -> None:
    with pytest.raises(ValueError):
        settings.validate()


def test_loaded_document_retains_one_shared_structural_analysis_bundle() -> None:
    document = load_document(ROOT / "examples" / "hinged_silicate.cif")

    assert document.structural_analysis is not None
    assert len(document.structural_analysis.periodic_bonds.bonds) == 8
    assert document.content_identity() == document.content_identity()
