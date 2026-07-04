#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

find_python() {
    local candidates=(
        ".venv/bin/python"
        "/usr/local/bin/python3"
        "/usr/bin/python3"
        "python3"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
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
    echo "Run ./setup_env.sh first, or install requirements.txt into Python 3.11+."
    echo
    echo "If Qt fails to start on Linux, install the platform packages for your desktop:"
    echo "  Ubuntu/Debian: sudo apt install libxcb-cursor0 libegl1"
    echo "  Fedora:        sudo dnf install xcb-util-cursor mesa-libEGL"
    exit 1
fi

"$PYTHON" -m xrd_manager.apps.finder_gui "$@"
