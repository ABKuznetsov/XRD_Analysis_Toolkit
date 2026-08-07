from __future__ import annotations

import unittest
from pathlib import Path


class WindowsFileAssociationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_root = Path(__file__).resolve().parents[2]
        cls.installer = (
            cls.repository_root / "installer" / "XRD_Analysis_Toolkit.iss"
        ).read_text(encoding="utf-8")
        cls.registration_script_path = (
            cls.repository_root / "toolkit" / "register_xpff_file_type.ps1"
        )
        cls.silent_launcher = (
            cls.repository_root / "XRD_Finder" / "launch_xrd_finder_silent.vbs"
        ).read_text(encoding="utf-8")
        cls.preview_launcher = (
            cls.repository_root / "toolkit" / "launch_xrd_finder_preview.ps1"
        ).read_text(encoding="utf-8")
        cls.finder_gui = (
            cls.repository_root
            / "XRD_Finder"
            / "xrd_finder"
            / "apps"
            / "finder_gui.py"
        ).read_text(encoding="utf-8")

    def test_installer_registers_machine_wide_prog_id_and_capabilities(self) -> None:
        self.assertIn('Root: HKLM; Subkey: "Software\\Classes\\.xpff"', self.installer)
        self.assertIn(
            'Root: HKLM; Subkey: "Software\\Classes\\XRDPhaseFinder.Project"',
            self.installer,
        )
        self.assertIn('Software\\RegisteredApplications', self.installer)
        self.assertIn('Software\\XRDPhaseFinder\\Capabilities\\FileAssociations', self.installer)

    def test_installer_repairs_current_user_association_after_install(self) -> None:
        self.assertIn("register_xpff_file_type.ps1", self.installer)
        self.assertIn("runascurrentuser", self.installer)

    def test_registration_script_has_icon_and_quoted_project_command(self) -> None:
        self.assertTrue(self.registration_script_path.is_file())
        script = self.registration_script_path.read_text(encoding="utf-8")
        self.assertIn("XRDPhaseFinder.Project", script)
        self.assertIn("launch_xrd_finder_silent.vbs", script)
        self.assertIn('"%1"', script)
        self.assertIn("RegisteredApplications", script)
        self.assertIn("SHChangeNotify", script)

    def test_project_path_is_forwarded_through_the_entire_launcher_chain(self) -> None:
        self.assertIn("WScript.Arguments.Count > 0", self.silent_launcher)
        self.assertIn("WScript.Arguments.Item(0)", self.silent_launcher)
        self.assertIn('" -ProjectPath "', self.silent_launcher)

        self.assertIn('[string]$ProjectPath = ""', self.preview_launcher)
        self.assertIn('if ($ProjectPath)', self.preview_launcher)
        self.assertIn(' --project `"$escapedProjectPath`"', self.preview_launcher)

        self.assertIn('parser.add_argument("--project"', self.finder_gui)
        self.assertIn("load_project_manifest(project_path)", self.finder_gui)


if __name__ == "__main__":
    unittest.main()
