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

# Pinned universal2 Python.org installer: works on Intel and Apple Silicon.
# SHA-256 verified against the official Python 3.12.10 macOS download.
PYTHON_PKG_URL="https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg"
PYTHON_PKG_SHA256="8373e58da4ea146b3eb1c1f9834f19a319440b6b679b06050b1f9ee3237aa8e4"

install_python() {
    case "${XRD_FINDER_OFFLINE:-}" in
        1|true|TRUE|yes|YES|on|ON)
            echo "Offline mode is enabled. Python cannot be downloaded."
            return 1
            ;;
    esac
    local download_dir
    download_dir="$(mktemp -d "$SCI_ROOT/python-download.XXXXXX")" || return 1
    local package="$download_dir/python-3.12.10-macos11.pkg"
    echo "Downloading Python 3.12.10 from python.org (about 44 MB)..."
    echo "Downloading Python: $PYTHON_PKG_URL" >> "$LOG_FILE"
    if ! /usr/bin/curl --fail --location --show-error --retry 3 --retry-all-errors \
        --connect-timeout 20 --max-time 900 --proto '=https' --proto-redir '=https' \
        --output "$package" "$PYTHON_PKG_URL"; then
        echo "Python download failed. Check your connection and run Finder again." | tee -a "$LOG_FILE"
        rm -rf "$download_dir"
        return 1
    fi
    local actual_sha
    actual_sha="$(/usr/bin/shasum -a 256 "$package")" || return 1
    actual_sha="${actual_sha%% *}"
    if [ "$actual_sha" != "$PYTHON_PKG_SHA256" ]; then
        echo "Python installer checksum failed. The downloaded file will not be installed." | tee -a "$LOG_FILE"
        rm -rf "$download_dir"
        return 1
    fi
    echo "Installing Python. macOS will ask for your administrator password."
    echo "Installing Python 3.12.10" >> "$LOG_FILE"
    if ! /usr/bin/osascript - "$package" <<'APPLESCRIPT'
on run argv
    do shell script "/usr/sbin/installer -pkg " & quoted form of (item 1 of argv) & " -target /" with administrator privileges
end run
APPLESCRIPT
    then
        echo "Python installation failed or was cancelled. Run Finder again to retry." | tee -a "$LOG_FILE"
        rm -rf "$download_dir"
        return 1
    fi
    rm -rf "$download_dir"
}

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
    install_python || exit 1
    PYTHON="$(find_python || true)"
    if [ -z "$PYTHON" ]; then
        echo "Python was installed but could not be started for $SCI_ARCH. See $LOG_FILE" | tee -a "$LOG_FILE"
        exit 1
    fi
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

REQ_FILE="$APP_ROOT/requirements.txt"
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

echo "Validating XRD Phase Finder runtime..."
cd "$APP_ROOT"
/usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" -m xrd_finder.apps.runtime_check --mode gui >> "$LOG_FILE" 2>&1

echo "[$(date)] Sci setup complete." >> "$LOG_FILE"
echo "Sci environment is ready."
