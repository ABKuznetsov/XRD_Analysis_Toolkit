from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Iterable
from uuid import uuid4

from PySide6.QtWidgets import QMessageBox

from xrd_finder.instrument.library import (
    BUILTIN_PROFILE_ID,
    PACKAGED_PROFILE_IDS,
    InstrumentProfileLibrary,
)
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.ui.instrument_profile_dialog import InstrumentProfileDialog


def primary_wavelength(profile: InstrumentProfile) -> float:
    return float(profile.radiation.components[0].wavelength_angstrom)


def legacy_constant_fwhm(profile: InstrumentProfile) -> float | None:
    if profile.resolution.model != "constant_fwhm":
        return None
    return float(profile.resolution.constant_fwhm_deg)


def legacy_radiation_settings(profile: InstrumentProfile) -> tuple[float, bool]:
    return (
        primary_wavelength(profile),
        profile.radiation.mode == "kalpha_doublet",
    )


def apply_profile_snapshot(patterns: Iterable[object], profile: InstrumentProfile) -> None:
    snapshot = profile.to_dict()
    wavelength = primary_wavelength(profile)
    for pattern in patterns:
        pattern.instrument_profile = deepcopy(snapshot)
        pattern.wavelength = wavelength


class PhaseFinderInstrumentProfileActionsMixin:
    def _init_instrument_profile_state(self) -> None:
        self.instrument_profile_library = InstrumentProfileLibrary()
        self._instrument_profile_dialog = None
        preferred_id = str(
            self.settings.value("instrument/active_profile_id", BUILTIN_PROFILE_ID, type=str)
            or BUILTIN_PROFILE_ID
        )
        if self.instrument_profile_library.get(preferred_id) is None:
            preferred_id = BUILTIN_PROFILE_ID
        self._selected_instrument_profile_id = preferred_id
        profile = self.instrument_profile_library.get(preferred_id) or InstrumentProfile.default_cu_kalpha()
        for pattern in self.project.patterns:
            if not getattr(pattern, "instrument_profile", None):
                apply_profile_snapshot([pattern], profile)

    def _active_instrument_profile(self) -> InstrumentProfile:
        pattern = self._active_pattern()
        return self._instrument_profile_for_pattern(pattern)

    def _instrument_profile_for_pattern(self, pattern) -> InstrumentProfile:
        snapshot = getattr(pattern, "instrument_profile", None) if pattern is not None else None
        if snapshot:
            try:
                return InstrumentProfile.from_dict(dict(snapshot))
            except (TypeError, ValueError):
                pass
        profile = self.instrument_profile_library.get(self._selected_instrument_profile_id)
        return profile or InstrumentProfile.default_cu_kalpha()

    def _legacy_fwhm_for_pattern(self, pattern) -> float | None:
        return legacy_constant_fwhm(self._instrument_profile_for_pattern(pattern))

    def _legacy_radiation_for_pattern(self, pattern) -> tuple[float, bool]:
        return legacy_radiation_settings(self._instrument_profile_for_pattern(pattern))

    def _active_wavelength(self) -> float:
        return primary_wavelength(self._active_instrument_profile())

    def _ensure_active_instrument_profile(self) -> None:
        pattern = self._active_pattern()
        if pattern is None or getattr(pattern, "instrument_profile", None):
            return
        profile = self.instrument_profile_library.get(self._selected_instrument_profile_id)
        apply_profile_snapshot([pattern], profile or InstrumentProfile.default_cu_kalpha())

    def _refresh_instrument_profile_selector(self) -> None:
        action_bar = getattr(self, "finder_action_bar", None)
        if action_bar is None:
            return
        current = self._active_instrument_profile()
        profiles = list(self.instrument_profile_library.list_profiles())
        matching_saved = next(
            (profile for profile in profiles if profile.profile_id == current.profile_id),
            None,
        )
        if matching_saved is None:
            profiles.append(current)
        entries = []
        for profile in profiles:
            shown = current if profile.profile_id == current.profile_id else profile
            name = shown.identity.name
            if (
                profile.profile_id == current.profile_id
                and matching_saved is not None
                and matching_saved.calculation_key() != current.calculation_key()
            ):
                name = f"{name} [{current.radiation.target}]"
            entries.append((shown.profile_id, name))
        action_bar.set_instrument_profiles(
            entries,
            current.profile_id,
        )

    def _select_instrument_profile(self, profile_id: str) -> None:
        profile = self.instrument_profile_library.get(profile_id)
        if profile is None:
            return
        self._selected_instrument_profile_id = profile_id
        self.settings.setValue("instrument/active_profile_id", profile_id)
        self._apply_instrument_profile(profile, selected=False)

    def _open_instrument_profile_editor(self, section: str = "identity") -> None:
        profile = self._active_instrument_profile()
        dialog = InstrumentProfileDialog(
            profile,
            profiles=self.instrument_profile_library.list_profiles(),
            packaged_profile_ids=PACKAGED_PROFILE_IDS,
            section=section,
            parent=self,
        )
        dialog.saveAsRequested.connect(self._save_instrument_profile_as_new)
        dialog.updateRequested.connect(self._update_instrument_profile)
        dialog.deleteRequested.connect(self._delete_instrument_profile)
        dialog.applyActiveRequested.connect(lambda value: self._apply_instrument_profile(value, selected=False))
        dialog.applySelectedRequested.connect(lambda value: self._apply_instrument_profile(value, selected=True))
        dialog.finished.connect(lambda _result: self._clear_instrument_profile_dialog(dialog))
        self._instrument_profile_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_instrument_profile_dialog(self, dialog: InstrumentProfileDialog) -> None:
        if self._instrument_profile_dialog is dialog:
            self._instrument_profile_dialog = None

    def _save_instrument_profile_as_new(self, profile: InstrumentProfile) -> None:
        saved = replace(profile, profile_id=f"instrument-{uuid4()}")
        try:
            self.instrument_profile_library.save_profile(saved)
        except ValueError as exc:
            QMessageBox.warning(self, "Instrument profile", str(exc))
            return
        self._selected_instrument_profile_id = saved.profile_id
        self.settings.setValue("instrument/active_profile_id", saved.profile_id)
        if self._instrument_profile_dialog is not None:
            self._instrument_profile_dialog.set_profiles(
                self.instrument_profile_library.list_profiles(),
                current_profile=saved,
            )
        self._refresh_instrument_profile_selector()

    def _update_instrument_profile(self, profile: InstrumentProfile) -> None:
        try:
            self.instrument_profile_library.save_profile(profile, overwrite=True)
        except ValueError as exc:
            QMessageBox.warning(self, "Instrument profile", str(exc))
            return
        if self._instrument_profile_dialog is not None:
            self._instrument_profile_dialog.set_profiles(
                self.instrument_profile_library.list_profiles(),
                current_profile=profile,
            )
        self._refresh_instrument_profile_selector()

    def _delete_instrument_profile(self, profile_id: str) -> None:
        try:
            self.instrument_profile_library.delete(profile_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Instrument profile", str(exc))
            return
        self._selected_instrument_profile_id = BUILTIN_PROFILE_ID
        self.settings.setValue("instrument/active_profile_id", BUILTIN_PROFILE_ID)
        if self._instrument_profile_dialog is not None:
            self._instrument_profile_dialog.close()
        self._refresh_instrument_profile_selector()

    def _patterns_for_instrument_profile(self, *, selected: bool) -> list[object]:
        if not selected:
            active = self._active_pattern()
            return [active] if active is not None else []
        checked_ids = set(self.tree.checked_pattern_ids())
        patterns = [pattern for pattern in self.project.patterns if pattern.id in checked_ids]
        if patterns:
            return patterns
        active = self._active_pattern()
        return [active] if active is not None else []

    def _apply_instrument_profile(self, profile: InstrumentProfile, *, selected: bool) -> None:
        patterns = self._patterns_for_instrument_profile(selected=selected)
        if not patterns:
            return
        queue = getattr(self, "visible_profile_calculation_queue", None)
        if queue is not None:
            queue.clear()
        apply_profile_snapshot(patterns, profile)
        self._selected_instrument_profile_id = profile.profile_id
        self.settings.setValue("instrument/active_profile_id", profile.profile_id)
        for cache_name in (
            "_candidate_peak_cache",
            "_candidate_json_peak_cache",
            "_candidate_probability_cache",
            "_candidate_gain_profile_cache",
            "_corundum_peak_cache",
            "_auto_scoring_cache",
        ):
            cache = getattr(self, cache_name, None)
            if cache is not None:
                cache.clear()
        for pattern in patterns:
            state = getattr(self, "profile_states", {}).get(getattr(pattern, "id", ""), {})
            if isinstance(state, dict):
                state.pop("result_snapshot", None)
        self._invalidate_match_profile_cache()
        self.project.touch()
        self.project_changed.emit()
        self._refresh_instrument_profile_selector()
        self._refresh_observed_pattern_plot()
        self._recalculate_match_profile()
        self._rerank_loaded_candidates_for_instrument_change()
