#!/bin/zsh
set -e

APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_ROOT"
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
    echo "Run setup_env.command first to create the shared Sci environment, or install requirements.txt into Python 3.11+."
    read "?Press Enter to close..."
    exit 1
fi

"$PYTHON" -m xrd_finder.apps.finder_cli "$@"
