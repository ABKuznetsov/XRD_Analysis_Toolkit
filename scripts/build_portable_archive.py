from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import sqlite3
import subprocess
import sys
import tomllib
import zipfile


EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__MACOSX",
    "__pycache__",
    "build",
    "dist",
    "pkgbuild",
    "venv",
}
EXCLUDED_DIRECTORY_PREFIXES = {
    PurePosixPath("XRD_Finder/benchmark_results"),
    PurePosixPath("XRD_Finder/data"),
    PurePosixPath("manuscript_assets"),
    PurePosixPath("scripts/manuscript"),
}
EXCLUDED_FILE_NAMES = {
    ".DS_Store",
    "Entry_96-100-0018.cif",
    "xrd_finder.zip",
}
EXCLUDED_SUFFIXES = {
    ".flag",
    ".log",
    ".pyc",
    ".pyo",
    ".signal",
}
INCLUDED_EXACT_FILES = {
    PurePosixPath(".gitattributes"),
    PurePosixPath(".gitignore"),
    PurePosixPath("BUILD_INFO.txt"),
    PurePosixPath("CHANGELOG.md"),
    PurePosixPath("LICENSE"),
    PurePosixPath("MANIFEST.in"),
    PurePosixPath("PORTABLE_CHANGES.md"),
    PurePosixPath("PORTABLE_README.md"),
    PurePosixPath("README.md"),
    PurePosixPath("THIRD_PARTY_DATA_SOURCES.md"),
    PurePosixPath("pyproject.toml"),
    PurePosixPath("scripts/build_portable_archive.py"),
    PurePosixPath("setup_env.bat"),
    PurePosixPath("toolkit/launch_xrd_finder_preview.ps1"),
    PurePosixPath("toolkit/launch_xrd_finder_preview_macos.py"),
    PurePosixPath("toolkit/manifest.json"),
    PurePosixPath("toolkit/setup_sci_env.bat"),
    PurePosixPath("XRD_Finder/app.json"),
    PurePosixPath("XRD_Finder/install_windows_runtime_direct.bat"),
    PurePosixPath("XRD_Finder/launch_xrd_finder.bat"),
    PurePosixPath("XRD_Finder/launch_xrd_finder_silent.vbs"),
    PurePosixPath("XRD_Finder/requirements-dev.txt"),
    PurePosixPath("XRD_Finder/requirements-optional.txt"),
    PurePosixPath("XRD_Finder/requirements.txt"),
    PurePosixPath("XRD_Finder/run_finder.bat"),
    PurePosixPath("XRD_Finder/run_finder.command"),
    PurePosixPath("XRD_Finder/run_finder.sh"),
    PurePosixPath("XRD_Finder/run_finder_cli.bat"),
    PurePosixPath("XRD_Finder/run_finder_cli.command"),
    PurePosixPath("XRD_Finder/run_finder_cli.sh"),
    PurePosixPath("XRD_Finder/run_finder_silent.vbs"),
    PurePosixPath("XRD_Finder/scripts/benchmark_gain_snr.py"),
    PurePosixPath("XRD_Finder/scripts/benchmark_match_gain.py"),
}
INCLUDED_DIRECTORY_PREFIXES = {
    PurePosixPath("XRD_Finder/tests"),
    PurePosixPath("XRD_Finder/xrd_finder"),
}
BENCHMARK_RESULT_DIRECTORIES = (
    "match_gain_literature_v12",
    "gain_snr_literature_v12",
)
BENCHMARK_RESULT_FILES = {
    "README.md",
    "cases.csv",
    "gain_steps.csv",
    "negative_controls.csv",
    "results.csv",
    "snr_cases.csv",
    "summary.json",
}
COD_FIXTURE_TARGET = PurePosixPath(
    "XRD_Finder/tests/fixtures/cod_benchmark.sqlite"
)


def project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def git_text(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def is_under(path: PurePosixPath, parent: PurePosixPath) -> bool:
    return path == parent or parent in path.parents


def should_include(relative: PurePosixPath) -> bool:
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts[:-1]):
        return False
    if any(is_under(relative, prefix) for prefix in EXCLUDED_DIRECTORY_PREFIXES):
        return False
    if relative.name in EXCLUDED_FILE_NAMES:
        return False
    if relative.name.startswith("._"):
        return False
    if relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return relative in INCLUDED_EXACT_FILES or any(
        is_under(relative, prefix) for prefix in INCLUDED_DIRECTORY_PREFIXES
    )


def source_files(root: Path) -> list[tuple[Path, PurePosixPath]]:
    files: list[tuple[Path, PurePosixPath]] = []
    for directory, directory_names, file_names in os.walk(root):
        current = Path(directory)
        relative_directory = PurePosixPath(current.relative_to(root).as_posix())
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in EXCLUDED_DIRECTORY_NAMES
            and not any(
                is_under(relative_directory / name, prefix)
                for prefix in EXCLUDED_DIRECTORY_PREFIXES
            )
        )
        for name in sorted(file_names):
            path = current / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if path.is_file() and should_include(relative):
                files.append((path, relative))
    return files


