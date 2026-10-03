from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from xrd_finder.tools.secure_macos_installer import (
    _prepare_secure_seed,
    copy_secure_tree,
    write_secure_mode_settings,
)


class SecureMacosInstallerTests(unittest.TestCase):
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
            (source / ".DS_Store").write_text("finder", encoding="utf-8")
            (source / "download.part").write_text("partial", encoding="utf-8")
            conflict_copy = source / "module (копия с компьютера DESKTOP-S23DO39).py"
            conflict_copy.write_text("stale code", encoding="utf-8")

            copy_secure_tree(source, target)
            settings_path = write_secure_mode_settings(target)

            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIs(payload["offline_mode"], True)
            self.assertEqual(payload["keep"], "value")
            self.assertTrue((target / "cod_cache" / "index.sqlite").is_file())
            self.assertFalse((target / "logs").exists())
            self.assertFalse((target / "__pycache__").exists())
            self.assertFalse((target / ".DS_Store").exists())
            self.assertFalse((target / "download.part").exists())
            self.assertFalse((target / conflict_copy.name).exists())

    def test_secure_seed_does_not_bundle_user_settings_keys_or_databases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sci_root = tmp_path / "Sci"
            env_dir = sci_root / "env-arm64"
            (env_dir / "bin").mkdir(parents=True)
            (env_dir / "bin" / "python").write_bytes(b"runtime")
            data_root = tmp_path / "personal-data"
            (data_root / "settings" / "qt" / "Xrdfinder").mkdir(parents=True)
            (data_root / "settings" / "qt" / "Xrdfinder" / "Standalone.ini").write_text(
                "api_key=SECRET\n", encoding="utf-8"
            )
            (data_root / "cod_cache").mkdir()
            (data_root / "cod_cache" / "index.sqlite").write_bytes(b"personal database")

            seed_root = tmp_path / "seed"
            _prepare_secure_seed(
                seed_root,
                sci_root=sci_root,
                data_root=data_root,
                progress=None,
            )

            installed_data = seed_root / "Sci" / "apps" / "xrd_phase_finder" / "data"
            self.assertTrue((installed_data / "settings" / "security.json").is_file())
            self.assertFalse((installed_data / "settings" / "qt").exists())
            self.assertFalse((installed_data / "cod_cache").exists())


if __name__ == "__main__":
    unittest.main()
