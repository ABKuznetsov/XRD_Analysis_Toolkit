from __future__ import annotations

import math

from cristma.diffraction import (
    RadiationComponent,
    RadiationSpectrum,
    RadiationSpectrumProvenance,
)

from xrd_finder.instrument.models import RadiationComponentProfile, RadiationProfile


def available_tube_targets() -> tuple[str, ...]:
    return tuple(
        target.value for target in RadiationSpectrum.available_k_alpha_targets()
    )


def radiation_profile_from_tube(
    target: str,
    *,
    mode: str = "kalpha_doublet",
) -> RadiationProfile:
    if mode not in {"kalpha_doublet", "kalpha1_only"}:
        raise ValueError(f"Unsupported laboratory radiation mode: {mode}")
    spectrum = RadiationSpectrum.lab_k_alpha(target)
    source_components = spectrum.components if mode == "kalpha_doublet" else spectrum.components[:1]
    return RadiationProfile(
        target=str(target).strip().capitalize(),
        mode=mode,
        components=tuple(
            RadiationComponentProfile(
                label=component.label,
                wavelength_angstrom=component.wavelength_angstrom,
                weight=component.relative_weight,
            )
            for component in source_components
        ),
    )


def cristma_spectrum_from_profile(
    profile: RadiationProfile,
    *,
    source_id: str,
) -> RadiationSpectrum:
    components = profile.components[:1] if profile.mode != "kalpha_doublet" else profile.components
    if profile.mode == "custom_monochromatic":
        primary = components[0]
        return RadiationSpectrum.synchrotron(
            wavelength_angstrom=float(primary.wavelength_angstrom),
            source_id=source_id,
            label=primary.label,
        )

    target = profile.target.strip().capitalize()
    if target in available_tube_targets():
        packaged = RadiationSpectrum.lab_k_alpha(target)
        expected = packaged.components[:1] if profile.mode == "kalpha1_only" else packaged.components
        if _components_match(components, expected):
            if profile.mode == "kalpha_doublet":
                return packaged
            return RadiationSpectrum(
                components=packaged.components[:1],
                provenance=packaged.provenance,
                probe=packaged.probe,
            )

    return RadiationSpectrum(
        components=tuple(
            RadiationComponent(
                component_id=f"finder-radiation-{index}",
                label=component.label,
                wavelength_angstrom=float(component.wavelength_angstrom),
                relative_weight=float(component.weight),
            )
            for index, component in enumerate(components, start=1)
        ),
        provenance=RadiationSpectrumProvenance.user_supplied(source_id),
    )


def _components_match(
    profile_components: tuple[RadiationComponentProfile, ...],
    cristma_components: tuple[RadiationComponent, ...],
) -> bool:
    if len(profile_components) < len(cristma_components):
        return False
    return all(
        math.isclose(
            float(profile_component.wavelength_angstrom),
            float(cristma_component.wavelength_angstrom),
            rel_tol=0.0,
            abs_tol=1.0e-7,
        )
        and math.isclose(
            float(profile_component.weight),
            float(cristma_component.relative_weight),
            rel_tol=0.0,
            abs_tol=1.0e-7,
        )
        for profile_component, cristma_component in zip(
            profile_components,
            cristma_components,
        )
    )
