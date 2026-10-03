from __future__ import annotations

from dataclasses import dataclass
import hashlib
from collections.abc import Sequence

from benchmarks.match.splits import PhaseDescriptor, SplitAssignment


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    seed: int = 5036
    fwhm_levels: tuple[float, ...] = (0.08, 0.15, 0.30, 0.50)
    noise_levels: tuple[str, ...] = ("none", "low", "medium", "high")


@dataclass(frozen=True, slots=True)
class ScenarioComponent:
    phase_id: str
    family_id: str
    fraction: float
    reciprocal_strain: tuple[float, float, float, float, float, float] = (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )
    fwhm: float | None = None
    diffraction_power: float = 1.0


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    split: str
    seed: int
    components: tuple[ScenarioComponent, ...]
    fwhm: float
    noise: str
    overlap: str
    background: str
    zero_shift: float
    axis_scale: float
    intensity_distortion: str
    category: str


def build_scenario_manifest(
    phases: Sequence[PhaseDescriptor],
    assignments: Sequence[SplitAssignment],
    config: ScenarioConfig,
) -> tuple[ScenarioDefinition, ...]:
    phase_by_id = {phase.phase_id: phase for phase in phases}
    by_split: dict[str, list[PhaseDescriptor]] = {"train": [], "validation": [], "test": []}
    for assignment in assignments:
        phase = phase_by_id[assignment.phase_id]
        by_split[assignment.split].append(phase)
    for split, members in by_split.items():
        members.sort(key=lambda phase: _stable_key(config.seed, split, phase.phase_id))

    scenarios = []
    serial = 0
    for split in ("train", "validation", "test"):
        members = by_split[split]
        if not members:
            continue
        for fwhm_index, fwhm in enumerate(config.fwhm_levels):
            for noise_index, noise in enumerate(config.noise_levels):
                for phase_count in (1, 2, 3, 4):
                    if len(members) < phase_count:
                        continue
                    start = (fwhm_index * 17 + noise_index * 7 + phase_count * 3) % len(members)
                    selected = tuple(members[(start + offset) % len(members)] for offset in range(phase_count))
                    fractions = _fractions(phase_count)
                    width_factors = (0.72, 1.0, 1.38, 1.75)
                    components = tuple(
                        ScenarioComponent(
                            phase.phase_id,
                            phase.family_id,
                            fraction,
                            reciprocal_strain=_reciprocal_strain(serial + offset),
                            fwhm=float(max(0.06, min(0.80, fwhm * width_factors[offset]))),
                        )
                        for offset, (phase, fraction) in enumerate(zip(selected, fractions, strict=True))
                    )
                    category = "organic" if any(phase.category == "organic" for phase in selected) else "inorganic"
                    scenario_seed = _integer_seed(config.seed, split, serial)
                    scenarios.append(
                        ScenarioDefinition(
                            scenario_id=f"{split}-{serial:04d}",
                            split=split,
                            seed=scenario_seed,
                            components=components,
                            fwhm=float(fwhm),
                            noise=noise,
                            overlap="high" if (serial % 3 == 0 and phase_count > 1) else "ordinary",
                            background=("flat", "sloped", "curved", "amorphous")[serial % 4],
                            zero_shift=(-0.30, -0.10, 0.0, 0.10, 0.30)[serial % 5],
                            axis_scale=0.0,
                            intensity_distortion=("none", "moderate", "strong")[serial % 3],
                            category=category,
                        )
                    )
                    serial += 1
    return tuple(scenarios)


def _fractions(count: int) -> tuple[float, ...]:
    return {
        1: (1.0,),
        2: (0.92, 0.08),
        3: (0.72, 0.20, 0.08),
        4: (0.52, 0.20, 0.20, 0.08),
    }[count]


def _stable_key(seed: int, split: str, value: str) -> bytes:
    return hashlib.sha256(f"{seed}:{split}:{value}".encode("utf-8")).digest()


def _integer_seed(seed: int, split: str, serial: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{split}:{serial}".encode("utf-8")).digest()[:4], "big")


def _reciprocal_strain(index: int) -> tuple[float, float, float, float, float, float]:
    levels = (-0.006, -0.003, 0.0, 0.003, 0.006)
    shear = (-0.0015, 0.0, 0.0015)
    return (
        levels[index % len(levels)],
        levels[(index * 2 + 1) % len(levels)],
        levels[(index * 3 + 2) % len(levels)],
        shear[index % len(shear)],
        shear[(index + 1) % len(shear)],
        shear[(index + 2) % len(shear)],
    )


__all__ = [
    "ScenarioComponent",
    "ScenarioConfig",
    "ScenarioDefinition",
    "build_scenario_manifest",
]
