"""Build publication-oriented crystallochemical descriptors."""

from __future__ import annotations

from collections import Counter
from typing import Sequence, cast

import numpy as np

from crystal_viewer.analysis.descriptors.model import (
    DescriptorKind,
    DescriptorValue,
    DistributionSummary,
)
from crystal_viewer.analysis.hierarchy import CoordinationPolyhedron
from crystal_viewer.core.document import StructureDocument


METHOD_ID = "crystal-blocks-descriptors-v1"


def _bond_distortion_index(lengths: Sequence[float]) -> float:
    data = np.asarray(lengths, dtype=float)
    mean = float(np.mean(data)) if data.size else 0.0
    return float(np.mean(np.abs(data - mean)) / mean) if mean else 0.0


def _off_centering(polyhedron: CoordinationPolyhedron, document: StructureDocument) -> float:
    center_site = document.structure.sites[polyhedron.center_index]
    center = document.structure.cell.frac_to_cart(center_site.fractional)
    centroid = np.mean(np.asarray(polyhedron.vertex_coordinates, dtype=float), axis=0)
    return float(np.linalg.norm(center - centroid))


def _value(
    identifier: str,
    title: str,
    section: str,
    kind: DescriptorKind,
    value: object,
    unit: str = "",
    *,
    warning: str = "",
    object_refs: tuple[str, ...] = (),
) -> DescriptorValue:
    return DescriptorValue(
        id=identifier,
        title=title,
        section=section,
        kind=kind,
        value=cast(object, value),
        unit=unit,
        method_id=METHOD_ID,
        warning=warning,
        object_refs=object_refs,
    )


def build_descriptors(
    document: StructureDocument,
    strong_5_plus_1_gap: float = 0.25,
) -> dict[str, DescriptorValue]:
    cache_key = (
        METHOD_ID,
        f"strong-gap={float(strong_5_plus_1_gap):.8g}",
        document.content_identity(),
    )
    cached = document.descriptor_cache.get(cache_key)
    if isinstance(cached, dict):
        return cast(dict[str, DescriptorValue], cached)

    cell = document.structure.cell
    descriptors = {
        "cell.a": _value("cell.a", "a", "Unit Cell", DescriptorKind.SCALAR, cell.a, "Å"),
        "cell.b": _value("cell.b", "b", "Unit Cell", DescriptorKind.SCALAR, cell.b, "Å"),
        "cell.c": _value("cell.c", "c", "Unit Cell", DescriptorKind.SCALAR, cell.c, "Å"),
        "cell.alpha": _value(
            "cell.alpha", "α", "Unit Cell", DescriptorKind.SCALAR, cell.alpha, "°"
        ),
        "cell.beta": _value(
            "cell.beta", "β", "Unit Cell", DescriptorKind.SCALAR, cell.beta, "°"
        ),
        "cell.gamma": _value(
            "cell.gamma", "γ", "Unit Cell", DescriptorKind.SCALAR, cell.gamma, "°"
        ),
        "cell.volume": _value(
            "cell.volume", "Cell volume", "Unit Cell", DescriptorKind.SCALAR, cell.volume, "Å³"
        ),
        "cell.space_group": _value(
            "cell.space_group",
            "Space group",
            "Unit Cell",
            DescriptorKind.CATEGORICAL,
            document.structure.space_group or "unknown",
            warning=("" if document.structure.space_group else "Space group was not reported."),
        ),
        "cell.c_over_a": _value(
            "cell.c_over_a",
            "c/a ratio",
            "Unit Cell",
            DescriptorKind.SCALAR,
            cell.c / cell.a,
        ),
    }

    occupancy_messages = tuple(
        warning.message
        for warning in document.warnings
        if warning.code == "occupancy-out-of-range"
    )
    descriptors["occupancy.out_of_range"] = _value(
        "occupancy.out_of_range",
        "Occupancy warnings",
        "Warnings and Data Quality",
        DescriptorKind.CATEGORICAL,
        "; ".join(occupancy_messages) if occupancy_messages else "none",
        warning="; ".join(occupancy_messages),
    )

    counts = dict(sorted(Counter(item.type_name for item in document.hierarchy.polyhedra).items()))
    descriptors["coordination.polyhedron_counts"] = _value(
        "coordination.polyhedron_counts",
        "Coordination polyhedra",
        "Polyhedra",
        DescriptorKind.CATEGORICAL,
        counts,
        object_refs=tuple(item.id for item in document.hierarchy.polyhedra),
    )

    mo_o6 = [
        item
        for item in document.hierarchy.polyhedra
        if item.center_element == "Mo"
        and item.ligand_element == "O"
        and item.coordination_number == 6
    ]
    distortion = DistributionSummary.from_values(
        _bond_distortion_index(item.bond_lengths) for item in mo_o6
    )
    off_centering = DistributionSummary.from_values(
        _off_centering(item, document) for item in mo_o6
    )
    gaps = DistributionSummary.from_values(
        sorted(item.bond_lengths)[5] - sorted(item.bond_lengths)[4]
        for item in mo_o6
    )
    references = tuple(item.id for item in mo_o6)
    descriptors["mo_o.distortion_index"] = _value(
        "mo_o.distortion_index", "Mo–O distortion index", "Polyhedra",
        DescriptorKind.DISTRIBUTION, distortion, object_refs=references,
    )
    descriptors["mo_o.off_centering"] = _value(
        "mo_o.off_centering", "Mo off-centering", "Polyhedra",
        DescriptorKind.DISTRIBUTION, off_centering, "Å", object_refs=references,
    )
    descriptors["mo_o.d6_minus_d5"] = _value(
        "mo_o.d6_minus_d5", "d6 − d5", "Polyhedra",
        DescriptorKind.DISTRIBUTION, gaps, "Å", object_refs=references,
    )
    strong_fraction = (
        sum(value > strong_5_plus_1_gap for value in gaps.values) / gaps.count
        if gaps.count
        else None
    )
    descriptors["mo_o.strong_5_plus_1_fraction"] = _value(
        "mo_o.strong_5_plus_1_fraction",
        "Strong [5+1] fraction",
        "Polyhedra",
        DescriptorKind.SCALAR if strong_fraction is not None else DescriptorKind.UNAVAILABLE,
        strong_fraction,
    )

    topology = document.inorganic_topology
    if topology is None or not topology.interpretable:
        warning = "; ".join(topology.warnings) if topology is not None else "Topology was not evaluated."
        descriptors["topology.component_classes"] = _value(
            "topology.component_classes",
            "Periodic component classes",
            "Topology",
            DescriptorKind.UNAVAILABLE,
            None,
            warning=warning,
        )
    else:
        component_classes = dict(
            sorted(Counter(item.classification for item in topology.components).items())
        )
        descriptors["topology.component_classes"] = _value(
            "topology.component_classes",
            "Periodic component classes",
            "Topology",
            DescriptorKind.GRAPH,
            {
                "classes": component_classes,
                "ranks": tuple(item.periodic_rank for item in topology.components),
                "family_ids": tuple(item.id for item in topology.families),
            },
            warning="; ".join(topology.warnings),
        )

    document.descriptor_cache[cache_key] = descriptors
    return descriptors
