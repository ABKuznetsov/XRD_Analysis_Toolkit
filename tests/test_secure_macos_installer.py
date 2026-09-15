from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from xrd_finder.tools.secure_macos_installer import (
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


if __name__ == "__main__":
    unittest.main()
