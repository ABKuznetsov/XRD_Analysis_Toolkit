"""Portable single-instrument profiles, independent of application settings."""
from __future__ import annotations

import json
import math
from numbers import Real
from dataclasses import fields
import os
from pathlib import Path
import tempfile

from xrd_finder.instrument.models import InstrumentProfile, SCHEMA_VERSION

PROFILE_FORMAT = "xrd-finder-instrument-profile"
PROFILE_FILE_SCHEMA = 1


def _validate_profile(profile: InstrumentProfile) -> None:
    for section in (profile.identity, profile.radiation, profile.geometry, profile.detector, profile.resolution):
        for field in fields(section):
            if field.type == 'str' and not isinstance(getattr(section, field.name), str):
                raise ValueError("Instrument text fields must contain text.")
    if not isinstance(profile.geometry.apply_lorentz_polarization, bool):
        raise ValueError("The Lorentz-polarization option must be a boolean.")
    values = [getattr(profile.resolution, name) for name in ("constant_fwhm_deg", "u", "v", "w", "x", "y")]
    values.extend((profile.geometry.polarization_fraction,))
    values.extend(value for value in (profile.geometry.goniometer_radius_mm,
        profile.radiation.tube_voltage_kv, profile.radiation.tube_current_ma) if value is not None)
    for component in profile.radiation.components:
        if not isinstance(component.label, str):
            raise ValueError("Radiation component labels must contain text.")
        values.extend((component.wavelength_angstrom, component.weight))
    try:
        valid = all(not isinstance(value, bool) and isinstance(value, Real) and math.isfinite(value) for value in values)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Instrument coefficients and wavelengths must be finite numbers.")


def _validate_required_fields(raw: dict) -> None:
    required = {
        "identity": ("name",),
        "radiation": ("target", "mode", "components"),
        "geometry": ("geometry", "apply_lorentz_polarization", "polarization_fraction"),
        "resolution": ("model",),
    }
    for section, names in required.items():
        if any(name not in raw[section] for name in names):
            raise ValueError(f"Incomplete instrument profile: {section}.")
    components = raw["radiation"]["components"]
    if not isinstance(components, list) or not components or any(
            not isinstance(component, dict) or any(key not in component
            for key in ("label", "wavelength_angstrom", "weight")) for component in components):
        raise ValueError("Explicit radiation wavelengths and weights are required.")
    resolution = raw["resolution"]
    names = ("u", "v", "w", "x", "y", "coefficient_units") if resolution["model"] == "tch" else ("constant_fwhm_deg",)
    if any(name not in resolution for name in names):
        raise ValueError("Explicit resolution coefficients and units are required.")


def export_instrument_profile(profile: InstrumentProfile, path: str | Path) -> None:
    _validate_profile(profile)
    payload = {"format": PROFILE_FORMAT, "schema_version": PROFILE_FILE_SCHEMA, "profile": profile.to_dict()}
    text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_instrument_profile(path: str | Path) -> InstrumentProfile:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("format") != PROFILE_FORMAT or payload.get("schema_version") != PROFILE_FILE_SCHEMA:
            raise ValueError("Unsupported instrument profile file format.")
        raw = payload.get("profile")
        if not isinstance(raw, dict) or any(not isinstance(raw.get(name), dict)
                for name in ("identity", "radiation", "geometry", "detector", "resolution")):
            raise ValueError("The file does not contain a complete instrument profile.")
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported instrument profile schema.")
        _validate_required_fields(raw)
        profile = InstrumentProfile.from_dict(raw)
        _validate_profile(profile)
        return profile
    except (TypeError, AttributeError, KeyError, OverflowError) as exc:
        raise ValueError("Invalid instrument profile values.") from exc
