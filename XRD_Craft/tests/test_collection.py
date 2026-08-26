from __future__ import annotations

import pytest

from crystal_viewer.analysis.hierarchy import HierarchyAnalyzer
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


def _document(name: str) -> StructureDocument:
    site = AtomSite("O1", "O", (0.0, 0.0, 0.0))
    structure = CrystalStructure(
        name=name,
        cell=UnitCell(5.0, 5.0, 5.0),
        asymmetric_sites=[site],
        sites=[site],
    )
    return StructureDocument.from_structure(
        structure,
        HierarchyAnalyzer().analyze(structure),
    )


def test_collection_keeps_exact_visual_slots() -> None:
    collection = StructureCollection()
    first, second, third = (_document(name) for name in ("one", "two", "three"))
    for document in (first, second, third):
        collection.add(document)

    collection.assign_visual("A", first.id)
    collection.assign_visual("B", second.id)
    collection.assign_visual("A", third.id)

    pair = collection.visual_pair()
    assert pair is not None
    assert tuple(item.id for item in pair) == (third.id, second.id)


def test_visual_pair_is_absent_until_both_slots_are_assigned() -> None:
    collection = StructureCollection()
    document = _document("one")
    collection.add(document)
    collection.assign_visual("A", document.id)

    assert collection.visual_pair() is None


def test_compare_selection_rejects_fifth_document() -> None:
    collection = StructureCollection(max_compared=4)
    documents = [_document(str(index)) for index in range(5)]
    for document in documents:
        collection.add(document)
    for document in documents[:4]:
        collection.set_compared(document.id, True)

    with pytest.raises(ValueError, match="four"):
        collection.set_compared(documents[4].id, True)

    assert tuple(item.id for item in collection.compared_documents()) == tuple(
        document.id for document in documents[:4]
    )
