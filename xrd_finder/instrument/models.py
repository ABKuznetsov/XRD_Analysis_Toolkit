from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 1


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    name: str = "Cu K-alpha default"
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    laboratory: str = ""
    calibration_date: str = ""
    comment: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Instrument profile name is required")


@dataclass(frozen=True, slots=True)
class RadiationComponentProfile:
    label: str
    wavelength_angstrom: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.wavelength_angstrom <= 0.0:
            raise ValueError("Radiation wavelength must be positive")
        if self.weight <= 0.0:
            raise ValueError("Radiation component weight must be positive")


@dataclass(frozen=True, slots=True)
class RadiationProfile:
    target: str = "Cu"
    mode: str = "kalpha_doublet"
    components: tuple[RadiationComponentProfile, ...] = (
        RadiationComponentProfile("Cu K-alpha1", 1.54056, 2.0),
        RadiationComponentProfile("Cu K-alpha2", 1.54439, 1.0),
    )
    tube_voltage_kv: float | None = None
    tube_current_ma: float | None = None
    filter_material: str = ""
    monochromator: str = ""

    def __post_init__(self) -> None:
        if not self.components:
            raise ValueError("At least one radiation wavelength component is required")
        if self.mode not in {"kalpha_doublet", "kalpha1_only", "custom_monochromatic"}:
            raise ValueError(f"Unsupported radiation mode: {self.mode}")

    @classmethod
    def custom_monochromatic(
        cls,
        wavelength_angstrom: float,
        *,
        label: str = "Custom",
    ) -> RadiationProfile:
        return cls(
            target="Custom",
            mode="custom_monochromatic",
            components=(RadiationComponentProfile(label, wavelength_angstrom),),
        )

    def calculation_payload(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "mode": self.mode,
            "components": [
                {
                    "label": component.label,
                    "wavelength_angstrom": component.wavelength_angstrom,
                    "weight": component.weight,
                }
                for component in self.components
            ],
        }


@dataclass(frozen=True, slots=True)
class GeometryProfile:
    geometry: str = "bragg_brentano"
    apply_lorentz_polarization: bool = True
    polarization_fraction: float = 0.5
    goniometer_radius_mm: float | None = None
    divergence_slit: str = ""
    receiving_slit: str = ""
    soller_slit: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.polarization_fraction <= 1.0:
            raise ValueError("Polarization fraction must be between 0 and 1")

    def calculation_payload(self) -> dict[str, Any]:
        return {
            "geometry": self.geometry,
            "apply_lorentz_polarization": self.apply_lorentz_polarization,
            "polarization_fraction": self.polarization_fraction,
        }


@dataclass(frozen=True, slots=True)
class DetectorProfile:
    manufacturer: str = ""
    model: str = ""
    detector_type: str = ""
    operating_mode: str = ""


@dataclass(frozen=True, slots=True)
class ResolutionProfile:
    model: str = "constant_fwhm"
    constant_fwhm_deg: float = 0.12
    u: float = 0.0
    v: float = 0.0
    w: float = 1.44
    x: float = 0.0
    y: float = 0.0

    def __post_init__(self) -> None:
        if self.model not in {"constant_fwhm", "tch"}:
            raise ValueError(f"Unsupported resolution model: {self.model}")
        if self.constant_fwhm_deg <= 0.0:
            raise ValueError("Constant FWHM must be positive")

    @classmethod
    def tch(cls, *, u: float, v: float, w: float, x: float, y: float) -> ResolutionProfile:
        return cls(model="tch", u=u, v=v, w=w, x=x, y=y)

    def calculation_payload(self) -> dict[str, Any]:
        if self.model == "constant_fwhm":
            return {
                "model": self.model,
                "constant_fwhm_deg": self.constant_fwhm_deg,
            }
        return {
            "model": self.model,
            "u": self.u,
            "v": self.v,
            "w": self.w,
            "x": self.x,
            "y": self.y,
        }


@dataclass(frozen=True, slots=True)
class InstrumentProfile:
    identity: InstrumentIdentity = field(default_factory=InstrumentIdentity)
    radiation: RadiationProfile = field(default_factory=RadiationProfile)
    geometry: GeometryProfile = field(default_factory=GeometryProfile)
    detector: DetectorProfile = field(default_factory=DetectorProfile)
    resolution: ResolutionProfile = field(default_factory=ResolutionProfile)
    profile_id: str = field(default_factory=lambda: f"instrument-{uuid4()}")
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def default_cu_kalpha(cls) -> InstrumentProfile:
        from xrd_finder.instrument.radiation_catalog import radiation_profile_from_tube

        return cls(
            radiation=radiation_profile_from_tube("Cu"),
            profile_id="builtin-cu-kalpha",
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> InstrumentProfile:
        radiation_data = dict(value.get("radiation") or {})
        components = tuple(
            RadiationComponentProfile(**component)
            for component in radiation_data.pop("components", [])
        )
        if components:
            radiation_data["components"] = components
        return cls(
            identity=InstrumentIdentity(**dict(value.get("identity") or {})),
            radiation=RadiationProfile(**radiation_data),
            geometry=GeometryProfile(**dict(value.get("geometry") or {})),
            detector=DetectorProfile(**dict(value.get("detector") or {})),
            resolution=ResolutionProfile(**dict(value.get("resolution") or {})),
            profile_id=str(value.get("profile_id") or f"instrument-{uuid4()}"),
            schema_version=int(value.get("schema_version") or SCHEMA_VERSION),
        )

    def calculation_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "radiation": self.radiation.calculation_payload(),
            "geometry": self.geometry.calculation_payload(),
            "resolution": self.resolution.calculation_payload(),
        }

    def calculation_key(self) -> str:
        payload = json.dumps(
            self.calculation_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()
