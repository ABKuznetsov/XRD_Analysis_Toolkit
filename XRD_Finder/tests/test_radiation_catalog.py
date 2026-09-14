from __future__ import annotations

from cristma.diffraction import RadiationSpectrum

from xrd_finder.instrument.models import RadiationComponentProfile, RadiationProfile
from xrd_finder.instrument.radiation_catalog import (
    available_tube_targets,
    cristma_spectrum_from_profile,
    radiation_profile_from_tube,
)


def test_catalog_delegates_available_targets_to_cristma() -> None:
    assert available_tube_targets() == tuple(
        target.value for target in RadiationSpectrum.available_k_alpha_targets()
    )


def test_catalog_copies_cristma_components_without_rounding() -> None:
    expected = RadiationSpectrum.lab_k_alpha("Ag")

    profile = radiation_profile_from_tube("Ag")

    assert profile.target == "Ag"
    assert profile.mode == "kalpha_doublet"
    assert tuple(component.wavelength_angstrom for component in profile.components) == tuple(
        component.wavelength_angstrom for component in expected.components
    )
    assert tuple(component.weight for component in profile.components) == tuple(
        component.relative_weight for component in expected.components
    )


def test_catalog_recognizes_values_rounded_by_instrument_editor() -> None:
    source = radiation_profile_from_tube("Cr")
    rounded = RadiationProfile(
        target=source.target,
        mode=source.mode,
        components=tuple(
            RadiationComponentProfile(
                component.label,
                round(component.wavelength_angstrom, 7),
                round(component.weight, 7),
            )
            for component in source.components
        ),
    )

    spectrum = cristma_spectrum_from_profile(rounded, source_id="rounded-ui")

    assert spectrum.source_id == "xray-tube:cr-ka"
