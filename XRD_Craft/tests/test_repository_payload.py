from __future__ import annotations

from pathlib import Path


CRAFT_ROOT = Path(__file__).resolve().parents[1]


def test_required_runtime_payload_is_present() -> None:
    required = (
        "src/crystal_viewer/app.py",
        "assets",
        "examples",
        "pyproject.toml",
        "README.md",
        "ARCHITECTURE.md",
        "run_viewer.bat",
        "run_viewer_silent.vbs",
        "run_viewer.command",
        "toolkit/setup_sci_env.bat",
        "toolkit/requirements-windows.txt",
    )

    missing = [relative for relative in required if not (CRAFT_ROOT / relative).exists()]

    assert missing == []


def test_generated_and_private_artifacts_are_not_imported() -> None:
    forbidden_directory_names = {
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "venv",
    }
    forbidden_suffixes = {".exe", ".pyc", ".pyo"}
    violations: list[str] = []

    for path in CRAFT_ROOT.rglob("*"):
        relative = path.relative_to(CRAFT_ROOT).as_posix()
        if relative == "tests/__pycache__" or relative.startswith("tests/__pycache__/"):
            # Pytest may create bytecode for this contract test itself. The
            # imported source tree is checked independently below.
            continue
        if path.is_dir() and path.name.casefold() in forbidden_directory_names:
            violations.append(relative)
        elif path.is_file() and path.suffix.casefold() in forbidden_suffixes:
            violations.append(relative)
        elif path.is_dir() and relative.casefold() == "docs/superpowers":
            violations.append(relative)

    assert violations == []
