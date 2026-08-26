from __future__ import annotations

import time
import math
from pathlib import Path

from crystal_viewer.analysis.coordination import describe_coordination
from crystal_viewer.analysis.periodic_bonds import PeriodicBond, PeriodicBondResult, build_periodic_bonds
from crystal_viewer.analysis.structural_analysis import StructuralAnalysisSettings
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


ROOT = Path(__file__).resolve().parents[1]


def _nested_octahedral_shell(
    secondary_count: int,
) -> tuple[CrystalStructure, PeriodicBondResult]:
    centre = (0.5, 0.5, 0.5)
    primary = (
        (2.0, 0.0, 0.0), (-2.0, 0.0, 0.0),
        (0.0, 2.0, 0.0), (0.0, -2.0, 0.0),
        (0.0, 0.0, 2.0), (0.0, 0.0, -2.0),
    )
    scale = 2.6 / math.sqrt(2.0)
    secondary = (
        (scale, scale, 0.0), (-scale, -scale, 0.0),
        (scale, 0.0, scale), (-scale, 0.0, -scale),
        (0.0, scale, scale), (0.0, -scale, -scale),
    )[:secondary_count]
    vectors = (*primary, *secondary)
    sites = [AtomSite("K1", "K", centre)]
    sites.extend(
        AtomSite(
            f"O{index}",
            "O",
            tuple(centre[axis] + vector[axis] / 20.0 for axis in range(3)),
        )
        for index, vector in enumerate(vectors, start=1)
    )
    structure = CrystalStructure("nested shell", UnitCell(20, 20, 20), sites, sites)
    bonds = tuple(
        PeriodicBond(0, index, (0, 0, 0), 2.0, 1.0, "crystalnn", 1.0)
        for index in range(1, 7)
    )
    return structure, PeriodicBondResult(bonds, True)


class _EmptyGeometryFinder:
    def compute_coordination_environments(self, structure, **_kwargs):
        return [None] * len(structure)


def test_complete_secondary_anion_shell_is_preserved_as_six_plus_six() -> None:
    structure, bonds = _nested_octahedral_shell(6)

    environments = describe_coordination(
        structure,
        bonds,
        StructuralAnalysisSettings(),
        geometry_finder=_EmptyGeometryFinder(),
    )

    assert len(environments[0].neighbor_indices) == 12
    assert "secondary anion shell" in " ".join(environments[0].warnings).lower()


def test_incomplete_secondary_shell_does_not_expand_primary_coordination() -> None:
    structure, bonds = _nested_octahedral_shell(2)

    environments = describe_coordination(
        structure,
        bonds,
        StructuralAnalysisSettings(),
        geometry_finder=_EmptyGeometryFinder(),
    )

    assert len(environments[0].neighbor_indices) == 6


def _tetrahedron() -> tuple[CrystalStructure, PeriodicBondResult]:
    sites = [
        AtomSite("B1", "B", (0.5, 0.5, 0.5)),
        AtomSite("O1", "O", (0.6, 0.6, 0.6)),
        AtomSite("O2", "O", (0.4, 0.4, 0.6)),
        AtomSite("O3", "O", (0.4, 0.6, 0.4)),
        AtomSite("O4", "O", (0.6, 0.4, 0.4)),
    ]
    structure = CrystalStructure("tetrahedron", UnitCell(8.0, 8.0, 8.0), sites, sites)
    bonds = tuple(
        PeriodicBond(0, index, (0, 0, 0), 1.38564, 1.0, "crystalnn", 1.0)
        for index in range(1, 5)
    )
    return structure, PeriodicBondResult(bonds, True)


def test_chemenv_describes_real_silicate_without_changing_primary_membership() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")
    bonds = build_periodic_bonds(structure)

    environments = describe_coordination(structure, bonds, StructuralAnalysisSettings(maximum_seconds=20.0))

    silicon = [environment for environment in environments if environment.center_index in (0, 1)]
    assert len(silicon) == 2
    assert all(len(environment.neighbor_indices) == 4 for environment in silicon)
    assert all(environment.candidates[0].symbol == "T:4" for environment in silicon)
    assert all(environment.candidates[0].csm < 1.0 for environment in silicon)


def test_chemenv_disagreement_is_retained_as_ambiguity_not_a_fifth_primary_neighbor() -> None:
    structure, bonds = _tetrahedron()

    class FiveCoordinateFinder:
        def compute_coordination_environments(self, _structure, **_kwargs):
            return [
                [{"ce_symbol": "T:5", "ce_fraction": 1.0, "csm": 2.0}],
                None,
                None,
                None,
                None,
            ]

    environments = describe_coordination(
        structure,
        bonds,
        StructuralAnalysisSettings(),
        geometry_finder=FiveCoordinateFinder(),
    )

    center = environments[0]
    assert center.neighbor_indices == (1, 2, 3, 4)
    assert center.candidates[0].symbol == "T:5"
    assert center.ambiguous is True
    assert "disagrees" in " ".join(center.warnings).lower()


