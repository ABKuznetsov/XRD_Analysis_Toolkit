#!/bin/zsh
set -e

TOOLKIT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_ROOT="$TOOLKIT_ROOT/XRD_Finder"
cd "$TOOLKIT_ROOT"
export PYTHONPATH="$APP_ROOT${PYTHONPATH+:$PYTHONPATH}"

find_python() {
    for candidate in \
        ".venv/bin/python" \
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
        "/usr/local/bin/python3" \
        "/opt/homebrew/bin/python3" \
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
        "/usr/bin/python3" \
        "python3"
    do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import PySide6, numpy, scipy, pyqtgraph" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "Could not find a Python with required packages: PySide6, numpy, scipy, pyqtgraph."
    echo "Run setup_env.command first to create the shared Toolkit .venv, or install XRD_Finder/requirements.txt into Python 3.11+."
    read "?Press Enter to close..."
    exit 1
fi

"$PYTHON" -m xrd_finder.apps.finder_gui "$@"
