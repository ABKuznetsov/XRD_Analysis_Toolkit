#!/bin/zsh
set -e

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCI_ROOT="$HOME/Library/Application Support/Sci"

if [ "$(uname -m)" = "arm64" ] || [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
    SCI_ARCH="arm64"
else
    SCI_ARCH="x86_64"
fi

SCI_ENV="$SCI_ROOT/env-$SCI_ARCH"
SCI_LOGS="$SCI_ROOT/logs"
LOG_FILE="$SCI_LOGS/setup.log"
export ARCHFLAGS="-arch $SCI_ARCH"
MACOS_PYSIDE_REQUIREMENT="PySide6==6.11.1"

mkdir -p "$SCI_ROOT" "$SCI_LOGS"

echo "[$(date)] Starting Sci setup" > "$LOG_FILE"
echo "Application root: $APP_ROOT" >> "$LOG_FILE"
echo "Sci root: $SCI_ROOT" >> "$LOG_FILE"

find_python() {
    for candidate in \
        "/opt/homebrew/bin/python3" \
        "/usr/local/bin/python3" \
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" \
        "/opt/homebrew/bin/python3.12" \
        "/opt/homebrew/bin/python3.11" \
        "/usr/local/bin/python3.12" \
        "/usr/local/bin/python3.11" \
        "/usr/bin/python3" \
        "python3"
    do
        if command -v "$candidate" >/dev/null 2>&1 \
            && /usr/bin/arch "-$SCI_ARCH" "$candidate" -c \
                "import platform, sys; raise SystemExit(0 if platform.machine() == '$SCI_ARCH' and (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" \
                >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

install_requirement() {
    local requirement="$1"
    [ -z "$requirement" ] && return 0
    [[ "$requirement" == \#* ]] && return 0
    if [[ "$requirement" == PySide6* ]]; then
        requirement="$MACOS_PYSIDE_REQUIREMENT"
    fi
    echo "Installing package: $requirement"
    echo "Installing package: $requirement" >> "$LOG_FILE"
    /usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" -m pip install --disable-pip-version-check --timeout 60 --retries 3 --prefer-binary --upgrade --upgrade-strategy eager "$requirement" >> "$LOG_FILE" 2>&1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "Compatible Python was not found."
    echo "Install Python 3.11 or 3.12 from https://www.python.org/downloads/macos/"
    echo "or with Homebrew: brew install python@3.12"
    echo "Python 3.11/3.12 not found." >> "$LOG_FILE"
    exit 1
fi

echo "Using Python: $PYTHON"
echo "Using Python: $PYTHON" >> "$LOG_FILE"
echo "Runtime architecture: $SCI_ARCH"
echo "Runtime architecture: $SCI_ARCH" >> "$LOG_FILE"

if [ -x "$SCI_ENV/bin/python" ] \
    && ! /usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" -c \
        "import platform, sys; raise SystemExit(0 if platform.machine() == '$SCI_ARCH' and (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" \
        >/dev/null 2>&1; then
    echo "Existing Sci environment uses an incompatible Python. Recreating it..."
    echo "Removing incompatible venv at $SCI_ENV" >> "$LOG_FILE"
    rm -rf "$SCI_ENV"
fi

if [ ! -x "$SCI_ENV/bin/python" ]; then
    echo "Creating Sci environment..."
    echo "Creating venv at $SCI_ENV" >> "$LOG_FILE"
    /usr/bin/arch "-$SCI_ARCH" "$PYTHON" -m venv "$SCI_ENV" >> "$LOG_FILE" 2>&1
fi

if [ ! -x "$SCI_ENV/bin/python" ]; then
    echo "Failed to create Sci environment."
    echo "venv creation failed." >> "$LOG_FILE"
    exit 1
fi

echo "Upgrading pip and build tools..."
echo "Upgrading pip and build tools..." >> "$LOG_FILE"
/usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" -m pip install --disable-pip-version-check --timeout 60 --retries 3 --prefer-binary --upgrade pip setuptools wheel >> "$LOG_FILE" 2>&1

REQ_FILE="$APP_ROOT/XRD_Finder/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    echo "Requirements file was not found: $REQ_FILE"
    echo "Requirements file was not found: $REQ_FILE" >> "$LOG_FILE"
    exit 1
fi

echo "Installing XRD Phase Finder requirements..."
echo "Installing XRD Phase Finder requirements..." >> "$LOG_FILE"
while IFS= read -r requirement || [ -n "$requirement" ]; do
    install_requirement "$requirement"
done < "$REQ_FILE"

echo "[$(date)] Sci setup complete." >> "$LOG_FILE"
echo "Sci environment is ready."
