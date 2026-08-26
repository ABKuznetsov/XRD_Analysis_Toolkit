from __future__ import annotations

from crystal_viewer.app import startup_path


def test_startup_without_file_opens_empty_session() -> None:
    assert startup_path(["crystal-viewer"]) is None


def test_startup_uses_explicit_existing_file(tmp_path) -> None:
    cif = tmp_path / "sample.cif"
    cif.write_text("data_sample\n", encoding="utf-8")

    assert startup_path(["crystal-viewer", str(cif)]) == cif
