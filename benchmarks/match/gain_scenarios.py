from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from collections.abc import Mapping, Sequence

from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.scenarios import ScenarioComponent, ScenarioDefinition
from benchmarks.match.splits import PhaseDescriptor, SplitAssignment
from xrd_finder.services.phase_pattern_equivalence import phase_patterns_equivalent


GAIN_MODES = ("direct", "overlap", "hidden", "sparse", "low_fraction")


@dataclass(frozen=True, slots=True)
class GainScenarioConfig:
    seed: int = 5036
    scenarios_per_mode: int = 8
    overlap_tolerance: float = 0.32
    equivalence_fwhm: float = 0.32


@dataclass(frozen=True, slots=True)
class JointGainStressCase:
    case_id: str
    scenario: ScenarioDefinition
    accepted_phase_ids: tuple[str, ...]
    target_phase_id: str
    target_family: str
    variant_group: str
    variant_kind: str


@dataclass(frozen=True, slots=True)
class _Pair:
    accepted: PhaseDescriptor
    target: PhaseDescriptor
    overlap: float
    sparse: bool


def build_gain_scenario_manifest(
    phases: Sequence[PhaseDescriptor],
    assignments: Sequence[SplitAssignment],
    references: Mapping[str, Sequence[ReferenceLine]],
    config: GainScenarioConfig = GainScenarioConfig(),
) -> tuple[ScenarioDefinition, ...]:
    """Build deterministic two-phase cases targeted at Gain failure modes."""

    phase_by_id = {phase.phase_id: phase for phase in phases}
    by_split: dict[str, list[PhaseDescriptor]] = {"train": [], "validation": [], "test": []}
    for assignment in assignments:
        phase = phase_by_id.get(assignment.phase_id)
        if phase is not None and phase.phase_id in references:
            by_split.setdefault(assignment.split, []).append(phase)

    scenarios: list[ScenarioDefinition] = []
    serial = 0
    for split in ("train", "validation", "test"):
        pairs = _candidate_pairs(
            by_split.get(split, ()),
            references,
            tolerance=float(config.overlap_tolerance),
            equivalence_fwhm=float(config.equivalence_fwhm),
        )
        if not pairs:
            continue
        for mode in GAIN_MODES:
            ranked = sorted(
                pairs,
                key=lambda pair: _pair_sort_key(config.seed, split, mode, pair),
            )
            count = max(1, int(config.scenarios_per_mode))
            for index in range(count):
                pair = ranked[index % len(ranked)]
                target_fraction, fwhm, noise = _mode_parameters(mode, index)
                category = (
                    "organic"
                    if pair.accepted.category == "organic" or pair.target.category == "organic"
                    else "inorganic"
                )
                scenarios.append(
                    ScenarioDefinition(
                        scenario_id=f"gain-{split}-{mode}-{serial:04d}",
                        split=split,
                        seed=_integer_seed(config.seed, split, mode, serial),
                        components=(
                            ScenarioComponent(
                                pair.accepted.phase_id,
                                pair.accepted.family_id,
                                1.0 - target_fraction,
                                reciprocal_strain=_reciprocal_strain(index * 2),
                                fwhm=max(0.06, min(0.80, fwhm * (0.70 if index % 2 == 0 else 1.30))),
                            ),
                            ScenarioComponent(
                                pair.target.phase_id,
                                pair.target.family_id,
                                target_fraction,
                                reciprocal_strain=_reciprocal_strain(index * 2 + 1),
                                fwhm=max(0.06, min(0.80, fwhm * (1.45 if index % 2 == 0 else 0.78))),
                            ),
                        ),
                        fwhm=fwhm,
                        noise=noise,
                        overlap=mode,
                        background=("flat", "sloped", "curved", "amorphous")[index % 4],
                        zero_shift=(-0.18, 0.0, 0.18)[index % 3],
                        axis_scale=0.0,
                        intensity_distortion=("none", "moderate", "strong")[index % 3],
                        category=category,
                    )
                )
                serial += 1
    return tuple(scenarios)


