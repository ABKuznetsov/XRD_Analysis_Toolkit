from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Sequence

import numpy as np

from benchmarks.match.generate_profiles import GeneratedPattern
from benchmarks.match.scenarios import ScenarioComponent, ScenarioDefinition


@dataclass(frozen=True, slots=True)
class ComponentObservability:
    phase_id: str
    nominal_fraction: float
    diffraction_power: float
    nominal_signal_fraction: float
    profile_area_share: float
    visible_lines: int
    max_line_snr: float
    observable: bool


def build_detection_manifest(
    scenarios: Sequence[ScenarioDefinition],
    *,
    power_levels: Sequence[float] = (0.1, 0.3, 1.0, 3.0),
) -> tuple[ScenarioDefinition, ...]:
    """Expand mixtures across relative I/Ic while keeping single phases once."""

    result = []
    for scenario in scenarios:
        if len(scenario.components) <= 1:
            components = tuple(replace(item, diffraction_power=1.0) for item in scenario.components)
            result.append(replace(scenario, components=components))
            continue
        dominant_index = max(
            range(len(scenario.components)),
            key=lambda index: float(scenario.components[index].fraction),
        )
        for power in power_levels:
            components = tuple(
                replace(
                    item,
                    diffraction_power=1.0 if index == dominant_index else max(float(power), 0.0),
                )
                for index, item in enumerate(scenario.components)
            )
            result.append(
                replace(
                    scenario,
                    scenario_id=f"{scenario.scenario_id}-power-{float(power):.2f}",
                    components=components,
                )
            )
    return tuple(result)


def measure_component_observability(
    generated: GeneratedPattern,
    phase_id: str,
    *,
    minimum_snr: float = 3.0,
    minimum_profile_share: float = 0.10,
) -> ComponentObservability:
    """Measure whether a phase creates independently detectable profile peaks."""

    x = np.asarray(generated.x, dtype=float)
    profile = np.asarray(generated.component_profiles[phase_id], dtype=float)
    clean = np.asarray(generated.clean_y, dtype=float)
    noise = np.asarray(generated.y, dtype=float) - clean - np.asarray(generated.background, dtype=float)
    median = float(np.nanmedian(noise)) if len(noise) else 0.0
    sigma = 1.4826 * float(np.nanmedian(np.abs(noise - median))) if len(noise) else 0.0
    numerical_floor = max(float(np.nanmax(clean)) * 1.0e-6, 1.0e-9) if len(clean) else 1.0e-9
    sigma = max(sigma, numerical_floor)

    maxima = np.flatnonzero(
        (profile[1:-1] > profile[:-2]) & (profile[1:-1] >= profile[2:])
    ) + 1 if len(profile) >= 3 else np.asarray([], dtype=int)
    maximum = float(np.nanmax(profile)) if len(profile) else 0.0
    maxima = maxima[profile[maxima] >= maximum * 0.01] if maximum > 0.0 else maxima[:0]
    maxima = maxima[np.argsort(profile[maxima])[::-1]][:20]
    def record_position(record) -> float:
        value = getattr(record, "two_theta", None)
        if value is None:
            value = record[0]
        return float(value)

    observed_positions = np.asarray(
        [record_position(record) for record in generated.observed_records],
        dtype=float,
    ) if generated.observed_records else np.asarray([], dtype=float)
    tolerance = max(0.18, float(generated.component_fwhm.get(phase_id, generated.fwhm)) * 1.5)

    visible_lines = 0
    max_line_snr = 0.0
    strongest_share = 0.0
    for index in maxima:
        position = float(x[index])
        if not len(observed_positions) or float(np.min(np.abs(observed_positions - position))) > tolerance:
            continue
        amplitude = max(float(profile[index]), 0.0)
        line_snr = amplitude / sigma
        profile_share = amplitude / max(float(clean[index]), numerical_floor)
        max_line_snr = max(max_line_snr, line_snr)
        strongest_share = max(strongest_share, profile_share)
        if line_snr >= float(minimum_snr) and profile_share >= float(minimum_profile_share):
            visible_lines += 1

    profile_area = float(np.trapezoid(np.clip(profile, 0.0, None), x)) if len(x) else 0.0
    total_area = float(np.trapezoid(np.clip(clean, 0.0, None), x)) if len(x) else 0.0
    observable = visible_lines >= 2 or (
        visible_lines >= 1 and max_line_snr >= 5.0 and strongest_share >= 0.20
    )
    fraction = float(generated.component_fractions.get(phase_id, 0.0))
    power = float(generated.component_diffraction_power.get(phase_id, 1.0))
    return ComponentObservability(
        phase_id=str(phase_id),
        nominal_fraction=fraction,
        diffraction_power=power,
        nominal_signal_fraction=fraction * power,
        profile_area_share=profile_area / max(total_area, numerical_floor),
        visible_lines=int(visible_lines),
        max_line_snr=float(max_line_snr),
        observable=bool(observable),
    )


__all__ = [
    "ComponentObservability",
    "build_detection_manifest",
    "measure_component_observability",
]
