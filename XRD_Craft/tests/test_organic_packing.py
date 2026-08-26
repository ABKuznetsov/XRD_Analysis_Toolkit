from __future__ import annotations

import math

import pytest

from crystal_viewer.analysis.organic.components import ComponentReport, MolecularComponent
from crystal_viewer.analysis.organic.contacts import (
    ContactKind,
    ContactReport,
    IntermolecularContact,
)
from crystal_viewer.analysis.organic.packing import PackingSettings, build_packing
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _component(identifier: str, atom: int) -> MolecularComponent:
    return MolecularComponent(identifier, (atom,), (), 0, (), identifier, 1.0, identifier)


def _packing_case(images, *, kind=ContactKind.HYDROGEN_BOND):
    sites = [AtomSite("C1", "C", (0.2, 0.5, 0.5)), AtomSite("C2", "C", (0.8, 0.5, 0.5))]
    structure = CrystalStructure("packing", UnitCell(8, 8, 8), sites, sites)
    components = ComponentReport((_component("M1", 0), _component("M2", 1)), (), ())
    contacts = ContactReport(
        tuple(
            IntermolecularContact(
                f"C{index}", kind, "M1", "M2", image, 2.8, 170.0, 1.0, "test"
            )
            for index, image in enumerate(images)
        ),
        True,
    )
    return structure, components, contacts


@pytest.mark.parametrize(
    ("images", "rank", "label"),
    [
        (((1, 0, 0),), 0, "finite motif"),
        (((0, 0, 0), (1, 0, 0)), 1, "chain"),
        (((0, 0, 0), (1, 0, 0), (0, 1, 0)), 2, "layer"),
        (((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), 3, "3D assembly"),
    ],
)
def test_packing_rank_classification(images, rank, label) -> None:
    report = build_packing(*_packing_case(images))

    assert report.assemblies[0].periodic_rank == rank
    assert report.assemblies[0].classification == label


def test_generic_short_contacts_do_not_create_packing_assemblies() -> None:
    report = build_packing(*_packing_case(((0, 0, 0),), kind=ContactKind.SHORT))

    assert not report.assemblies


def test_voids_are_geometric_periodic_and_provenanced() -> None:
    site = AtomSite("C1", "C", (0.5, 0.5, 0.5))
    structure = CrystalStructure("void", UnitCell(6, 6, 6), [site], [site])
    components = ComponentReport((_component("M1", 0),), (), ())
    contacts = ContactReport((), False)

    report = build_packing(
        structure, components, contacts, settings=PackingSettings(grid_spacing=1.0)
    )

    assert report.voids[0].classification == "geometric void"
    assert report.voids[0].periodic_rank >= 1
    assert report.effective_grid_spacing >= 1.0
    assert "accessible" not in report.voids[0].classification.lower()


@pytest.mark.parametrize("spacing", [0.0, -0.1, math.nan])
def test_void_grid_spacing_validates(spacing) -> None:
    with pytest.raises(ValueError):
        PackingSettings(grid_spacing=spacing).validate()