def build_joint_gain_stress_manifest(
    phases: Sequence[PhaseDescriptor],
    assignments: Sequence[SplitAssignment],
    references: Mapping[str, Sequence[ReferenceLine]],
    *,
    seed: int = 5036,
) -> tuple[JointGainStressCase, ...]:
    """Build paired stress cases that isolate order and card-variant effects."""

    phase_by_id = {phase.phase_id: phase for phase in phases}
    by_split: dict[str, list[PhaseDescriptor]] = {}
    for assignment in assignments:
        phase = phase_by_id.get(assignment.phase_id)
        if phase is not None and phase.phase_id in references:
            by_split.setdefault(assignment.split, []).append(phase)

    cases: list[JointGainStressCase] = []
    for split in sorted(by_split):
        available = sorted(by_split[split], key=lambda item: item.phase_id)
        equivalent_pair = next(
            (
                (first, second)
                for index, first in enumerate(available)
                for second in available[index + 1 :]
                if phase_patterns_equivalent(
                    references[first.phase_id],
                    references[second.phase_id],
                    fwhm=0.32,
                )
            ),
            None,
        )
        if equivalent_pair is None:
            continue
        accepted, accepted_variant = equivalent_pair
        distinct = [
            phase
            for phase in available
            if phase.phase_id not in {accepted.phase_id, accepted_variant.phase_id}
            and not phase_patterns_equivalent(
                references[accepted.phase_id],
                references[phase.phase_id],
                fwhm=0.32,
            )
        ]
        if not distinct:
            continue
        accepted_lines = _strong_lines(references[accepted.phase_id])
        target = max(
            distinct,
            key=lambda phase: (
                _weighted_overlap(
                    _strong_lines(references[phase.phase_id]),
                    accepted_lines,
                    0.32,
                ),
                phase.phase_id,
            ),
        )
        helpers = [phase for phase in distinct if phase.phase_id != target.phase_id]

        def scenario(case_id: str, components, *, noise="low", overlap="overlap"):
            return ScenarioDefinition(
                scenario_id=case_id,
                split=split,
                seed=_integer_seed(seed, split, case_id, len(cases)),
                components=tuple(components),
                fwhm=0.18,
                noise=noise,
                overlap=overlap,
                background="curved",
                zero_shift=0.12,
                axis_scale=0.0,
                intensity_distortion="moderate",
                category=(
                    "organic"
                    if any(item.category == "organic" for item in (accepted, target))
                    else "inorganic"
                ),
            )

        def component(phase: PhaseDescriptor, fraction: float):
            return ScenarioComponent(
                phase.phase_id,
                phase.family_id,
                fraction,
                reciprocal_strain=_reciprocal_strain(len(cases)),
                fwhm=0.18,
            )

        shared_id = f"joint-{split}-shared-dominant"
        shared = scenario(
            shared_id,
            (component(accepted, 0.65), component(target, 0.35)),
        )
        cases.append(
            JointGainStressCase(
                shared_id,
                shared,
                (accepted.phase_id,),
                target.phase_id,
                target.family_id,
                f"{split}:shared",
                "shared-dominant-line",
            )
        )

        if helpers:
            order_id = f"joint-{split}-accepted-order"
            order_scenario = scenario(
                order_id,
                (
                    component(accepted, 0.48),
                    component(helpers[0], 0.30),
                    component(target, 0.22),
                ),
            )
            for suffix, accepted_ids in (
                ("a", (accepted.phase_id, helpers[0].phase_id)),
                ("b", (helpers[0].phase_id, accepted.phase_id)),
            ):
                cases.append(
                    JointGainStressCase(
                        f"{order_id}-{suffix}",
                        order_scenario,
                        accepted_ids,
                        target.phase_id,
                        target.family_id,
                        f"{split}:order",
                        "accepted-order",
                    )
                )

        for suffix, selected in (("a", accepted), ("b", accepted_variant)):
            card_id = f"joint-{split}-card-variant-{suffix}"
            card_scenario = scenario(
                card_id,
                (component(selected, 0.65), component(target, 0.35)),
            )
            cases.append(
                JointGainStressCase(
                    card_id,
                    card_scenario,
                    (selected.phase_id,),
                    target.phase_id,
                    target.family_id,
                    f"{split}:card",
                    "card-variant",
                )
            )

        noise_id = f"joint-{split}-noise-only"
        noise_scenario = scenario(
            noise_id,
            (component(accepted, 0.995), component(target, 0.005)),
            noise="high",
            overlap="noise-only",
        )
        cases.append(
            JointGainStressCase(
                noise_id,
                noise_scenario,
                (accepted.phase_id,),
                target.phase_id,
                target.family_id,
                f"{split}:noise",
                "noise-only",
            )
        )

        if len(helpers) >= 2:
            weak_id = f"joint-{split}-weak-overlap"
            weak_scenario = scenario(
                weak_id,
                (
                    component(accepted, 0.45),
                    component(helpers[0], 0.27),
                    component(helpers[1], 0.20),
                    component(target, 0.08),
                ),
                noise="medium",
                overlap="weak-overlap",
            )
            cases.append(
                JointGainStressCase(
                    weak_id,
                    weak_scenario,
                    (accepted.phase_id, helpers[0].phase_id, helpers[1].phase_id),
                    target.phase_id,
                    target.family_id,
                    f"{split}:weak-overlap",
                    "weak-overlap",
                )
            )
    return tuple(cases)


