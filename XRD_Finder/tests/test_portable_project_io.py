from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.phase import Phase
from xrd_finder.core.project import Project
from xrd_finder.core.series import SeriesAnalysis
from xrd_finder.core.structure import Structure
from xrd_finder.io import project_io
from xrd_finder.io.project_io import _extract_portable_member, load_project_manifest, save_project_manifest


class PortableProjectIoTest(unittest.TestCase):
    def test_xpff_rejects_unsafe_asset_member_paths_before_file_io(self) -> None:
        """Fails if native path parsing can reinterpret a crafted ZIP member."""

        class ArchiveMustNotBeOpened:
            def __init__(self) -> None:
                self.opened: list[str] = []

            def open(self, member: str, mode: str):
                self.opened.append(member)
                raise AssertionError(f"unsafe member reached archive I/O: {member}")

        malicious_members = [
            "not-assets/phase.cif",
            "/assets/absolute.cif",
            "assets\\backslash.cif",
            "assets/..\\escape.cif",
            "assets/C:drive-relative.cif",
            "assets/C:/drive-absolute.cif",
            "assets/name:stream.cif",
            "assets//empty-component.cif",
            "assets/./dot-component.cif",
            "assets/../parent-component.cif",
            "assets/",
        ]
        archive = ArchiveMustNotBeOpened()
        with TemporaryDirectory() as directory, patch.object(Path, "mkdir") as mkdir:
            root = Path(directory) / "extracted"
            for member in malicious_members:
                with self.subTest(member=member):
                    with self.assertRaisesRegex(ValueError, r"Unsafe file path"):
                        _extract_portable_member(archive, member, root)  # type: ignore[arg-type]

        self.assertEqual(archive.opened, [])
        mkdir.assert_not_called()

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

    def test_xpff_embeds_shared_match_candidate_cif_without_project_phase(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            first_xrd_path = tmp_path / "first.xy"
            second_xrd_path = tmp_path / "second.xy"
            cif_path = tmp_path / "candidate.cif"
            first_xrd_path.write_text("10 100\n20 200\n", encoding="utf-8")
            second_xrd_path.write_text("10 80\n20 160\n", encoding="utf-8")
            cif_path.write_text("data_basio3\n_cell_length_a 1\n", encoding="utf-8")
            first_pattern = Pattern.create("First", str(first_xrd_path))
            second_pattern = Pattern.create("Second", str(second_xrd_path))
            candidate_key = "USER:BaSiO3"
            candidate = {"Source": "USER", "Entry": "BaSiO3", "Name": "BaSiO3"}
            project = Project(name="Candidate-only project", patterns=[first_pattern, second_pattern])
            project.finder_state.match_candidates = [candidate]
            project.finder_state.profile_states = {
                first_pattern.id: {"candidates": [candidate]},
                second_pattern.id: {"candidates": [candidate]},
            }
            project.finder_state.candidate_cif_paths = {candidate_key: str(cif_path)}

            target = tmp_path / "candidate-only.xpff"
            save_project_manifest(project, target)
            cif_path.unlink()

            with zipfile.ZipFile(target) as archive:
                candidate_members = [name for name in archive.namelist() if name.startswith("assets/candidates/")]
            self.assertEqual(len(candidate_members), 1)

            restored = load_project_manifest(target)
            extracted_path = Path(restored.finder_state.candidate_cif_paths[candidate_key])
            self.assertTrue(extracted_path.is_file())
            self.assertEqual(extracted_path.read_text(encoding="utf-8"), "data_basio3\n_cell_length_a 1\n")
            for pattern in (first_pattern, second_pattern):
                restored_candidate = restored.finder_state.profile_states[pattern.id]["candidates"][0]
                self.assertEqual(f"{restored_candidate['Source']}:{restored_candidate['Entry']}", candidate_key)

    def test_xpff_manifest_without_candidate_cif_paths_uses_empty_mapping(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "legacy.xpff"
            data = {"name": "Legacy project", "patterns": [], "phases": [], "structures": [], "series": {}, "finder_state": {}}
            with zipfile.ZipFile(target, mode="w") as archive:
                archive.writestr("project.json", json.dumps(data))

            restored = load_project_manifest(target)

            self.assertEqual(restored.finder_state.candidate_cif_paths, {})

    def test_xpff_save_rejects_missing_project_collection_assets_atomically(self) -> None:
        """Fails if a non-empty project asset path survives as a machine-local path."""
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            missing_path = tmp_path / "missing-source.dat"
            cases = [
                (
                    "pattern",
                    Project(name="Missing pattern asset", patterns=[Pattern.create("Missing pattern", str(missing_path))]),
                    "Missing pattern",
                ),
                (
                    "phase",
                    Project(name="Missing phase asset", phases=[Phase.create("Missing phase", str(missing_path))]),
                    "Missing phase",
                ),
                (
                    "structure",
                    Project(
                        name="Missing structure asset",
                        structures=[Structure.create("Missing structure", str(missing_path))],
                    ),
                    "Missing structure",
                ),
            ]

            for label, project, display_name in cases:
                with self.subTest(collection=label):
                    target = tmp_path / f"existing-{label}.xpff"
                    target.write_bytes(b"previous project")

                    with self.assertRaisesRegex(ValueError, rf"{display_name}.*missing-source\.dat"):
                        save_project_manifest(project, target)

                    self.assertEqual(target.read_bytes(), b"previous project")

    def test_xpff_save_keeps_existing_file_when_candidate_cif_is_missing(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            target = tmp_path / "existing.xpff"
            target.write_bytes(b"previous project")
            candidate_key = "USER:Missing"
            missing_path = tmp_path / "missing.cif"
            project = Project(name="Missing candidate CIF")
            project.finder_state.match_candidates = [{"Source": "USER", "Entry": "Missing"}]
            project.finder_state.candidate_cif_paths = {candidate_key: str(missing_path)}

            with self.assertRaisesRegex(ValueError, r"USER:Missing.*missing\.cif"):
                save_project_manifest(project, target)

            self.assertEqual(target.read_bytes(), b"previous project")

    def test_xpff_ignores_unreferenced_missing_candidate_cif_mapping(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            live_path = tmp_path / "live.cif"
            live_path.write_text("data_live\n", encoding="utf-8")
            live_candidate = {"Source": "USER", "Entry": "Live"}
            project = Project(name="Live candidate only")
            project.finder_state.match_candidates = [live_candidate]
            project.finder_state.candidate_cif_paths = {
                "USER:Live": str(live_path),
                "USER:Stale": str(tmp_path / "missing.cif"),
            }

            target = tmp_path / "live-only.xpff"
            save_project_manifest(project, target)

            with zipfile.ZipFile(target) as archive:
                candidate_members = [name for name in archive.namelist() if name.startswith("assets/candidates/")]
            self.assertEqual(len(candidate_members), 1)
            restored = load_project_manifest(target)
            self.assertEqual(set(restored.finder_state.candidate_cif_paths), {"USER:Live"})

    def test_xpff_uses_distinct_members_for_colliding_candidate_keys(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            first_path = tmp_path / "first.cif"
            second_path = tmp_path / "second.cif"
            first_path.write_text("data_first\n", encoding="utf-8")
            second_path.write_text("data_second\n", encoding="utf-8")
            first_key = "USER:A/B"
            second_key = "USER:A_B"
            project = Project(name="Colliding candidate keys")
            project.finder_state.match_candidates = [
                {"Source": "USER", "Entry": "A/B"},
                {"Source": "USER", "Entry": "A_B"},
            ]
            project.finder_state.candidate_cif_paths = {first_key: str(first_path), second_key: str(second_path)}

            target = tmp_path / "colliding-keys.xpff"
            save_project_manifest(project, target)
            first_path.unlink()
            second_path.unlink()

            with zipfile.ZipFile(target) as archive:
                candidate_members = [name for name in archive.namelist() if name.startswith("assets/candidates/")]
            self.assertEqual(len(candidate_members), 2)
            self.assertEqual(len(set(candidate_members)), 2)
            restored = load_project_manifest(target)
            self.assertEqual(Path(restored.finder_state.candidate_cif_paths[first_key]).read_text(encoding="utf-8"), "data_first\n")
            self.assertEqual(Path(restored.finder_state.candidate_cif_paths[second_key]).read_text(encoding="utf-8"), "data_second\n")

    def test_path_deduplication_uses_platform_case_normalization(self) -> None:
        """Fails if case-sensitive platforms merge paths that differ only by case."""
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            first_path = tmp_path / "first.cif"
            second_path = tmp_path / "second.cif"
            first_path.write_bytes(b"data_upper\n")
            second_path.write_bytes(b"data_lower\n")
            mapping = {"USER:Upper": str(first_path), "USER:Lower": str(second_path)}
            archive_path = tmp_path / "paths.zip"

            def case_distinct_resolve(path: Path, *args, **kwargs) -> Path:
                if path == first_path:
                    return Path("Z:/Case/Phase.cif")
                if path == second_path:
                    return Path("Z:/case/phase.cif")
                return path.absolute()

            with zipfile.ZipFile(archive_path, mode="w") as archive:
                with (
                    patch.object(Path, "resolve", autospec=True, side_effect=case_distinct_resolve),
                    patch.object(project_io.os.path, "normcase", side_effect=lambda value: value),
                ):
                    project_io._embed_path_mapping(archive, mapping, "candidates", ".cif", {})

            self.assertNotEqual(mapping["USER:Upper"], mapping["USER:Lower"])
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.read(mapping["USER:Upper"]), b"data_upper\n")
                self.assertEqual(archive.read(mapping["USER:Lower"]), b"data_lower\n")


if __name__ == "__main__":
    unittest.main()
