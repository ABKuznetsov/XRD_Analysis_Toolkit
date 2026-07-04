#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found."
    echo "Install Python 3.11 or newer first."
    echo
    echo "Ubuntu/Debian:"
    echo "  sudo apt install python3 python3-venv python3-pip"
    echo
    echo "Fedora:"
    echo "  sudo dnf install python3 python3-pip"
    exit 1
fi

if ! python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
    echo "Python 3.11 or newer is required."
    echo "Current python3:"
    python3 --version
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
echo "Run the app with ./run_finder.sh"
