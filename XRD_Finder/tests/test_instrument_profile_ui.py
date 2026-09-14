from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from cristma.diffraction import RadiationSpectrum

from xrd_finder.core.pattern import Pattern
from xrd_finder.instrument.models import InstrumentProfile, RadiationProfile, ResolutionProfile
from xrd_finder.instrument.radiation_catalog import (
    available_tube_targets,
    radiation_profile_from_tube,
)
from xrd_finder.ui.finder_action_bar import FinderActionBar
from xrd_finder.ui.candidate_search_actions import PhaseFinderCandidateSearchActionsMixin
from xrd_finder.ui.instrument_profile_actions import (
    PhaseFinderInstrumentProfileActionsMixin,
    apply_profile_snapshot,
    legacy_constant_fwhm,
    legacy_radiation_settings,
)
from xrd_finder.ui.instrument_profile_dialog import (
    InstrumentProfileDialog,
    InstrumentProfileEditor,
)
from xrd_finder.ui.phase_finder_menu import build_phase_finder_menu_bar


class InstrumentProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_action_bar_emits_profile_id_and_edit_request(self) -> None:
        bar = FinderActionBar()
        selected: list[str] = []
        edit_requests: list[bool] = []
        bar.instrumentProfileSelected.connect(selected.append)
        bar.instrumentProfileEditRequested.connect(lambda: edit_requests.append(True))

        bar.set_instrument_profiles(
            [("builtin-cu-kalpha", "Cu K-alpha default"), ("lab-1", "Lab diffractometer")],
            "builtin-cu-kalpha",
        )
        bar.instrument_profile_combo.setCurrentIndex(1)
        bar.instrument_profile_edit_button.click()

        self.assertEqual(selected, ["lab-1"])
        self.assertEqual(edit_requests, [True])
        self.assertEqual(bar.current_instrument_profile_id(), "lab-1")

    def test_pattern_menu_opens_requested_editor_section(self) -> None:
        class Owner(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.sections: list[str] = []

            def _open_instrument_profile_editor(self, section: str = "identity") -> None:
                self.sections.append(section)

            def _search_pdf2_text(self) -> None:
                pass

            def _search_pdf2_candidates(self) -> None:
                pass

            def _add_selected_candidate_to_match_list(self) -> None:
                pass

            def _add_selected_cif_to_project(self) -> None:
                pass

            def _show_database_settings_tab(self) -> None:
                pass

            def _open_toolkit_catalog(self) -> None:
                pass

        owner = Owner()
        menu_bar = build_phase_finder_menu_bar(owner)
        instrument_menu = next(menu for menu in menu_bar._owned_menus if menu.title() == "Instrument")
        actions = {action.text(): action for action in instrument_menu.actions()}

        actions["Wavelength..."].trigger()
        actions["Resolution..."].trigger()

        self.assertEqual(owner.sections, ["radiation", "resolution"])

    def test_resolution_fields_follow_selected_model(self) -> None:
        editor = InstrumentProfileEditor()

        editor.resolution_model.setCurrentIndex(
            editor.resolution_model.findData("constant_fwhm")
        )
        self.assertTrue(editor.constant_fwhm.isEnabled())
        self.assertFalse(editor.tch_u.isEnabled())

        editor.resolution_model.setCurrentIndex(editor.resolution_model.findData("tch"))
        self.assertFalse(editor.constant_fwhm.isEnabled())
        self.assertTrue(editor.tch_u.isEnabled())
        self.assertTrue(editor.tch_y.isEnabled())

    def test_radiation_target_uses_cristma_tube_presets(self) -> None:
        editor = InstrumentProfileEditor()

        self.assertIsInstance(editor.radiation_target, QComboBox)
        self.assertTrue(editor.radiation_target.isEditable())
        self.assertEqual(available_tube_targets(), ("Cr", "Fe", "Co", "Cu", "Mo", "Ag"))
        self.assertEqual(
            [editor.radiation_target.itemText(index) for index in range(editor.radiation_target.count())],
            ["Cr", "Fe", "Co", "Cu", "Mo", "Ag", "Custom"],
        )

    def test_selecting_tube_loads_cristma_doublet(self) -> None:
        editor = InstrumentProfileEditor()
        expected = RadiationSpectrum.lab_k_alpha("Co")

        editor.radiation_target.setCurrentText("Co")

        self.assertEqual(editor.radiation_mode.currentData(), "kalpha_doublet")
        self.assertEqual(editor.component_1_label.text(), expected.components[0].label)
        self.assertAlmostEqual(
            editor.component_1_wavelength.value(),
            expected.components[0].wavelength_angstrom,
        )
        self.assertAlmostEqual(editor.component_1_weight.value(), expected.components[0].relative_weight)
        self.assertEqual(editor.component_2_label.text(), expected.components[1].label)
        self.assertAlmostEqual(
            editor.component_2_wavelength.value(),
            expected.components[1].wavelength_angstrom,
        )
        self.assertAlmostEqual(editor.component_2_weight.value(), expected.components[1].relative_weight)

    def test_custom_monochromatic_mode_keeps_manual_wavelength(self) -> None:
        editor = InstrumentProfileEditor()

        editor.radiation_mode.setCurrentIndex(
            editor.radiation_mode.findData("custom_monochromatic")
        )
        editor.component_1_label.setText("Beamline wavelength")
        editor.component_1_wavelength.setValue(0.41328)

        result = editor.instrument_profile()

        self.assertEqual(result.radiation.target, "Custom")
        self.assertEqual(result.radiation.mode, "custom_monochromatic")
        self.assertEqual(len(result.radiation.components), 1)
        self.assertAlmostEqual(result.radiation.components[0].wavelength_angstrom, 0.41328)

    def test_switching_standard_target_back_to_doublet_restores_second_component(self) -> None:
        source = InstrumentProfile(
            radiation=RadiationProfile(
                target="Mo",
                mode="kalpha1_only",
                components=(
                    radiation_profile_from_tube("Mo", mode="kalpha1_only").components[0],
                ),
            )
        )
        editor = InstrumentProfileEditor(source)
        expected = RadiationSpectrum.lab_k_alpha("Mo")

        editor.radiation_mode.setCurrentIndex(
            editor.radiation_mode.findData("kalpha_doublet")
        )

        result = editor.instrument_profile()
        self.assertEqual(len(result.radiation.components), 2)
        self.assertAlmostEqual(
            result.radiation.components[1].wavelength_angstrom,
            expected.components[1].wavelength_angstrom,
        )

    def test_editor_round_trips_profile_and_keeps_profile_id(self) -> None:
        source = InstrumentProfile(
            profile_id="lab-1",
            resolution=ResolutionProfile.tch(u=0.1, v=-0.02, w=0.03, x=0.04, y=0.05),
        )
        editor = InstrumentProfileEditor(source)

        result = editor.instrument_profile()

        self.assertEqual(result.profile_id, "lab-1")
        self.assertEqual(result.resolution.model, "tch")
        self.assertAlmostEqual(result.resolution.v, -0.02)
        self.assertEqual(result.radiation.components, source.radiation.components)

    def test_dialog_selects_saved_profile_and_loads_it_into_editor(self) -> None:
        builtin = InstrumentProfile.default_cu_kalpha()
        tongda = InstrumentProfile(
            profile_id="tongda",
            identity=builtin.identity.__class__(name="Tongda TD3700"),
            resolution=ResolutionProfile.tch(u=2.0, v=-2.0, w=5.0, x=3.9, y=3.6),
        )
        dialog = InstrumentProfileDialog(
            builtin,
            profiles=(builtin, tongda),
            packaged_profile_ids={builtin.profile_id},
        )

        dialog.profile_selector.setCurrentIndex(
            dialog.profile_selector.findData(tongda.profile_id)
        )

        self.assertEqual(dialog.editor.instrument_profile().profile_id, "tongda")
        self.assertEqual(dialog.editor.profile_name.text(), "Tongda TD3700")
        self.assertTrue(dialog.save_profile_button.isEnabled())
        self.assertTrue(dialog.delete_button.isEnabled())

    def test_dialog_new_profile_creates_unsaved_editable_draft(self) -> None:
        builtin = InstrumentProfile.default_cu_kalpha()
        dialog = InstrumentProfileDialog(
            builtin,
            profiles=(builtin,),
            packaged_profile_ids={builtin.profile_id},
        )

        dialog.new_profile_button.click()

        draft = dialog.editor.instrument_profile()
        self.assertNotEqual(draft.profile_id, builtin.profile_id)
        self.assertEqual(draft.identity.name, "New instrument profile")
        self.assertTrue(dialog.save_profile_button.isEnabled())
        self.assertFalse(dialog.delete_button.isEnabled())

    def test_dialog_single_save_action_routes_packaged_and_user_profiles(self) -> None:
        builtin = InstrumentProfile.default_cu_kalpha()
        user_profile = InstrumentProfile(
            profile_id="lab-profile",
            identity=builtin.identity.__class__(name="Laboratory profile"),
        )
        dialog = InstrumentProfileDialog(
            builtin,
            profiles=(builtin, user_profile),
            packaged_profile_ids={builtin.profile_id},
        )
        saved_as: list[str] = []
        updated: list[str] = []
        dialog.saveAsRequested.connect(lambda profile: saved_as.append(profile.profile_id))
        dialog.updateRequested.connect(lambda profile: updated.append(profile.profile_id))

        dialog.save_profile_button.click()
        dialog.profile_selector.setCurrentIndex(
            dialog.profile_selector.findData(user_profile.profile_id)
        )
        dialog.save_profile_button.click()

        self.assertEqual(saved_as, [builtin.profile_id])
        self.assertEqual(updated, [user_profile.profile_id])

    def test_applying_profile_stores_snapshot_and_primary_wavelength(self) -> None:
        pattern = Pattern.create("sample")
        profile = InstrumentProfile(
            profile_id="co-lab",
            radiation=RadiationProfile.custom_monochromatic(1.78897, label="Co K-alpha1"),
        )

        apply_profile_snapshot([pattern], profile)

        self.assertEqual(pattern.instrument_profile["profile_id"], "co-lab")
        self.assertAlmostEqual(pattern.wavelength or 0.0, 1.78897)

    def test_applying_profile_requests_local_candidate_reranking(self) -> None:
        pattern = Pattern.create("sample")

        class Settings:
            def setValue(self, _key, _value):
                pass

        class Signal:
            def emit(self):
                pass

        class Project:
            patterns = [pattern]

            def touch(self):
                pass

        class Owner(PhaseFinderInstrumentProfileActionsMixin):
            settings = Settings()
            project = Project()
            project_changed = Signal()
            profile_states = {}
            match_profile_result_cache = {}
            rerank_requests = 0

            @staticmethod
            def _patterns_for_instrument_profile(*, selected):
                return [pattern]

            @staticmethod
            def _invalidate_match_profile_cache():
                pass

            @staticmethod
            def _refresh_instrument_profile_selector():
                pass

            @staticmethod
            def _refresh_observed_pattern_plot():
                pass

            @staticmethod
            def _recalculate_match_profile():
                pass

            def _rerank_loaded_candidates_for_instrument_change(self):
                self.rerank_requests += 1

        owner = Owner()
        owner._apply_instrument_profile(InstrumentProfile.default_cu_kalpha(), selected=False)

        self.assertEqual(owner.rerank_requests, 1)

    def test_instrument_change_reranks_visible_candidates_without_search(self) -> None:
        class Table:
            @staticmethod
            def all_row_values():
                return [
                    {
                        "Source": "COD",
                        "Entry": "1000001",
                        "Formula": "Si O2",
                        "Phase": "Quartz",
                        "Sp. gr.": "P 31 2 1",
                        "Match (%)": "72%",
                        "Gain (%)": "",
                        "I/Ic": "",
                    }
                ]

        class Owner(PhaseFinderCandidateSearchActionsMixin):
            candidate_table = Table()
            match_candidates = []

            def _candidate_state_rows(self, candidates):
                return [
                    [
                        candidate.get("Source", ""),
                        candidate.get("Entry", ""),
                        candidate.get("Formula", ""),
                        candidate.get("Phase", ""),
                        candidate.get("Sp. gr.", ""),
                        candidate.get("Match (%)", ""),
                        candidate.get("Gain (%)", ""),
                        candidate.get("I/Ic", ""),
                    ]
                    for candidate in candidates
                ]

            def _set_candidate_rows(self, rows, **kwargs):
                self.ranked_rows = rows
                self.rank_options = kwargs

        owner = Owner()
        owner._rerank_loaded_candidates_for_instrument_change()

        self.assertEqual(owner.ranked_rows[0][1], "1000001")
        self.assertTrue(owner.rank_options["force_rank"])

    def test_selector_shows_unsaved_active_radiation_instead_of_builtin_copy(self) -> None:
        builtin = InstrumentProfile.default_cu_kalpha()
        active = InstrumentProfile(
            profile_id=builtin.profile_id,
            identity=builtin.identity,
            radiation=radiation_profile_from_tube("Co"),
            geometry=builtin.geometry,
            detector=builtin.detector,
            resolution=builtin.resolution,
        )

        class ActionBar:
            def set_instrument_profiles(self, profiles, active_id):
                self.profiles = profiles
                self.active_id = active_id

        class Library:
            def list_profiles(self):
                return (builtin,)

            def get(self, profile_id):
                return builtin if profile_id == builtin.profile_id else None

        class Owner(PhaseFinderInstrumentProfileActionsMixin):
            finder_action_bar = ActionBar()
            instrument_profile_library = Library()

            @staticmethod
            def _active_instrument_profile():
                return active

        owner = Owner()
        owner._refresh_instrument_profile_selector()

        self.assertEqual(owner.finder_action_bar.active_id, builtin.profile_id)
        self.assertIn((builtin.profile_id, "Cu K-alpha default [Co]"), owner.finder_action_bar.profiles)

    def test_only_constant_resolution_is_exposed_to_legacy_finder(self) -> None:
        constant = InstrumentProfile(
            resolution=ResolutionProfile(constant_fwhm_deg=0.23),
        )
        tch = InstrumentProfile(
            resolution=ResolutionProfile.tch(u=0.1, v=-0.02, w=0.03, x=0.04, y=0.05),
        )

        self.assertAlmostEqual(legacy_constant_fwhm(constant) or 0.0, 0.23)
        self.assertIsNone(legacy_constant_fwhm(tch))

    def test_legacy_radiation_settings_preserve_selected_mode(self) -> None:
        doublet = InstrumentProfile()
        kalpha1 = InstrumentProfile(
            radiation=RadiationProfile(
                target="Cu",
                mode="kalpha1_only",
                components=(doublet.radiation.components[0],),
            ),
        )
        monochromatic = InstrumentProfile(
            radiation=RadiationProfile.custom_monochromatic(0.71073, label="Mo K-alpha1"),
        )

        self.assertEqual(legacy_radiation_settings(doublet), (1.54056, True))
        self.assertEqual(legacy_radiation_settings(kalpha1), (1.54056, False))
        self.assertEqual(legacy_radiation_settings(monochromatic), (0.71073, False))


if __name__ == "__main__":
    unittest.main()
