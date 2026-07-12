from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


FORBIDDEN_PARTS = {
    ".git",
    ".DS_Store",
    "__pycache__",
    "__MACOSX",
    "diagnostics_runtime",
}
FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".flag",
    ".signal",
}
FORBIDDEN_PREFIXES = (
    "XRD_Finder/data/",
    "XRD_Finder/xrd_finder/app.py",
    "XRD_Finder/xrd_finder/core/refinement.py",
    "XRD_Finder/xrd_finder/core/series.py",
    "XRD_Finder/xrd_finder/io/exporters.py",
    "XRD_Finder/xrd_finder/services/refinement_service.py",
    "XRD_Finder/xrd_finder/services/thermo_service.py",
    "XRD_Finder/xrd_finder/services/solid_solution_service.py",
    "XRD_Finder/xrd_finder/services/structure_service.py",
    "XRD_Finder/xrd_finder/ui/legacy_windows.py",
    "XRD_Finder/xrd_finder/ui/main_window.py",
)


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)


def require_clean_worktree(root: Path) -> None:
    result = run_git(["status", "--porcelain"], root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    if result.stdout.strip():
        raise RuntimeError(
            "Working tree is not clean. Commit or stash changes before building a release archive."
        )


def project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    return str(data["project"]["version"])


def build_archive(root: Path, output: Path, ref: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(
        [
            "archive",
            "--format=zip",
            "--worktree-attributes",
            f"--output={output}",
            ref,
        ],
        root,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git archive failed")


def bad_archive_members(path: Path) -> list[str]:
    bad = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            normalized = name.replace("\\", "/").rstrip("/")
            path_parts = normalized.split("/")
            parts = set(path_parts)
            suffix = Path(normalized).suffix
            if parts & FORBIDDEN_PARTS or suffix in FORBIDDEN_SUFFIXES:
                bad.append(name)
                continue
            if any(part.startswith("._") for part in path_parts):
                bad.append(name)
                continue
            if normalized.startswith(FORBIDDEN_PREFIXES):
                bad.append(name)
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a clean XRD Phase Finder source archive.")
    parser.add_argument("--ref", default="HEAD", help="Git ref to archive, default: HEAD.")
    parser.add_argument("--output", type=Path, help="Output zip path. Defaults to dist/XRD_Phase_Finder_Source_<version>.zip.")
    parser.add_argument("--allow-dirty", action="store_true", help="Skip the clean-worktree guard. The archive still uses the selected git ref.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if not args.allow_dirty:
        require_clean_worktree(root)

    version = project_version(root)
    output = args.output or root / "dist" / f"XRD_Phase_Finder_Source_{version}.zip"
    output = output.resolve()
    build_archive(root, output, args.ref)

    bad = bad_archive_members(output)
    if bad:
        preview = "\n".join(f"  {name}" for name in bad[:40])
        raise RuntimeError(f"Archive contains forbidden files:\n{preview}")

    print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"release archive failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
