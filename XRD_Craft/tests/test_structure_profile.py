from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from crystal_viewer.analysis.structure_profile import (
    ProfileConfidence,
    ProfileDecision,
    ProfileSettings,
    RequestedProfile,
    ResolvedProfile,
    resolve_structure_profile,
)
from crystal_viewer.analysis.periodic_bonds import PeriodicBond, PeriodicBondResult
from crystal_viewer.analysis.organic.bond_layers import build_bond_layers
from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _edge(first: int, second: int, image: tuple[int, int, int] = (0, 0, 0)) -> PeriodicBond:
    return PeriodicBond(first, second, image, 1.5, 1.0, "test", 1.0)


def _profile_case(name: str):
    if name == "carbonate":
        sites = [
            AtomSite("C1", "C", (0.5, 0.5, 0.5)),
            AtomSite("O1", "O", (0.6, 0.5, 0.5)),
            AtomSite("O2", "O", (0.45, 0.59, 0.5)),
            AtomSite("O3", "O", (0.45, 0.41, 0.5)),
            AtomSite("Ca1", "Ca", (0.0, 0.0, 0.0)),
        ]
        covalent = (_edge(0, 1), _edge(0, 2), _edge(0, 3))
        coordination = (_edge(4, 1),)
        rejected = ()
    elif name == "finite_organic":
        sites = [
            AtomSite("C1", "C", (0.2, 0.5, 0.5)),
            AtomSite("C2", "C", (0.35, 0.5, 0.5)),
            AtomSite("O1", "O", (0.5, 0.5, 0.5)),
        ]
        covalent = (_edge(0, 1), _edge(1, 2))
        coordination = ()
        rejected = ()
    elif name == "reticular_bridge":
        sites = [
            AtomSite("Zn1", "Zn", (0.0, 0.5, 0.5)),
            AtomSite("Zn2", "Zn", (0.8, 0.5, 0.5)),
            AtomSite("C1", "C", (0.3, 0.5, 0.5)),
            AtomSite("C2", "C", (0.5, 0.5, 0.5)),
            AtomSite("O1", "O", (0.15, 0.5, 0.5)),
            AtomSite("O2", "O", (0.65, 0.5, 0.5)),
        ]
        covalent = (_edge(4, 2), _edge(2, 3), _edge(3, 5))
        coordination = (_edge(0, 4), _edge(0, 4, (1, 0, 0)), _edge(1, 5))
        rejected = ()
    elif name == "ambiguous_mixed":
        sites = [
            AtomSite("C1", "C", (0.1, 0.2, 0.2)),
            AtomSite("C2", "C", (0.2, 0.2, 0.2)),
            AtomSite("Si1", "Si", (0.5, 0.5, 0.5)),
            AtomSite("O1", "O", (0.6, 0.5, 0.5)),
        ]
        covalent = (_edge(0, 1), _edge(2, 3), _edge(2, 3, (1, 0, 0)))
        coordination = ()
        rejected = (_edge(1, 3),)
    else:  # pragma: no cover - test helper contract
        raise KeyError(name)
    structure = CrystalStructure(name, UnitCell(10.0, 10.0, 10.0), sites, sites)
    periodic = PeriodicBondResult(covalent + coordination + rejected, True)
    layers = SimpleNamespace(covalent=covalent, coordination=coordination, rejected=rejected)
    return structure, periodic, layers


def test_auto_profile_is_the_default_and_manual_values_validate() -> None:
    settings = StructuralAnalysisSettings()

    assert settings.profile.requested is RequestedProfile.AUTO
    ProfileSettings(RequestedProfile.ORGANIC_METAL_ORGANIC).validate()


def test_profile_decision_requires_reasons_and_bounded_score() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ProfileDecision(ResolvedProfile.MOLECULAR, 1.2, ("finite molecule",))
    with pytest.raises(ValueError, match="requires evidence"):
        ProfileDecision(ResolvedProfile.MOLECULAR, 0.8, ())


def test_profile_decision_is_immutable_and_maps_confidence() -> None:
    high = ProfileDecision(ResolvedProfile.MOLECULAR, 0.8, ("finite molecule",))
    medium = ProfileDecision(ResolvedProfile.MOLECULAR, 0.55, ("finite molecule",))
    low = ProfileDecision(ResolvedProfile.INORGANIC, 0.54, ("mixed evidence",))

    assert high.confidence is ProfileConfidence.HIGH
    assert medium.confidence is ProfileConfidence.MEDIUM
    assert low.confidence is ProfileConfidence.LOW
    with pytest.raises(FrozenInstanceError):
        high.score = 0.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("carbonate", ResolvedProfile.INORGANIC),
        ("finite_organic", ResolvedProfile.MOLECULAR),
        ("reticular_bridge", ResolvedProfile.RETICULAR),
    ],
)
def test_auto_profile_uses_periodic_graph_evidence(case: str, expected: ResolvedProfile) -> None:
    decision = resolve_structure_profile(*_profile_case(case))

    assert decision.resolved is expected
    assert decision.reasons


def test_manual_inorganic_override_keeps_conflicting_evidence_warning() -> None:
    structure, periodic, layers = _profile_case("reticular_bridge")

    decision = resolve_structure_profile(
        structure,
        periodic,
        layers,
        requested=RequestedProfile.INORGANIC,
    )

    assert decision.resolved is ResolvedProfile.INORGANIC
    assert any("override" in warning.lower() for warning in decision.warnings)


def test_ambiguous_mixed_structure_reports_low_confidence_and_reasons() -> None:
    decision = resolve_structure_profile(*_profile_case("ambiguous_mixed"))

    assert decision.confidence is ProfileConfidence.LOW
    assert any("unresolved" in reason.lower() for reason in decision.reasons)


def test_profile_accepts_production_chemical_bond_layers() -> None:
    structure, periodic, _layers = _profile_case("reticular_bridge")

    decision = resolve_structure_profile(
        structure,
        periodic,
        build_bond_layers(structure, periodic),
    )

    assert decision.resolved is ResolvedProfile.RETICULAR
