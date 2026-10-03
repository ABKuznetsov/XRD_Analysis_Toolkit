from __future__ import annotations

import json
import gc
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from PySide6.QtCore import QByteArray

from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.ui.app_settings import app_settings
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.settings_transfer import export_user_settings_bundle, import_user_settings_bundle


class UserDataPersistenceTests(unittest.TestCase):
    def test_settings_export_warns_when_api_key_is_included(self) -> None:
        settings = SimpleNamespace(
            value=lambda key, default=None, type=None: (
                "secret-key" if key == "materials_project/api_key" else default
            )
        )
        window = SimpleNamespace(settings=settings)
        with patch(
            "xrd_finder.ui.analysis_windows.QFileDialog.getSaveFileName",
            return_value=("C:/tmp/settings.json", "JSON"),
        ), patch(
            "xrd_finder.ui.analysis_windows.export_user_settings_bundle"
        ), patch(
            "xrd_finder.ui.analysis_windows.QMessageBox.warning"
        ) as warning:
            PhaseFinderWindow._export_user_settings(window)

        self.assertIn("API key", warning.call_args.args[2])
        self.assertIn("do not publish", warning.call_args.args[2])

    def test_imported_api_is_applied_without_opening_database_window(self) -> None:
        class FakeSettings:
            def value(self, key, default=None, type=None):
                values = {
                    "match_pdf2/root": "D:/PDF2",
                    "materials_project/api_key": "imported-key",
                }
                value = values.get(key, default)
                return type(value) if type is not None and value is not None else value

        old_mp = object()
        old_pdf2 = object()
        window = SimpleNamespace(
            settings=None,
            plot_view_settings=None,
            plot_settings_panel=None,
            database_panel=None,
            candidate_search_service=SimpleNamespace(
                materials_project=old_mp,
                match_pdf2=old_pdf2,
            ),
        )
        with patch("xrd_finder.ui.analysis_windows.app_settings", return_value=FakeSettings()), patch(
            "xrd_finder.ui.analysis_windows.PlotViewSettingsWidget.load_saved_default_settings",
            return_value=None,
        ):
            PhaseFinderWindow._reload_imported_user_settings(window)
        self.assertEqual(window.materials_project.api_key, "imported-key")
        self.assertIs(window.candidate_search_service.materials_project, window.materials_project)
        self.assertIs(window.candidate_search_service.match_pdf2, window.match_pdf2)

    def test_standard_windows_installer_does_not_package_or_delete_user_data(self) -> None:
        installer = (
            Path(__file__).resolve().parents[1]
            / "installer"
            / "finder_setup"
            / "XRD_Phase_Finder.iss"
        ).read_text(encoding="utf-8")
        self.assertNotIn('Source: "..\\..\\data', installer)
        self.assertNotIn('Source: "..\\..\\cod_cache', installer)
        self.assertNotIn("Standalone.ini", installer)
        self.assertNotIn("materials_project/api_key", installer)
        self.assertNotIn('{localappdata}\\Sci\\apps\\xrd_phase_finder\\data', installer)
        self.assertIn("data\\*", installer)
        self.assertIn("settings\\*", installer)
        self.assertIn("cod_cache\\*", installer)
        self.assertIn("*копия с компьютера*", installer)
        self.assertIn("*conflicted copy*", installer)
        self.assertIn("*.sqlite", installer)

    def test_settings_bundle_roundtrip_includes_database_settings_api_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_data_root = os.environ.get("XRD_FINDER_DATA_DIR")
            os.environ["XRD_FINDER_DATA_DIR"] = str(root / "appdata")
            profile_path = root / "appdata" / "settings" / "instrument_profiles.json"
            profile_path.parent.mkdir(parents=True)
            profile_payload = {"schema_version": 1, "profiles": []}
            profile_path.write_text(json.dumps(profile_payload), encoding="utf-8")
            try:
                settings = app_settings()
                settings.clear()
                settings.setValue("materials_project/api_key", "test-secret-key")
                settings.setValue("materials_project/enabled", True)
                settings.setValue("sources/cod_online", False)
                settings.setValue("sources/user_library", True)
                settings.setValue("match_pdf2/root", "D:/PDF2")
                settings.setValue("layout/window_geometry", QByteArray(b"geometry"))
                settings.setValue("plot/default_view", '{"grid": true}')
                settings.sync()

                bundle = root / "settings.json"
                with patch(
                    "xrd_finder.ui.settings_transfer.default_instrument_profile_library_path",
                    return_value=profile_path,
                ):
                    export_user_settings_bundle(bundle)
                    settings.clear()
                    settings.sync()
                    import_user_settings_bundle(bundle)

                restored = app_settings()
                self.assertEqual(restored.value("materials_project/api_key", type=str), "test-secret-key")
                self.assertTrue(restored.value("materials_project/enabled", type=bool))
                self.assertFalse(restored.value("sources/cod_online", type=bool))
                self.assertTrue(restored.value("sources/user_library", type=bool))
                self.assertEqual(restored.value("match_pdf2/root", type=str), "D:/PDF2")
                self.assertEqual(restored.value("layout/window_geometry"), QByteArray(b"geometry"))
                self.assertEqual(restored.value("plot/default_view", type=str), '{"grid": true}')
            finally:
                settings = app_settings()
                settings.clear()
                settings.sync()
                if old_data_root is None:
                    os.environ.pop("XRD_FINDER_DATA_DIR", None)
                else:
                    os.environ["XRD_FINDER_DATA_DIR"] = old_data_root

    def test_phase_library_roundtrip_keeps_cif_derived_data_and_sql_peak_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_cache = LocalPhaseCache(root / "source")
            payload = {
                "schema_version": 1,
                "application": "XRD Phase Finder",
                "library": "phase_library",
                "sources": ["USER", "COD", "MP"],
                "entries": [],
            }
            for index, source in enumerate(("USER", "COD", "MP"), start=1):
                payload["entries"].append({
                    "source": source,
                    "entry_id": str(index),
                    "formula": "CaCO3",
                    "name": f"phase-{index}",
                    "spacegroup": "R-3c",
                    "source_text": "test",
                    "cif_text": "data_test\n_cell_length_a 5.0\n",
                    "a": 5.0,
                    "b": 5.0,
                    "c": 5.0,
                    "atoms_json": "[]",
                    "iic": 1.25,
                    "peaks_json": json.dumps([{
                        "two_theta": 20.0 + index,
                        "d": 4.0,
                        "intensity": 100.0,
                        "raw_intensity": 100.0,
                        "h": 1,
                        "k": 0,
                        "l": 0,
                        "multiplicity": 2,
                    }]),
                    "top_peaks_json": json.dumps([[20.0 + index, 1.0]]),
                    "derived_version": 9,
                })
            incoming = root / "incoming.json"
            incoming.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(source_cache.import_phase_library(incoming), 3)

            exported = root / "exported.json"
            self.assertEqual(
                source_cache.export_phase_library(exported, sources=["USER", "COD", "MP"]),
                3,
            )
            restored_cache = LocalPhaseCache(root / "restored")
            self.assertEqual(restored_cache.import_phase_library(exported), 3)
            self.assertEqual(restored_cache.peak_indexed_count(), 3)
            for index, source in enumerate(("USER", "COD", "MP"), start=1):
                restored = restored_cache.get(source, str(index))
                self.assertIsNotNone(restored)
                self.assertEqual(restored.derived_version, 9)
                self.assertEqual(restored.iic, 1.25)
                self.assertTrue(restored.peaks_json)
                self.assertEqual(len(restored_cache.peak_records(source, str(index))), 1)
            del source_cache, restored_cache
            gc.collect()

if __name__ == "__main__":
    unittest.main()
