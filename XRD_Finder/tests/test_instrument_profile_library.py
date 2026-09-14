from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from xrd_finder.instrument.library import (
    TONGDA_TD3700_PROFILE_ID,
    InstrumentProfileLibrary,
)
from xrd_finder.instrument.models import InstrumentIdentity, InstrumentProfile
from xrd_finder.services.cache_paths import default_instrument_profile_library_path


def _profile(profile_id: str, name: str) -> InstrumentProfile:
    return InstrumentProfile(
        profile_id=profile_id,
        identity=InstrumentIdentity(name=name),
    )


def test_first_load_creates_packaged_profiles_and_schema_document(tmp_path: Path) -> None:
    path = tmp_path / "instrument_profiles.json"

    library = InstrumentProfileLibrary(path)

    assert [profile.profile_id for profile in library.list_profiles()] == [
        "builtin-cu-kalpha",
        TONGDA_TD3700_PROFILE_ID,
    ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["profiles"][0]["profile_id"] == "builtin-cu-kalpha"


def test_tongda_td3700_packaged_profile_uses_calibration_parameters(tmp_path: Path) -> None:
    profile = InstrumentProfileLibrary(tmp_path / "instrument_profiles.json").get(
        TONGDA_TD3700_PROFILE_ID
    )

    assert profile is not None
    assert profile.identity.name == "Tongda TD3700 (Cu, 1D)"
    assert profile.identity.manufacturer == "Tongda"
    assert profile.identity.model == "TD3700"
    assert profile.radiation.target == "Cu"
    assert [component.weight for component in profile.radiation.components] == pytest.approx(
        [2.0, 1.0]
    )
    assert profile.radiation.tube_voltage_kv == pytest.approx(30.0)
    assert profile.radiation.tube_current_ma == pytest.approx(20.0)
    assert profile.geometry.goniometer_radius_mm == pytest.approx(225.0)
    assert profile.geometry.polarization_fraction == pytest.approx(0.7)
    assert profile.detector.detector_type == "1D"
    assert profile.resolution.model == "tch"
    assert (
        profile.resolution.u,
        profile.resolution.v,
        profile.resolution.w,
        profile.resolution.x,
        profile.resolution.y,
    ) == pytest.approx((2.0, -2.0, 5.0, 3.9697460181849933, 3.6562103496734855))
    assert "SH/L=0.002" in profile.identity.comment


def test_create_update_and_delete_profile_preserves_builtin(tmp_path: Path) -> None:
    library = InstrumentProfileLibrary(tmp_path / "instrument_profiles.json")
    created = _profile("lab-1", "Laboratory diffractometer")

    library.save_profile(created)
    library.save_profile(
        replace(created, identity=replace(created.identity, comment="Calibrated")),
        overwrite=True,
    )

    assert library.get("lab-1").identity.comment == "Calibrated"
    library.delete("lab-1")
    assert library.get("lab-1") is None
    assert library.get("builtin-cu-kalpha") is not None
    assert library.get(TONGDA_TD3700_PROFILE_ID) is not None


def test_packaged_tongda_profile_cannot_be_deleted(tmp_path: Path) -> None:
    library = InstrumentProfileLibrary(tmp_path / "instrument_profiles.json")

    with pytest.raises(ValueError, match="Packaged"):
        library.delete(TONGDA_TD3700_PROFILE_ID)


def test_duplicate_profile_names_are_rejected_case_insensitively(tmp_path: Path) -> None:
    library = InstrumentProfileLibrary(tmp_path / "instrument_profiles.json")
    library.save_profile(_profile("lab-1", "My instrument"))

    with pytest.raises(ValueError, match="name"):
        library.save_profile(_profile("lab-2", "  MY INSTRUMENT  "))


def test_corrupt_library_is_preserved_and_replaced_with_default(tmp_path: Path) -> None:
    path = tmp_path / "instrument_profiles.json"
    path.write_text("{not valid json", encoding="utf-8")

    library = InstrumentProfileLibrary(path)

    assert library.get("builtin-cu-kalpha") is not None
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert list(tmp_path.glob("instrument_profiles.corrupt-*.json"))


def test_writes_use_atomic_replace_and_leave_no_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "instrument_profiles.json"
    calls: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def tracking_replace(source: Path, target: Path) -> Path:
        calls.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", tracking_replace)
    library = InstrumentProfileLibrary(path)
    library.save_profile(_profile("lab-1", "Instrument 1"))

    assert calls
    assert all(target == path for _, target in calls)
    assert not list(tmp_path.glob("*.tmp"))


def test_default_library_path_uses_managed_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XRD_FINDER_DATA_DIR", str(tmp_path))

    assert default_instrument_profile_library_path() == tmp_path / "settings" / "instrument_profiles.json"
