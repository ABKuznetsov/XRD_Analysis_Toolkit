from __future__ import annotations

import math
from dataclasses import dataclass

from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.series import SeriesMechanicsReport
from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class StructuralPassport:
    atoms: int
    polyhedra: int
    structural_units: int
    rigid_blocks: int
    connectors: int
    complexity_score: float
    complexity_stars: int
    topology: str
    mean_rigidity_prior: float
    predicted_flexibility: str
    dominant_mechanism: str
    nte_mechanism: str


def build_structural_passport(
    structure: CrystalStructure,
    hierarchy: HierarchyReport,
    series: SeriesMechanicsReport | None = None,
) -> StructuralPassport:
    counts = (
        len(structure.sites),
        len(hierarchy.polyhedra),
        len(hierarchy.structural_units),
        len(hierarchy.blocks),
        len(hierarchy.connectors),
    )
    complexity = min(
        1.0,
        (
            math.log1p(counts[0]) / 7.0
            + math.log1p(counts[1]) / 6.0
            + math.log1p(counts[2] + counts[3]) / 5.0
        )
        / 3.0,
    )
    rigidity = (
        sum(block.rigidity_score for block in hierarchy.blocks) / len(hierarchy.blocks)
        if hierarchy.blocks
        else 0.0
    )
    connector_ratio = len(hierarchy.connectors) / max(len(hierarchy.blocks), 1)
    flexibility = "Low" if connector_ratio < 0.25 else "Medium" if connector_ratio < 1.25 else "High"
    topology = "Pending periodic-net analysis"
    dominant = "Requires a structure series"
    nte = "Requires lattice-response analysis"
    if series is not None:
        shares = {
            "Rigid-block rotation": series.shares.rigid_block_rotation,
            "Rigid-block translation": series.shares.rigid_block_translation,
            "Internal distortion": series.shares.internal_distortion,
            "Connector-angle change": series.shares.connector_angle_change,
        }
        dominant = max(shares, key=shares.get)
        nte = "Candidate mechanism present" if shares["Rigid-block rotation"] + shares["Connector-angle change"] > 55 else "Not indicated"
    return StructuralPassport(
        atoms=counts[0],
        polyhedra=counts[1],
        structural_units=counts[2],
        rigid_blocks=counts[3],
        connectors=counts[4],
        complexity_score=complexity,
        complexity_stars=max(1, min(5, round(complexity * 5))),
        topology=topology,
        mean_rigidity_prior=rigidity,
        predicted_flexibility=flexibility,
        dominant_mechanism=dominant,
        nte_mechanism=nte,
    )

