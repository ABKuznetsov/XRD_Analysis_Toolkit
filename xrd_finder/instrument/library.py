from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.instrument.presets import packaged_instrument_profiles
from xrd_finder.services.cache_paths import default_instrument_profile_library_path


LIBRARY_SCHEMA_VERSION = 1
BUILTIN_PROFILE_ID = "builtin-cu-kalpha"
PACKAGED_PROFILE_IDS = frozenset(
    {BUILTIN_PROFILE_ID}
)


class InstrumentProfileLibrary:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_instrument_profile_library_path()
        self._profiles = self._load_or_restore()

    def list_profiles(self) -> tuple[InstrumentProfile, ...]:
        return tuple(self._profiles)

    def get(self, profile_id: str) -> InstrumentProfile | None:
        return next((profile for profile in self._profiles if profile.profile_id == profile_id), None)

    def save_profile(self, profile: InstrumentProfile, *, overwrite: bool = False) -> None:
        current_index = next(
            (index for index, item in enumerate(self._profiles) if item.profile_id == profile.profile_id),
            None,
        )
        if current_index is not None and not overwrite:
            raise ValueError(f"Instrument profile already exists: {profile.profile_id}")

        normalized_name = profile.identity.name.strip().casefold()
        if any(
            item.profile_id != profile.profile_id
            and item.identity.name.strip().casefold() == normalized_name
            for item in self._profiles
        ):
            raise ValueError(f"Instrument profile name already exists: {profile.identity.name}")

        updated = list(self._profiles)
        if current_index is None:
            updated.append(profile)
        else:
            updated[current_index] = profile
        self._write(updated)
        self._profiles = updated

    def delete(self, profile_id: str) -> None:
        if profile_id in PACKAGED_PROFILE_IDS:
            raise ValueError("Packaged instrument profiles cannot be deleted")
        updated = [profile for profile in self._profiles if profile.profile_id != profile_id]
        if len(updated) == len(self._profiles):
            return
        self._ensure_packaged(updated)
        self._write(updated)
        self._profiles = updated

    def _load_or_restore(self) -> list[InstrumentProfile]:
        if not self.path.exists():
            profiles = list(packaged_instrument_profiles())
            self._write(profiles)
            return profiles

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            profiles = self._parse(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._preserve_corrupt_file()
            profiles = list(packaged_instrument_profiles())
            self._write(profiles)
            return profiles

        if self._ensure_packaged(profiles):
            self._write(profiles)
        return profiles

    @staticmethod
    def _parse(payload: Any) -> list[InstrumentProfile]:
        if not isinstance(payload, dict):
            raise ValueError("Instrument profile library must be a JSON object")
        if payload.get("schema_version") != LIBRARY_SCHEMA_VERSION:
            raise ValueError("Unsupported instrument profile library schema")
        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ValueError("Instrument profile library has no profile list")
        profiles = [InstrumentProfile.from_dict(item) for item in raw_profiles if isinstance(item, dict)]
        if len(profiles) != len(raw_profiles):
            raise ValueError("Instrument profile library contains an invalid profile")
        return profiles

    @staticmethod
    def _ensure_packaged(profiles: list[InstrumentProfile]) -> bool:
        changed = False
        for target_index, packaged in enumerate(packaged_instrument_profiles()):
            current_index = next(
                (
                    index
                    for index, profile in enumerate(profiles)
                    if profile.profile_id == packaged.profile_id
                ),
                None,
            )
            if current_index is None:
                profiles.insert(target_index, packaged)
                changed = True
                continue
            if profiles[current_index] != packaged:
                profiles[current_index] = packaged
                changed = True
            if current_index != target_index:
                profile = profiles.pop(current_index)
                profiles.insert(target_index, profile)
                changed = True
        return changed

    def _write(self, profiles: list[InstrumentProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "schema_version": LIBRARY_SCHEMA_VERSION,
            "profiles": [profile.to_dict() for profile in profiles],
        }
        temporary_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.path)

    def _preserve_corrupt_file(self) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.path.with_name(f"{self.path.stem}.corrupt-{timestamp}{self.path.suffix}")
        counter = 1
        while backup.exists():
            backup = self.path.with_name(
                f"{self.path.stem}.corrupt-{timestamp}-{counter}{self.path.suffix}"
            )
            counter += 1
        self.path.replace(backup)
