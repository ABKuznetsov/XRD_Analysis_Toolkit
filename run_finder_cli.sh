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
    echo "Run ./setup_env.sh first, or install requirements.txt into Python 3.11+."
    exit 1
fi

"$PYTHON" -m xrd_manager.apps.finder_cli "$@"
