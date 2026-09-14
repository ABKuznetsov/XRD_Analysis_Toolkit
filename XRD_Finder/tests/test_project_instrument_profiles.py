from __future__ import annotations

from pathlib import Path

import pytest

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.instrument.models import InstrumentProfile, RadiationProfile
from xrd_finder.instrument.presets import tongda_td3700_profile
from xrd_finder.io.project_io import load_project_manifest, save_project_manifest


@pytest.mark.parametrize("suffix", [".json", ".xpff"])
def test_project_round_trip_preserves_instrument_profile_snapshot(
    tmp_path: Path,
    suffix: str,
) -> None:
    profile = InstrumentProfile.default_cu_kalpha()
    pattern = Pattern.create("Observed")
    pattern.instrument_profile = profile.to_dict()
    project = Project(name="Instrument profile", patterns=[pattern])
    target = tmp_path / f"project{suffix}"

    save_project_manifest(project, target)
    restored = load_project_manifest(target)

    assert restored.patterns[0].instrument_profile == profile.to_dict()


def test_xpff_round_trip_preserves_tongda_td3700_profile(tmp_path: Path) -> None:
    project = Project(name="TD3700 project")
    pattern = Pattern.create("sample")
    profile = tongda_td3700_profile()
    pattern.instrument_profile = profile.to_dict()
    pattern.wavelength = profile.radiation.components[0].wavelength_angstrom
    project.patterns.append(pattern)
    target = tmp_path / "td3700.xpff"

    save_project_manifest(project, target)
    restored = load_project_manifest(target)

    restored_profile = InstrumentProfile.from_dict(restored.patterns[0].instrument_profile)
    assert restored_profile == profile
    assert restored.patterns[0].wavelength == pytest.approx(
        profile.radiation.components[0].wavelength_angstrom
    )


def test_legacy_wavelength_is_upgraded_to_profile_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "legacy.json"
    target.write_text(
        """
        {
          "name": "Legacy",
          "patterns": [
            {
              "name": "Observed",
              "id": "pattern-1",
              "wavelength": 0.709317
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    restored = load_project_manifest(target)
    snapshot = restored.patterns[0].instrument_profile
    profile = InstrumentProfile.from_dict(snapshot)

    assert profile.radiation == RadiationProfile.custom_monochromatic(
        0.709317,
        label="Legacy wavelength",
    )
    assert restored.patterns[0].wavelength == pytest.approx(0.709317)
