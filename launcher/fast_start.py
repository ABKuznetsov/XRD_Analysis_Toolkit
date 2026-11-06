"""Cheap installed-runtime check and direct GUI launch; no Qt/Tk/science imports.

Exit 75 asks the platform launcher to display its first-install/repair UI.
Application errors use their own exit code and never cause an automatic repair.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Thread
import time
import uuid


NEEDS_SETUP = 75


def runtime_metadata_ready(root: Path) -> bool:
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        return False
    try:
        requirements = (root / 'requirements.txt').read_text(encoding='utf-8')
        for line in requirements.splitlines():
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            match = re.fullmatch(r'([A-Za-z0-9_-]+)(?:==([^\s;]+))?', line)
            if not match:
                return False  # A new constraint must be checked by the full setup path.
            name, expected = match.groups()
            if sys.platform == 'darwin' and name.casefold() == 'pyside6':
                expected = '6.11.1'
            actual = importlib.metadata.version(name)
            if expected and actual != expected:
                return False
            if importlib.util.find_spec(name) is None:
                return False
        return True
    except (OSError, ValueError, ImportError, importlib.metadata.PackageNotFoundError):
        return False


def launch(root: Path, data: Path, logs: Path, arguments: list[str], *, environ=None, python=None) -> int:
    env = dict(os.environ if environ is None else environ)
    # An explicit data location belongs to the user/test runner. Otherwise the
    # platform launcher passes exactly the location used by its previous loader.
    data = Path(env.get('XRD_FINDER_DATA_DIR') or data).expanduser()
    logs = Path(env.get('XRD_FINDER_LOG_DIR') or logs).expanduser()
    logs.mkdir(parents=True, exist_ok=True)
    ready = logs / f'xrd-{uuid.uuid4().hex}.ready'
    try:
        info = json.loads((root / 'app.json').read_text(encoding='utf-8-sig'))
        entry = info.get('entry_module') or 'xrd_finder.apps.finder_gui'
    except (OSError, ValueError, AttributeError):
        entry = 'xrd_finder.apps.finder_gui'
    env.update(PYTHONDONTWRITEBYTECODE='1', XRD_FINDER_DATA_DIR=str(data),
               XRD_FINDER_LOG_DIR=str(logs), XRD_FINDER_READY_FILE=str(ready))
    env['PYTHONPATH'] = str(root) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    env.setdefault('MPLCONFIGDIR', str(data.parent / 'matplotlib'))
    if sys.platform == 'darwin':
        env.setdefault('QT_MAC_WANTS_LAYER', '1')
    elif sys.platform == 'win32':
        for key, value in {'QT_OPENGL':'software', 'QT_QUICK_BACKEND':'software',
                           'QT_ANGLE_PLATFORM':'warp', 'QT_QPA_PLATFORM':'windows'}.items():
            env.setdefault(key, value)
    # No hidden-window preparation handshake on a normal launch.
    env.pop('XRD_FINDER_SHOW_SIGNAL_FILE', None)
    env.pop('XRD_FINDER_PREPARED_FILE', None)
    with (logs / 'xrd_finder_console.log').open('w', encoding='utf-8') as output:
        process = subprocess.Popen([str(python or sys.executable), '-m', entry, *arguments],
                                   cwd=str(root), env=env, stdout=output,
                                   stderr=subprocess.STDOUT,
                                   start_new_session=sys.platform != 'win32',
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    # Reap a child that outlives this function without holding the launcher open.
    Thread(target=process.wait, name='finder-process', daemon=True).start()
    try:
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            if ready.exists():
                return 0
            code = process.poll()
            if code is not None:
                return code
            time.sleep(0.025)
        # A user may still be deciding about the one-time library conversion.
        # Keep the application alive; never start a second copy or a repair.
        return 0
    finally:
        ready.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--develop', action='store_true')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--logs-root', type=Path)
    args, arguments = parser.parse_known_args()
    root = Path(__file__).resolve().parents[1]
    if args.develop:
        import platform
        private = Path.home() / 'Library/Application Support/Sci/xrd-develop-libs' / platform.machine() / sys.implementation.cache_tag
        if (private / 'cristma').is_dir():
            sys.path.insert(0, str(private))
    if not runtime_metadata_ready(root):
        return NEEDS_SETUP
    if args.probe:
        return 0
    if args.data_root is None or args.logs_root is None:
        parser.error('--data-root and --logs-root are required for installed launch')
    code = launch(root, args.data_root, args.logs_root, arguments)
    if code:
        # Only failed starts need the expensive native-library/API probe.
        # A GUI bug with a healthy runtime must not trigger package repair.
        try:
            check = subprocess.run([sys.executable, '-m', 'xrd_finder.apps.runtime_check', '--mode', 'core'],
                                   cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=30)
        except subprocess.TimeoutExpired:
            return NEEDS_SETUP
        if check.returncode:
            return NEEDS_SETUP
    return code


if __name__ == '__main__':
    raise SystemExit(main())
