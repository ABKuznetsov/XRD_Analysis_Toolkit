from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import re
import sys
from pathlib import Path


CORE_MODULES = {
    "certifi": "certifi",
    "gemmi": "gemmi",
    "numpy": "numpy",
    "pybaselines": "pybaselines",
    "pyqtgraph": "pyqtgraph",
    "PySide6": "PySide6",
    "scipy": "scipy",
}

FULL_MODULES = {
    **CORE_MODULES,
    "mp-api": "mp_api",
    "pymatgen": "pymatgen",
}

REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)\s*(?:==\s*([A-Za-z0-9_.+!-]+))?"
)


def _normalized_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _requirements(path: Path | None) -> dict[str, tuple[str, str | None]]:
    if path is None or not path.is_file():
        return {}
    result: dict[str, tuple[str, str | None]] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = REQUIREMENT.match(line)
        if match:
            name, version = match.groups()
            result[_normalized_package_name(name)] = (name, version)
    return result


def _exact_requirements(path: Path | None) -> dict[str, tuple[str, str]]:
    return {
        key: (name, version)
        for key, (name, version) in _requirements(path).items()
        if version is not None
    }


def _probe_runtime(requirements_path: Path | None, *, full: bool = False) -> list[str]:
    failures: list[str] = []
    if requirements_path is not None and not requirements_path.is_file():
        failures.append(f"Requirements file is missing: {requirements_path}")
    if not ((3, 11) <= sys.version_info[:2] < (3, 13)):
        failures.append(
            "Python version is unsupported: "
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}; "
            "expected 3.11 or 3.12"
        )

    missing_packages: set[str] = set()
    for normalized_name, (display_name, expected) in _requirements(requirements_path).items():
        try:
            installed = importlib.metadata.version(display_name)
        except importlib.metadata.PackageNotFoundError:
            expected_text = f" (required {expected})" if expected else ""
            failures.append(f"{display_name} is not installed{expected_text}")
            missing_packages.add(normalized_name)
            continue
        if expected is not None and installed != expected:
            failures.append(
                f"{display_name} version mismatch: installed {installed}, required {expected}"
            )

    modules = FULL_MODULES if full else CORE_MODULES
    for package_name, module_name in modules.items():
        if _normalized_package_name(package_name) in missing_packages:
            continue
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # diagnostics must report binary/DLL failures too
            failures.append(f"{package_name} import failed: {type(exc).__name__}: {exc}")

    if not failures:
        try:
            import numpy as np
            from scipy.optimize import nnls

            matrix = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=float)
            values, _ = nnls(matrix, np.asarray([1.0, 2.0], dtype=float))
            if not np.allclose(values, [1.0, 2.0]):
                failures.append("NumPy/SciPy numerical self-test returned an invalid result")
        except Exception as exc:
            failures.append(f"NumPy/SciPy self-test failed: {type(exc).__name__}: {exc}")

        try:
            from PySide6 import QtCore, QtGui, QtWidgets

            if not (QtCore and QtGui and QtWidgets):
                failures.append("PySide6 Qt modules are incomplete")
        except Exception as exc:
            failures.append(f"PySide6 Qt test failed: {type(exc).__name__}: {exc}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the XRD Phase Finder Sci runtime")
    parser.add_argument("--requirements", type=Path)
    parser.add_argument(
        "--full",
        action="store_true",
        help="also import optional heavy connectors; intended for installation validation",
    )
    args = parser.parse_args()

    failures = _probe_runtime(args.requirements, full=args.full)
    if failures:
        # Keep diagnostics on stdout. Windows PowerShell 5 may convert native
        # stderr into a NativeCommandError and hide the useful package message.
        print("RUNTIME_CHECK_FAILED")
        print(f"Python: {sys.executable}")
        print(f"Version: {sys.version.split()[0]}")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(
        "RUNTIME_CHECK_OK "
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}; "
        f"{len(FULL_MODULES if args.full else CORE_MODULES)} required packages imported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
