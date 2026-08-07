from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.phase import Phase
from xrd_finder.core.project import Project
from xrd_finder.core.series import SeriesAnalysis
from xrd_finder.core.structure import Structure
from xrd_finder.io.project_io import load_project_manifest, save_project_manifest


class PortableProjectIoTest(unittest.TestCase):
    def test_xpff_embeds_xrd_cif_and_project_state(self) -> None:
        with TemporaryDirectory() as directory:
            self._assert_portable_round_trip(Path(directory))

    def _assert_portable_round_trip(self, tmp_path: Path) -> None:
        xrd_path = tmp_path / "sample with spaces.xy"
        cif_path = tmp_path / "user phase.cif"
        xrd_path.write_text("10 100\n20 200\n", encoding="utf-8")
        cif_path.write_text("data_test\n_cell_length_a 1\n", encoding="utf-8")

        pattern = Pattern.create("Sample", str(xrd_path))
        phase = Phase.create("User phase", str(cif_path))
        structure = Structure.create("User phase", str(cif_path))
        structure.phase_id = phase.id
        series = SeriesAnalysis.create("Series 1")
        series.pattern_ids = [pattern.id]
        series.phase_ids = [phase.id]
        project = Project(
            name="Portable project",
            patterns=[pattern],
            phases=[phase],
            structures=[structure],
            series=[series],
        )
        project.finder_state.checked_pattern_ids = [pattern.id]
        project.finder_state.checked_phase_ids = [phase.id]
        project.finder_state.phase_colors = {phase.id: "#123456"}
        project.finder_state.profile_states = {pattern.id: {"marker_scale": 1.5}}

        target = tmp_path / "portable project.xpff"
        save_project_manifest(project, target)
        xrd_path.unlink()
        cif_path.unlink()

        with zipfile.ZipFile(target) as archive:
            names = set(archive.namelist())
            self.assertIn("project.json", names)
            self.assertTrue(any(name.startswith("assets/xrd/") for name in names))
            self.assertTrue(any(name.startswith("assets/cif/") for name in names))

        restored = load_project_manifest(target)
        self.assertEqual(restored.root_path, str(target))
        self.assertTrue(Path(restored.patterns[0].source_path).read_text(encoding="utf-8").startswith("10 100"))
        self.assertTrue(Path(restored.phases[0].source_path).read_text(encoding="utf-8").startswith("data_test"))
        self.assertEqual(restored.structures[0].source_path, restored.phases[0].source_path)
        self.assertEqual(restored.series[0].pattern_ids, [pattern.id])
        self.assertEqual(restored.finder_state.phase_colors, {phase.id: "#123456"})
        self.assertEqual(restored.finder_state.profile_states[pattern.id]["marker_scale"], 1.5)


if __name__ == "__main__":
    unittest.main()
