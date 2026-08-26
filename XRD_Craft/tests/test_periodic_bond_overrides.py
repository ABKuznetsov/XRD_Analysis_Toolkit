from __future__ import annotations

from crystal_viewer.analysis.periodic_bonds import BondSettings, build_periodic_bonds
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


class _NoNeighbours:
    def get_nn_info(self, _structure, _index):
        return []


def _structure():
    return CrystalStructure(
        "manual-bond",
        UnitCell(5.0, 5.0, 5.0),
        [],
        [
            AtomSite("B1", "B", (0.0, 0.0, 0.0)),
            AtomSite("O1", "O", (0.3, 0.0, 0.0)),
        ],
    )


def test_confirmed_addition_is_present_with_recomputed_distance():
    result = build_periodic_bonds(
        _structure(),
        BondSettings(confirmed_additions=((0, 1, (0, 0, 0)),)),
        neighbor_finder=_NoNeighbours(),
    )

    assert len(result.bonds) == 1
    assert result.bonds[0].method == "user-confirmed"
    assert result.bonds[0].distance == 1.5
    assert result.bonds[0].confidence == 1.0


def test_confirmed_removal_wins_over_an_identical_addition():
    key = (0, 1, (0, 0, 0))
    result = build_periodic_bonds(
        _structure(),
        BondSettings(confirmed_additions=(key,), confirmed_removals=(key,)),
        neighbor_finder=_NoNeighbours(),
    )

    assert result.bonds == ()
