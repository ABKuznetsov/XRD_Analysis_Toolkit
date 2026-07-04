#!/bin/zsh
set -e

TOOLKIT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$TOOLKIT_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Install Python 3.11 or newer first."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating shared Toolkit virtual environment at $TOOLKIT_ROOT/.venv..."
    python3 -m venv .venv
fi

echo "Upgrading pip..."
".venv/bin/python" -m pip install --upgrade pip

echo "Installing XRD Toolkit requirements..."
".venv/bin/python" -m pip install -r XRD_Finder/requirements.txt

echo
echo "Environment is ready."
echo "Run the app with XRD_Finder/run_finder.command"
