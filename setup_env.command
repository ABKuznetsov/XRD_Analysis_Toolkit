#!/bin/zsh
set -e

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Install Python 3.11 or newer first."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating local virtual environment..."
    python3 -m venv .venv
fi

echo "Upgrading pip..."
".venv/bin/python" -m pip install --upgrade pip

echo "Installing XRD Toolkit requirements..."
".venv/bin/python" -m pip install -r requirements.txt

echo
echo "Environment is ready."
echo "Run the app with run_finder.command"
