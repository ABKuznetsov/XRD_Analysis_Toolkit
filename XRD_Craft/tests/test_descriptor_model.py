from __future__ import annotations

import pytest

from crystal_viewer.analysis.descriptors.model import (
    DescriptorKind,
    DescriptorValue,
    DistributionSummary,
    FocusCommand,
)
from crystal_viewer.analysis.hierarchy import HierarchyLevel


def test_distribution_summary_is_stable_and_empty_safe() -> None:
    summary = DistributionSummary.from_values([3.0, 1.0, 2.0])

    assert summary.minimum == 1.0
    assert summary.mean == 2.0
    assert summary.maximum == 3.0
    assert summary.std == pytest.approx(0.8164965809)
    assert summary.count == 3
    assert summary.values == (3.0, 1.0, 2.0)
    assert DistributionSummary.from_values([]).count == 0


def test_descriptor_and_focus_payloads_are_typed_and_immutable() -> None:
    descriptor = DescriptorValue(
        id="cell.a",
        title="a",
        section="Crystal data",
        kind=DescriptorKind.SCALAR,
        value=7.736,
        unit="Å",
    )
    focus = FocusCommand(
        action="select",
        level=HierarchyLevel.POLYHEDRA,
        selector="type",
        payload={"value": "MoO6"},
    )

    assert descriptor.kind is DescriptorKind.SCALAR
    assert focus.payload["value"] == "MoO6"
    with pytest.raises(TypeError):
        focus.payload["value"] = "SiO4"  # type: ignore[index]
