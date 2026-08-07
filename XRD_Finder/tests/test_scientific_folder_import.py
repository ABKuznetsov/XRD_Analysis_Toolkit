from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.project import Project
from xrd_finder.core.series import SeriesAnalysis
from xrd_finder.io.scientific_folder_import import (
    collect_scientific_folder_groups,
    unique_series_name,
)
from xrd_finder.io.project_io import load_project_manifest, save_project_manifest
from xrd_finder.ui.analysis_windows import AnalysisWindow
from xrd_finder.ui.project_tree import ProjectTree


class ScientificFolderGroupingTests(unittest.TestCase):
    def test_root_files_and_each_direct_subfolder_become_separate_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Annealing"
            root.mkdir()
            (root / "initial.xy").write_text("10 1\n11 2\n", encoding="utf-8")
            (root / "notes.pdf").write_text("ignored", encoding="utf-8")

            low = root / "100C"
            low.mkdir()
            (low / "sample.xy").write_text("10 2\n11 3\n", encoding="utf-8")
            (low / "phase.cif").write_text("data_test\n", encoding="utf-8")
            nested = low / "repeat"
            nested.mkdir()
            (nested / "sample.dat").write_text("10 3\n11 4\n", encoding="utf-8")

            high = root / "200C"
            high.mkdir()
            (high / "sample.csv").write_text("10,4\n11,5\n", encoding="utf-8")
            (root / "empty").mkdir()

            groups = collect_scientific_folder_groups(
                root,
                {".xy", ".txt", ".dat", ".csv", ".xye", ".cif"},
            )

            self.assertEqual([group.name for group in groups], ["Annealing", "100C", "200C"])
            self.assertEqual([path.name for path in groups[0].paths], ["initial.xy"])
            self.assertEqual(
                [path.relative_to(low).as_posix() for path in groups[1].paths],
                ["phase.cif", "repeat/sample.dat", "sample.xy"],
            )
            self.assertEqual([path.name for path in groups[2].paths], ["sample.csv"])

    def test_folder_without_supported_files_produces_no_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Empty"
            root.mkdir()
            (root / "readme.pdf").write_text("ignored", encoding="utf-8")
            self.assertEqual(collect_scientific_folder_groups(root, {".xy", ".cif"}), [])

    def test_duplicate_series_name_gets_a_stable_suffix(self) -> None:
        existing = ["Annealing", "100C", "100C (2)"]
        self.assertEqual(unique_series_name("200C", existing), "200C")
        self.assertEqual(unique_series_name("100c", existing), "100c (3)")


class _ImportHarness:
    IMPORT_SUFFIXES = AnalysisWindow.IMPORT_SUFFIXES
    _import_scientific_paths = AnalysisWindow._import_scientific_paths
    _import_scientific_drop_paths = AnalysisWindow._import_scientific_drop_paths
    _drop_file_paths = AnalysisWindow._drop_file_paths

    def __init__(self, project: Project) -> None:
        self.project = project
        self.finalize_count = 0

    def _remember_directory(self, _path: Path) -> None:
        return

    def _series_id_for_new_project_object(self) -> None:
        return None

    def _finalize_scientific_import(self) -> None:
        self.finalize_count += 1


class _LocalUrl:
    def __init__(self, path: Path) -> None:
        self.path = path

    def isLocalFile(self) -> bool:
        return True

    def toLocalFile(self) -> str:
        return str(self.path)


class _MimeData:
    def __init__(self, paths: list[Path]) -> None:
        self._paths = paths

    def hasUrls(self) -> bool:
        return True

    def urls(self) -> list[_LocalUrl]:
        return [_LocalUrl(path) for path in self._paths]


class _DropEvent:
    def __init__(self, paths: list[Path]) -> None:
        self._mime_data = _MimeData(paths)

    def mimeData(self) -> _MimeData:
        return self._mime_data


class ScientificFolderImportIntegrationTests(unittest.TestCase):

    def test_dropped_directory_creates_series_and_assigns_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Annealing"
            root.mkdir()
            (root / "initial.xy").write_text("10 1\n11 2\n", encoding="utf-8")
            child = root / "500C"
            child.mkdir()
            (child / "heated.xy").write_text("10 3\n11 4\n", encoding="utf-8")

            project = Project(name="Folder import")
            harness = _ImportHarness(project)
            harness._import_scientific_drop_paths([root])

            self.assertEqual([series.name for series in project.series], ["Annealing", "500C"])
            self.assertEqual([pattern.name for pattern in project.patterns], ["initial", "heated"])
            self.assertEqual(project.series[0].pattern_ids, [project.patterns[0].id])
            self.assertEqual(project.series[1].pattern_ids, [project.patterns[1].id])
            self.assertEqual(harness.finalize_count, 1)

            project_path = Path(directory) / "folder-import.xpff"
            save_project_manifest(project, project_path)
            restored = load_project_manifest(project_path)
            self.assertEqual([series.name for series in restored.series], ["Annealing", "500C"])
            self.assertEqual([pattern.name for pattern in restored.patterns], ["initial", "heated"])
            self.assertEqual(restored.series[0].pattern_ids, [restored.patterns[0].id])
            self.assertEqual(restored.series[1].pattern_ids, [restored.patterns[1].id])

    def test_drop_path_filter_accepts_directory_and_supported_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pattern = root / "sample.xy"
            pattern.write_text("10 1\n11 2\n", encoding="utf-8")
            unsupported = root / "notes.pdf"
            unsupported.write_text("ignored", encoding="utf-8")
            harness = _ImportHarness(Project(name="Drop filter"))
            accepted = harness._drop_file_paths(_DropEvent([root, pattern, unsupported]))
            self.assertEqual(accepted, [root, pattern])


class ProjectTreeExpansionStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _project() -> Project:
        project = Project(name="Expansion")
        project.series.append(SeriesAnalysis.create("Series 1", kind="collection"))
        return project

    def test_new_series_is_collapsed_by_default(self) -> None:
        tree = ProjectTree()
        tree.set_project(self._project())
        series_item = tree.topLevelItem(0).child(0)
        self.assertFalse(series_item.isExpanded())
        tree.deleteLater()

    def test_saved_expansion_state_round_trips_and_restores(self) -> None:
        project = self._project()
        tree = ProjectTree()
        tree.set_project(project)
        tree.topLevelItem(0).child(0).setExpanded(True)
        project.finder_state = FinderProjectState(tree_expansion_state=tree.expansion_state())

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "expansion.xpff"
            save_project_manifest(project, path)
            restored = load_project_manifest(path)

        restored_tree = ProjectTree()
        restored_tree.set_project(restored)
        restored_tree.restore_expansion_state(restored.finder_state.tree_expansion_state)
        self.assertTrue(restored_tree.topLevelItem(0).child(0).isExpanded())
        self.assertEqual(
            FinderProjectState(**asdict(restored.finder_state)).tree_expansion_state,
            restored.finder_state.tree_expansion_state,
        )
        tree.deleteLater()
        restored_tree.deleteLater()


if __name__ == "__main__":
    unittest.main()
