from __future__ import annotations

from dataclasses import replace

from xrd_finder.instrument.models import (
    DetectorProfile,
    GeometryProfile,
    InstrumentIdentity,
    InstrumentProfile,
    RadiationComponentProfile,
    ResolutionProfile,
)
from xrd_finder.instrument.radiation_catalog import radiation_profile_from_tube


TONGDA_TD3700_PROFILE_ID = "preset-tongda-td3700-cu-1d"


def tongda_td3700_profile() -> InstrumentProfile:
    catalog_radiation = radiation_profile_from_tube("Cu")
    radiation = replace(
        catalog_radiation,
        components=tuple(
            RadiationComponentProfile(
                label=component.label,
                wavelength_angstrom=component.wavelength_angstrom,
                weight=weight,
            )
            for component, weight in zip(
                catalog_radiation.components,
                (2.0, 1.0),
                strict=True,
            )
        ),
        tube_voltage_kv=30.0,
        tube_current_ma=20.0,
    )
    return InstrumentProfile(
        profile_id=TONGDA_TD3700_PROFILE_ID,
        identity=InstrumentIdentity(
            name="Tongda TD3700 (Cu, 1D)",
            manufacturer="Tongda",
            model="TD3700",
            comment=(
                "GSAS-II calibration from Si_0.4_noknife.instprm: Zero=0.0 deg; "
                "SH/L=0.002 (stored for provenance; axial asymmetry is not yet applied)."
            ),
        ),
        radiation=radiation,
        geometry=GeometryProfile(
            geometry="bragg_brentano",
            apply_lorentz_polarization=True,
            polarization_fraction=0.7,
            goniometer_radius_mm=225.0,
        ),
        detector=DetectorProfile(
            manufacturer="Tongda",
            detector_type="1D",
        ),
        resolution=ResolutionProfile.tch(
            u=2.0,
            v=-2.0,
            w=5.0,
            x=3.9697460181849933,
            y=3.6562103496734855,
        ),
    )


def packaged_instrument_profiles() -> tuple[InstrumentProfile, ...]:
    return (
        InstrumentProfile.default_cu_kalpha(),
        tongda_td3700_profile(),
    )
