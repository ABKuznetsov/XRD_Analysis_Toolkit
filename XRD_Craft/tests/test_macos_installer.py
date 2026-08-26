from __future__ import annotations

import json
import subprocess
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _config(script: str) -> dict[str, object]:
    result = subprocess.run(
        ["/bin/zsh", str(ROOT / script), "--print-config"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_macos_pkg_uses_raman_style_bundle_and_shared_sci_environment() -> None:
    build = _config("scripts/build_macos_pkg.command")
    setup = _config("toolkit/setup_crystal_blocks_env.command")
    launch = _config("toolkit/launch_crystal_blocks.command")

    assert build["app_name"] == "CRAFT"
    assert build["bundle_id"] == "com.scitools.craft"
    assert build["pkg_name"] == "CRAFT_macOS_0.1.0.pkg"
    assert build["install_path"] == "/Applications/CRAFT.app"
    assert build["relocatable"] is False
    assert build["icon"] == "icon.icns"
    assert build["signing"] == "adhoc"
    assert build["launcher"] == "native-mach-o"
    assert (ROOT / "toolkit" / "macos_launcher.c").is_file()
    assert (ROOT / "assets" / "crystal_blocks_icon.png").is_file()
    assert setup["environment"] == "~/Library/Application Support/Sci/env"
    assert setup["python"] == "3.11 or 3.12"
    assert setup["install_mode"] == "dependencies-only"
    assert setup["repair_architecture"] is True
    assert launch["module"] == "crystal_viewer.app"
    assert launch["environment"] == "~/Library/Application Support/Sci/env"


def test_launcher_reads_version_with_existing_shared_environment_without_path_python(tmp_path) -> None:
    app = tmp_path / "app"
    toolkit = app / "toolkit"
    toolkit.mkdir(parents=True)
    shutil.copy(ROOT / "toolkit" / "launch_crystal_blocks.command", toolkit)
    (app / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    called = tmp_path / "setup-called"
    setup = toolkit / "setup_crystal_blocks_env.command"
    setup.write_text(f'#!/bin/zsh\ntouch "{called}"\n', encoding="utf-8")
    setup.chmod(0o755)
    home = tmp_path / "home"
    env_bin = home / "Library/Application Support/Sci/env/bin"
    env_bin.mkdir(parents=True)
    fake_python = env_bin / "python"
    fake_python.write_text(
        '#!/bin/zsh\nif [ "$1" = "-c" ]; then print 0.1.0; fi\nexit 0\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    marker = home / "Library/Application Support/Sci/apps/craft/installed-version.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("0.1.0\n", encoding="utf-8")
    fake_path = tmp_path / "bin"
    fake_path.mkdir()
    for command in ("dirname", "cat", "mkdir", "touch"):
        (fake_path / command).symlink_to(shutil.which(command))

    subprocess.run(
        ["/bin/zsh", str(toolkit / "launch_crystal_blocks.command")],
        cwd=app,
        env={**os.environ, "HOME": str(home), "PATH": str(fake_path)},
        check=True,
    )

    assert not called.exists()


def test_launcher_accepts_a_healthy_shared_environment_without_a_craft_marker(tmp_path) -> None:
    app = tmp_path / "app"
    toolkit = app / "toolkit"
    toolkit.mkdir(parents=True)
    shutil.copy(ROOT / "toolkit" / "launch_crystal_blocks.command", toolkit)
    (app / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    called = tmp_path / "setup-called"
    setup = toolkit / "setup_crystal_blocks_env.command"
    setup.write_text(f'#!/bin/zsh\ntouch "{called}"\n', encoding="utf-8")
    setup.chmod(0o755)
    home = tmp_path / "home"
    env_bin = home / "Library/Application Support/Sci/env/bin"
    env_bin.mkdir(parents=True)
    fake_python = env_bin / "python"
    fake_python.write_text(
        '#!/bin/zsh\nif [ "$1" = "-c" ]; then print 0.1.0; fi\nexit 0\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_path = tmp_path / "bin"
    fake_path.mkdir()
    for command in ("dirname", "cat", "mkdir"):
        (fake_path / command).symlink_to(shutil.which(command))

    subprocess.run(
        ["/bin/zsh", str(toolkit / "launch_crystal_blocks.command")],
        cwd=app,
        env={**os.environ, "HOME": str(home), "PATH": str(fake_path)},
        check=True,
    )

    assert not called.exists()
    marker = home / "Library/Application Support/Sci/apps/craft/installed-version.txt"
    assert marker.read_text(encoding="utf-8").strip() == "0.1.0"


def test_macos_setup_does_not_force_reinstall_the_shared_environment() -> None:
    setup = (ROOT / "toolkit" / "setup_crystal_blocks_env.command").read_text(encoding="utf-8")

    assert "--force-reinstall" not in setup