def _candidate_pairs(
    phases: Sequence[PhaseDescriptor],
    references: Mapping[str, Sequence[ReferenceLine]],
    *,
    tolerance: float,
    equivalence_fwhm: float,
) -> tuple[_Pair, ...]:
    result = []
    for target in phases:
        target_lines = _strong_lines(references.get(target.phase_id, ()))
        if len(target_lines) < 3:
            continue
        sparse = _is_sparse(target_lines)
        for accepted in phases:
            if accepted.phase_id == target.phase_id or accepted.family_id == target.family_id:
                continue
            if phase_patterns_equivalent(
                references.get(accepted.phase_id, ()),
                references.get(target.phase_id, ()),
                fwhm=equivalence_fwhm,
            ):
                continue
            accepted_lines = _strong_lines(references.get(accepted.phase_id, ()))
            if len(accepted_lines) < 3:
                continue
            result.append(
                _Pair(
                    accepted=accepted,
                    target=target,
                    overlap=_weighted_overlap(target_lines, accepted_lines, tolerance),
                    sparse=sparse,
                )
            )
    return tuple(result)


def _pair_sort_key(seed: int, split: str, mode: str, pair: _Pair):
    tie = hashlib.sha256(
        f"{seed}:{split}:{mode}:{pair.accepted.phase_id}:{pair.target.phase_id}".encode("utf-8")
    ).digest()
    if mode in {"overlap", "hidden"}:
        primary = -pair.overlap
    else:
        primary = pair.overlap
    sparse_mismatch = 0 if (pair.sparse == (mode == "sparse")) else 1
    if mode != "sparse" and pair.sparse:
        sparse_mismatch = 1
    return sparse_mismatch, primary, tie


def _mode_parameters(mode: str, index: int) -> tuple[float, float, str]:
    if mode == "hidden":
        return 0.04, (0.30, 0.50)[index % 2], "high"
    if mode == "low_fraction":
        return 0.08, (0.15, 0.30)[index % 2], ("medium", "high")[index % 2]
    if mode == "overlap":
        return 0.30, (0.15, 0.30)[index % 2], ("none", "low")[index % 2]
    if mode == "sparse":
        return 0.22, (0.08, 0.15)[index % 2], ("low", "medium")[index % 2]
    return 0.30, (0.08, 0.15)[index % 2], ("none", "low")[index % 2]


def _reciprocal_strain(index: int) -> tuple[float, float, float, float, float, float]:
    axial = (-0.006, -0.003, 0.0, 0.003, 0.006)
    shear = (-0.0015, 0.0, 0.0015)
    return (
        axial[index % len(axial)],
        axial[(index * 2 + 1) % len(axial)],
        axial[(index * 3 + 2) % len(axial)],
        shear[index % len(shear)],
        shear[(index + 1) % len(shear)],
        shear[(index + 2) % len(shear)],
    )


def _strong_lines(lines: Sequence[ReferenceLine]) -> tuple[ReferenceLine, ...]:
    usable = [
        line
        for line in lines
        if math.isfinite(float(line.two_theta))
        and math.isfinite(float(line.intensity))
        and float(line.intensity) > 0.0
    ]
    usable.sort(key=lambda line: float(line.intensity), reverse=True)
    return tuple(usable[:10])


def _is_sparse(lines: Sequence[ReferenceLine]) -> bool:
    values = sorted((max(float(line.intensity), 0.0) for line in lines), reverse=True)[:10]
    if len(values) < 3:
        return bool(values)
    total = sum(values)
    return bool(total > 0.0 and (values[0] / total >= 0.45 or sum(values[:2]) / total >= 0.65))


def _weighted_overlap(
    target: Sequence[ReferenceLine],
    accepted: Sequence[ReferenceLine],
    tolerance: float,
) -> float:
    total = sum(max(float(line.intensity), 0.0) for line in target)
    if total <= 0.0:
        return 0.0
    accepted_positions = [float(line.two_theta) for line in accepted]
    supported = sum(
        max(float(line.intensity), 0.0)
        for line in target
        if accepted_positions
        and min(abs(float(line.two_theta) - position) for position in accepted_positions) <= tolerance
    )
    return float(supported / total)


def _integer_seed(seed: int, split: str, mode: str, serial: int) -> int:
    value = hashlib.sha256(f"{seed}:{split}:{mode}:{serial}".encode("utf-8")).digest()
    return int.from_bytes(value[:4], "big")


__all__ = [
    "GAIN_MODES",
    "GainScenarioConfig",
    "JointGainStressCase",
    "build_gain_scenario_manifest",
    "build_joint_gain_stress_manifest",
]
