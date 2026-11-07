#!/bin/zsh
set -e

APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT${PYTHONPATH+:$PYTHONPATH}"
export XRD_FINDER_LOG_DIR="${HOME}/Library/Logs/XRD Phase Finder"
SCI_ROOT="$HOME/Library/Application Support/Sci"
SCI_ARCH="$(uname -m)"

find_python() {
    for candidate in \
        "$SCI_ROOT/env-$SCI_ARCH/bin/python" \
        "$SCI_ROOT/env/bin/python" \
        ".venv/bin/python" \
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
        "/usr/local/bin/python3" \
        "/opt/homebrew/bin/python3" \
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
        "/usr/bin/python3" \
        "python3"
    do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" "$APP_ROOT/launcher/fast_start.py" --probe --develop >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "Could not find a Python with all required XRD Phase Finder packages."
    echo "Run launcher/setup_sci_env.command first to create the shared Sci environment, or install requirements.txt into Python 3.11+."
    read "?Press Enter to close..."
    exit 1
fi

# Develop can use a private dependency build without replacing shared Sci libs.
# Separate interpreter tags prevent loading a cp311 native module in cp313.
RUNTIME_TAG="$("$PYTHON" -c 'import sys; print(sys.implementation.cache_tag)')"
XRD_DEVELOP_LIBS="$SCI_ROOT/xrd-develop-libs/$SCI_ARCH/$RUNTIME_TAG"
if [ -d "$XRD_DEVELOP_LIBS/cristma" ]; then
    export PYTHONPATH="$APP_ROOT:$XRD_DEVELOP_LIBS${PYTHONPATH+:$PYTHONPATH}"
fi

"$PYTHON" -m xrd_finder.apps.finder_gui "$@"