def test_chemenv_budget_overrun_marks_environment_incomplete_without_erasing_result() -> None:
    structure, bonds = _tetrahedron()

    class SlowFinder:
        def compute_coordination_environments(self, _structure, **_kwargs):
            time.sleep(0.01)
            return [[{"ce_symbol": "T:4", "ce_fraction": 1.0, "csm": 0.0}], None, None, None, None]

    environments = describe_coordination(
        structure,
        bonds,
        StructuralAnalysisSettings(maximum_seconds=0.001),
        geometry_finder=SlowFinder(),
    )

    assert environments[0].candidates[0].symbol == "T:4"
    assert environments[0].complete is False
    assert "time" in " ".join(environments[0].warnings).lower()


def test_chemenv_evaluates_one_representative_per_symmetry_orbit() -> None:
    sites = [
        AtomSite("B1", "B", (0.25, 0.25, 0.25)),
        AtomSite("B1·2", "B", (0.75, 0.75, 0.75)),
        AtomSite("O1", "O", (0.30, 0.30, 0.30)),
        AtomSite("O2", "O", (0.20, 0.20, 0.30)),
        AtomSite("O3", "O", (0.20, 0.30, 0.20)),
        AtomSite("O4", "O", (0.30, 0.20, 0.20)),
        AtomSite("O1·2", "O", (0.80, 0.80, 0.80)),
        AtomSite("O2·2", "O", (0.70, 0.70, 0.80)),
        AtomSite("O3·2", "O", (0.70, 0.80, 0.70)),
        AtomSite("O4·2", "O", (0.80, 0.70, 0.70)),
    ]
    structure = CrystalStructure("two copies", UnitCell(10, 10, 10), sites[:5], sites)
    bonds = PeriodicBondResult(
        tuple(
            PeriodicBond(center, ligand, (0, 0, 0), 1.0, 1.0, "test", 1.0)
            for center, ligands in ((0, range(2, 6)), (1, range(6, 10)))
            for ligand in ligands
        ),
        True,
    )

    class RecordingFinder:
        indices = None

        def compute_coordination_environments(self, value, **kwargs):
            self.indices = kwargs["indices"]
            result = [None] * len(value)
            result[0] = [{"ce_symbol": "T:4", "ce_fraction": 1.0, "csm": 0.0}]
            return result

    finder = RecordingFinder()
    environments = describe_coordination(
        structure,
        bonds,
        StructuralAnalysisSettings(),
        geometry_finder=finder,
    )

    assert finder.indices == [0]
    assert [item.center_index for item in environments] == [0, 1]
    assert environments[0].neighbor_indices == (2, 3, 4, 5)
    assert environments[1].neighbor_indices == (6, 7, 8, 9)
    assert [item.candidates[0].symbol for item in environments] == ["T:4", "T:4"]


def test_chemenv_keeps_different_coordination_numbers_separate_within_an_orbit() -> None:
    sites = [
        AtomSite("B1", "B", (0.25, 0.25, 0.25)),
        AtomSite("B1·2", "B", (0.75, 0.75, 0.75)),
        *(AtomSite(f"O{index}", "O", (0.05 * index, 0.1, 0.1)) for index in range(1, 8)),
    ]
    structure = CrystalStructure("defensive copies", UnitCell(10, 10, 10), sites, sites)
    bonds = PeriodicBondResult(
        tuple(
            PeriodicBond(center, ligand, (0, 0, 0), 1.0, 1.0, "test", 1.0)
            for center, ligands in ((0, range(2, 5)), (1, range(5, 9)))
            for ligand in ligands
        ),
        True,
    )

    class RecordingFinder:
        indices = None

        def compute_coordination_environments(self, value, **kwargs):
            self.indices = kwargs["indices"]
            result = [None] * len(value)
            result[0] = [{"ce_symbol": "TL:3", "ce_fraction": 1.0, "csm": 0.0}]
            result[1] = [{"ce_symbol": "T:4", "ce_fraction": 1.0, "csm": 0.0}]
            return result

    finder = RecordingFinder()
    environments = describe_coordination(
        structure,
        bonds,
        StructuralAnalysisSettings(),
        geometry_finder=finder,
    )

    assert finder.indices == [0, 1]
    assert [item.candidates[0].symbol for item in environments] == ["TL:3", "T:4"]