def cod_fixture_source(root: Path) -> Path:
    candidates = (
        root / COD_FIXTURE_TARGET,
        Path.home()
        / "Library"
        / "Application Support"
        / "Sci"
        / "apps"
        / "xrd_phase_finder"
        / "data"
        / "cod_cache"
        / "index.sqlite",
        root / "XRD_Finder" / "data" / "cod_cache" / "index.sqlite",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            with sqlite3.connect(candidate) as connection:
                indexed = connection.execute(
                    """
                    select count(distinct source || ':' || entry_id)
                    from phase_peaks
                    """
                ).fetchone()[0]
        except sqlite3.Error:
            continue
        if int(indexed) >= 20:
            return candidate
    raise FileNotFoundError(
        "A COD cache with at least 20 peak-indexed candidates is required "
        "to build the portable benchmark fixture."
    )


def extra_files(root: Path) -> list[tuple[Path, PurePosixPath]]:
    files: list[tuple[Path, PurePosixPath]] = []
    fixture = cod_fixture_source(root)
    files.append((fixture, COD_FIXTURE_TARGET))

    results_root = root / "XRD_Finder" / "benchmark_results"
    for directory_name in BENCHMARK_RESULT_DIRECTORIES:
        source_directory = results_root / directory_name
        if not source_directory.is_dir():
            raise FileNotFoundError(
                f"Benchmark result directory is missing: {source_directory}"
            )
        for name in sorted(BENCHMARK_RESULT_FILES):
            path = source_directory / name
            if path.is_file():
                target = (
                    PurePosixPath("XRD_Finder/benchmark_results")
                    / directory_name
                    / name
                )
                files.append((path, target))
    return files


def build_info(root: Path, version: str) -> str:
    status = git_text(root, "status", "--porcelain")
    return "\n".join(
        [
            "XRD Phase Finder portable development package",
            f"Version: {version}",
            f"Built UTC: {datetime.now(timezone.utc).isoformat()}",
            f"Git commit: {git_text(root, 'rev-parse', 'HEAD')}",
            f"Working tree: {'dirty' if status and status != 'unknown' else 'clean'}",
            "",
            "This package was built from the current working tree.",
            "Uncommitted and untracked source/test changes are included.",
            "",
        ]
    )


def write_archive(
    root: Path,
    output: Path,
    top_level: str,
    version: str,
) -> tuple[int, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)

    entries: dict[PurePosixPath, Path] = {}
    for path, relative in [*source_files(root), *extra_files(root)]:
        if relative in entries:
            if entries[relative].resolve() == path.resolve():
                continue
            raise RuntimeError(f"Duplicate archive member: {relative}")
        entries[relative] = path

    total_size = 0
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative, path in sorted(entries.items(), key=lambda item: str(item[0])):
            archive_name = str(PurePosixPath(top_level) / relative)
            archive.write(path, archive_name)
            total_size += path.stat().st_size
        archive.writestr(
            str(PurePosixPath(top_level) / "BUILD_INFO.txt"),
            build_info(root, version),
        )

    temporary.replace(output)
    return len(entries) + 1, total_size


def validate_archive(path: Path, top_level: str) -> None:
    forbidden: list[str] = []
    allowed_extra_prefix = PurePosixPath("XRD_Finder/benchmark_results")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name in names:
            relative_text = name.removeprefix(f"{top_level}/")
            relative = PurePosixPath(relative_text)
            is_curated_result = is_under(relative, allowed_extra_prefix)
            if not name.startswith(f"{top_level}/") or (
                not is_curated_result and not should_include(relative)
            ):
                forbidden.append(name)
        required = {
            f"{top_level}/PORTABLE_README.md",
            f"{top_level}/XRD_Finder/requirements-dev.txt",
            f"{top_level}/{COD_FIXTURE_TARGET}",
            f"{top_level}/XRD_Finder/tests/test_gain_evidence.py",
            f"{top_level}/XRD_Finder/xrd_finder/finder/gain_evidence.py",
        }
        missing = sorted(required.difference(names))
    if forbidden:
        raise RuntimeError(
            "Portable archive contains forbidden files:\n"
            + "\n".join(f"  {name}" for name in forbidden[:30])
        )
    if missing:
        raise RuntimeError(
            "Portable archive is incomplete:\n"
            + "\n".join(f"  {name}" for name in missing)
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a portable development archive from the current worktree."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output ZIP path. Defaults to dist/XRD_Phase_Finder_Portable_<version>.zip.",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    version = project_version(root)
    top_level = f"XRD_Phase_Finder_Portable_{version}"
    output = (
        args.output
        or root / "dist" / f"XRD_Phase_Finder_Portable_{version}.zip"
    ).resolve()

    member_count, source_size = write_archive(root, output, top_level, version)
    validate_archive(output, top_level)
    checksum = sha256(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{checksum}  {output.name}\n", encoding="ascii")

    print(f"Archive: {output}")
    print(f"SHA-256: {checksum}")
    print(f"Members: {member_count}")
    print(f"Source bytes: {source_size}")
    print(f"Archive bytes: {output.stat().st_size}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"portable archive failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
