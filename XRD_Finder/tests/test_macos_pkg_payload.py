from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build_macos_pkg.command"
PREVIEW_SCRIPT = REPOSITORY_ROOT / "toolkit" / "launch_xrd_finder_preview_macos.py"


def test_macos_pkg_keeps_and_validates_required_finder_modules() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    required_modules = (
        "XRD_Finder/xrd_finder/core/refinement.py",
        "XRD_Finder/xrd_finder/core/series.py",
    )
    for module in required_modules:
        assert f'--exclude "{module}"' not in script
        assert module in script


def test_macos_pkg_uses_a_runtime_payload_allowlist() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    required_sources = (
        "XRD_Finder/xrd_finder/",
        "XRD_Finder/app.json",
        "XRD_Finder/Entry_96-100-0018.cif",
        "XRD_Finder/requirements.txt",
        "XRD_Finder/icon.png",
        "toolkit/launch_xrd_finder_preview.command",
        "toolkit/launch_xrd_finder_preview_macos.py",
        "toolkit/setup_sci_env.command",
        "toolkit/manifest.json",
        "LICENSE",
    )
    for path in required_sources:
        assert path in script

    assert '"$ROOT/" "$APP_PAYLOAD_DIR/"' not in script
    assert "Forbidden non-runtime payload" in script
    for legacy_module in (
        "app.py",
        "io/exporters.py",
        "services/thermo_service.py",
        "services/solid_solution_service.py",
        "services/structure_service.py",
        "ui/legacy_windows.py",
        "ui/main_window.py",
    ):
        assert f'--exclude "{legacy_module}"' in script


def test_macos_pkg_explicitly_rejects_craft_payload() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '"$ROOT/" "$APP_PAYLOAD_DIR/"' not in script
    assert "Forbidden CRAFT payload" in script


def test_macos_runtime_probe_covers_required_imports() -> None:
    tree = ast.parse(PREVIEW_SCRIPT.read_text(encoding="utf-8"))
    probe = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "RUNTIME_PROBE" for target in node.targets)
    )

    for module in ("certifi", "mp_api", "pybaselines", "pymatgen", "rfc8785"):
        assert module in probe
