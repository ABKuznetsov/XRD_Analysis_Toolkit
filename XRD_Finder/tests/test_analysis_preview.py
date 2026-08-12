from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from xrd_finder.ui.analysis_preview import capture_analysis_preview


class _FakeImage:
    def isNull(self) -> bool:
        return False

    def save(self, path: str, _format: str) -> bool:
        Path(path).write_bytes(b"preview-png")
        return True


class AnalysisPreviewTest(unittest.TestCase):
    def test_capture_writes_stable_pattern_preview(self) -> None:
        with TemporaryDirectory() as directory:
            path = capture_analysis_preview(
                _FakeImage(),
                cache_root=directory,
                project_id="project:1",
                pattern_id="pattern/1",
            )

            self.assertTrue(Path(path).is_file())
            self.assertEqual(Path(path).read_bytes(), b"preview-png")
            self.assertEqual(Path(path).suffix, ".png")

    def test_null_image_is_not_recorded(self) -> None:
        image = _FakeImage()
        image.isNull = lambda: True
        with TemporaryDirectory() as directory:
            self.assertIsNone(
                capture_analysis_preview(
                    image,
                    cache_root=directory,
                    project_id="project-1",
                    pattern_id="pattern-1",
                )
            )


if __name__ == "__main__":
    unittest.main()
