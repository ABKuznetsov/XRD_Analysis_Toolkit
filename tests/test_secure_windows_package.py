from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from xrd_finder.tools.secure_windows_package import (
    copy_secure_tree,
    secure_stage_root,
    write_secure_mode_settings,
    write_secure_inno_script,
)


class SecureWindowsPackageTests(unittest.TestCase):
    def test_secure_data_overlay_forces_offline_mode_and_excludes_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source"
            target = tmp_path / "target"
            (source / "settings").mkdir(parents=True)
            (source / "settings" / "security.json").write_text(
                json.dumps({"offline_mode": False, "keep": "value"}),
                encoding="utf-8",
            )
            (source / "cod_cache").mkdir()
            (source / "cod_cache" / "index.sqlite").write_text("sqlite", encoding="utf-8")
            (source / "logs").mkdir()
            (source / "logs" / "xrd_finder_console.log").write_text("log", encoding="utf-8")
            (source / "__pycache__").mkdir()
            (source / "__pycache__" / "noise.pyc").write_bytes(b"pyc")
            (source / "download.part").write_text("partial", encoding="utf-8")

            copy_secure_tree(source, target)
            settings_path = write_secure_mode_settings(target)

            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIs(payload["offline_mode"], True)
            self.assertEqual(payload["keep"], "value")
            self.assertEqual(payload["source"], "secure Windows installer")
            self.assertTrue((target / "cod_cache" / "index.sqlite").is_file())
            self.assertFalse((target / "logs").exists())
            self.assertFalse((target / "__pycache__").exists())
            self.assertFalse((target / "download.part").exists())

    def test_secure_seed_rejects_venv_without_base_python(self) -> None:
        from xrd_finder.tools.secure_windows_package import _prepare_secure_seed

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sci_root = tmp_path / "Sci"
            env_dir = sci_root / "env"
            (env_dir / "Scripts").mkdir(parents=True)
            (env_dir / "Scripts" / "python.exe").write_bytes(b"launcher")
            (env_dir / "pyvenv.cfg").write_text(
                "home = C:\\missing\\Python311\nversion = 3.11.9\n",
                encoding="utf-8",
            )
            data_root = tmp_path / "data"

            with self.assertRaisesRegex(RuntimeError, "base Python runtime"):
                _prepare_secure_seed(
                    tmp_path / "seed",
                    sci_root=sci_root,
                    data_root=data_root,
                    progress=None,
                )

    def test_inno_script_installs_prepared_runtime_and_data_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script_path = tmp_path / "secure.iss"
            app_root = tmp_path / "app"
            seed_root = tmp_path / "seed"
            output_dir = tmp_path / "dist"

            write_secure_inno_script(
                script_path,
                app_root=app_root,
                seed_root=seed_root,
                output_dir=output_dir,
                version="1.6.2",
            )

            script = script_path.read_text(encoding="utf-8")
            self.assertIn("OutputBaseFilename=XRD_Phase_Finder_Secure_Windows_1_6_2", script)
            self.assertIn("AppId={{7F3F4D7E-1E5B-4B54-B8B1-8C5D4F4A0101}", script)
            self.assertIn("AppName={#MyAppName}", script)
            self.assertIn('Source: "' + str(app_root / "*") + '"', script)
            self.assertIn('Source: "' + str(seed_root / "Sci" / "*") + '"', script)
            self.assertIn('DestDir: "{localappdata}\\Sci"', script)
            self.assertIn("apply_secure_windows_seed.ps1", script)
            self.assertNotIn("releases/download", script)

    def test_secure_stage_root_uses_short_temp_path_not_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "very" / "long" / "nested" / "output"
            stage = secure_stage_root(output_dir)

            self.assertNotIn(str(output_dir), str(stage))
            self.assertIn("xrd_secure_windows_setup", str(stage))


if __name__ == "__main__":
    unittest.main()



