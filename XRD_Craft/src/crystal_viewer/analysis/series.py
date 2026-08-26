from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.motion import BlockMotion, compare_block_coordinates
from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class BlockSeriesResult:
    block_id: str
    classification: str
    atom_count: int
    motion: BlockMotion
    rigidity_confidence: float


@dataclass(frozen=True, slots=True)
class ConnectorSeriesResult:
    connector_id: str
    first_block: str
    second_block: str
    start_angle: float
    end_angle: float

    @property
    def angle_change(self) -> float:
        return self.end_angle - self.start_angle


@dataclass(frozen=True, slots=True)
class MechanismShares:
    rigid_block_rotation: float
    rigid_block_translation: float
    internal_distortion: float
    connector_angle_change: float


@dataclass(frozen=True, slots=True)
class SeriesMechanicsReport:
    start_label: str
    end_label: str
    blocks: tuple[BlockSeriesResult, ...]
    connectors: tuple[ConnectorSeriesResult, ...]
    shares: MechanismShares
    warnings: tuple[str, ...] = ()


def _validate_correspondence(structures: list[CrystalStructure]) -> None:
    if len(structures) < 2:
        raise ValueError("At least two structures are required for mechanics analysis.")
    reference_elements = [site.element for site in structures[0].sites]
    for structure in structures[1:]:
        if [site.element for site in structure.sites] != reference_elements:
            raise ValueError(
                "Automatic series analysis currently requires identical site order and elements. "
                "A crystallographic site matcher is the next implementation step."
            )


def _connector_angle(
    structure: CrystalStructure,
    first_center_index: int,
    second_center_index: int,
    ligand_index: int,
) -> float:
    pivot = np.asarray(structure.sites[ligand_index].fractional, dtype=float)

    def vector_to(center_index: int) -> np.ndarray:
        delta = np.asarray(structure.sites[center_index].fractional, dtype=float) - pivot
        delta -= np.rint(delta)
        return delta @ structure.cell.matrix

    first = vector_to(first_center_index)
    second = vector_to(second_center_index)
    denominator = np.linalg.norm(first) * np.linalg.norm(second)
    if denominator <= 1e-12:
        return 0.0
    cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def _mechanism_shares(
    blocks: list[BlockSeriesResult],
    connectors: list[ConnectorSeriesResult],
) -> MechanismShares:
    # A descriptive geometric motion budget, not yet a tensorial CTE decomposition.
    rotation = sum(abs(item.motion.rotation_degrees) for item in blocks)
    translation = sum(item.motion.translation for item in blocks)
    distortion = sum(item.motion.distortion_percent for item in blocks)
    connector = sum(abs(item.angle_change) for item in connectors)
    values = np.asarray((rotation, translation, distortion, connector), dtype=float)
    total = float(values.sum())
    percentages = values / total * 100.0 if total > 0 else np.zeros(4)
    return MechanismShares(*map(float, percentages))


def analyze_structure_series(
    structures: list[CrystalStructure],
    hierarchy: HierarchyReport,
    labels: list[str] | None = None,
) -> SeriesMechanicsReport:
    """
    Compare the first and last structure using the hierarchy from the first.

    Site correspondence is intentionally strict in this first version. It avoids
    presenting a plausible-looking but crystallographically wrong block motion.
    """
    _validate_correspondence(structures)
    labels = labels or [structure.name for structure in structures]
    start, end = structures[0], structures[-1]
    block_results = []
    for block in hierarchy.blocks:
        indices = list(block.atom_indices)
        if len(indices) < 3:
            continue
        motion = compare_block_coordinates(start.cartesian_positions[indices], end.cartesian_positions[indices])
        confidence = float(np.exp(-motion.distortion_percent / 1.0))
        block_results.append(
            BlockSeriesResult(
                block_id=block.id,
                classification=block.classification,
                atom_count=len(indices),
                motion=motion,
                rigidity_confidence=confidence,
            )
        )
    connector_results = []
    polyhedron_lookup = {polyhedron.id: polyhedron for polyhedron in hierarchy.polyhedra}
    for connector in hierarchy.connectors:
        first_polyhedron = polyhedron_lookup[connector.first_polyhedron]
        second_polyhedron = polyhedron_lookup[connector.second_polyhedron]
        start_angle = _connector_angle(
            start,
            first_polyhedron.center_index,
            second_polyhedron.center_index,
            connector.ligand_indices[0],
        )
        end_angle = _connector_angle(
            end,
            first_polyhedron.center_index,
            second_polyhedron.center_index,
            connector.ligand_indices[0],
        )
        connector_results.append(
            ConnectorSeriesResult(
                connector_id=connector.id,
                first_block=connector.first_block,
                second_block=connector.second_block,
                start_angle=start_angle,
                end_angle=end_angle,
            )
        )
    warnings = (
        "Mechanism shares are a normalized geometric motion budget, not yet a decomposition of the thermal-expansion tensor.",
    )
    return SeriesMechanicsReport(
        start_label=labels[0],
        end_label=labels[-1],
        blocks=tuple(block_results),
        connectors=tuple(connector_results),
        shares=_mechanism_shares(block_results, connector_results),
        warnings=warnings,
    )
