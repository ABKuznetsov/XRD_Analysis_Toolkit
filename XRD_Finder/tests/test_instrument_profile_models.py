from __future__ import annotations

from dataclasses import replace

import pytest

import xrd_finder.instrument as instrument_api
from xrd_finder.instrument.models import (
    InstrumentIdentity,
    InstrumentProfile,
    RadiationProfile,
    ResolutionProfile,
)


def test_public_instrument_api_exports_models_and_library() -> None:
    assert set(instrument_api.__all__) == {
        "DetectorProfile",
        "GeometryProfile",
        "InstrumentIdentity",
        "InstrumentProfile",
        "InstrumentProfileLibrary",
        "RadiationComponentProfile",
        "RadiationProfile",
        "ResolutionProfile",
    }


def test_builtin_cu_profile_round_trips_without_losing_scientific_state() -> None:
    profile = InstrumentProfile.default_cu_kalpha()

    restored = InstrumentProfile.from_dict(profile.to_dict())

    assert restored == profile
    assert restored.radiation.target == "Cu"
    assert restored.radiation.mode == "kalpha_doublet"
    assert restored.resolution.model == "constant_fwhm"
    assert restored.schema_version == 1


def test_metadata_changes_do_not_invalidate_calculation_key() -> None:
    profile = InstrumentProfile.default_cu_kalpha()
    renamed = replace(
        profile,
        identity=replace(profile.identity, name="Laboratory diffractometer", serial_number="SN-42"),
    )

    assert renamed.calculation_key() == profile.calculation_key()


def test_radiation_and_resolution_changes_invalidate_calculation_key() -> None:
    profile = InstrumentProfile.default_cu_kalpha()
    monochromatic = replace(
        profile,
        radiation=RadiationProfile.custom_monochromatic(0.709317, label="Mo K-alpha1"),
    )
    tch = replace(
        profile,
        resolution=ResolutionProfile.tch(u=1.0, v=-0.2, w=0.8, x=0.04, y=0.01),
    )

    assert monochromatic.calculation_key() != profile.calculation_key()
    assert tch.calculation_key() != profile.calculation_key()


def test_invalid_custom_wavelength_is_rejected() -> None:
    with pytest.raises(ValueError, match="wavelength"):
        RadiationProfile.custom_monochromatic(0.0)


def test_profile_name_is_required() -> None:
    with pytest.raises(ValueError, match="name"):
        InstrumentProfile(identity=InstrumentIdentity(name="   "))
