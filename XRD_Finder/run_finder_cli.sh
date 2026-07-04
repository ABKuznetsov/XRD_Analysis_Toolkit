#!/usr/bin/env bash
set -euo pipefail

TOOLKIT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_ROOT="$TOOLKIT_ROOT/XRD_Finder"
cd "$TOOLKIT_ROOT"
export PYTHONPATH="$APP_ROOT${PYTHONPATH+:$PYTHONPATH}"

find_python() {
    local candidates=(
        ".venv/bin/python"
        "/usr/local/bin/python3"
        "/usr/bin/python3"
        "python3"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import numpy, scipy" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "Could not find a Python with required packages: numpy and scipy."
    echo "Run ./setup_env.sh first to create the shared Toolkit .venv, or install XRD_Finder/requirements.txt into Python 3.11+."
    exit 1
fi

"$PYTHON" -m xrd_finder.apps.finder_cli "$@"
