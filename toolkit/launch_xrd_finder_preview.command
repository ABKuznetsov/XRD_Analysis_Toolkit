#!/bin/zsh
set -e
unsetopt BG_NICE 2>/dev/null || true

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCI_ROOT="$HOME/Library/Application Support/Sci"

if [ "$(uname -m)" = "arm64" ] || [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
    SCI_ARCH="arm64"
else
    SCI_ARCH="x86_64"
fi

SCI_ENV="$SCI_ROOT/env-$SCI_ARCH"
XRD_FINDER_USER_ROOT="$SCI_ROOT/XRD_Finder"
SCI_LOGS="$SCI_ROOT/logs"
READY_FILE="$SCI_ROOT/xrd_finder_ready"
PREVIEW_SCRIPT="$APP_ROOT/toolkit/launch_xrd_finder_preview_macos.py"

mkdir -p "$SCI_ROOT" "$XRD_FINDER_USER_ROOT" "$SCI_LOGS"

find_preview_python() {
    for candidate in \
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" \
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
        "/opt/homebrew/bin/python3.12" \
        "/opt/homebrew/bin/python3.11" \
        "/usr/local/bin/python3.12" \
        "/usr/local/bin/python3.11" \
        "/usr/local/bin/python3" \
        "/usr/bin/python3" \
        "python3"
    do
        if command -v "$candidate" >/dev/null 2>&1 \
            && /usr/bin/arch "-$SCI_ARCH" "$candidate" -c \
                "import platform, sys, tkinter; raise SystemExit(0 if platform.machine() == '$SCI_ARCH' and (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" \
                >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PREVIEW_PYTHON="$(find_preview_python || true)"
if [ -n "$PREVIEW_PYTHON" ] && [ -f "$PREVIEW_SCRIPT" ]; then
    exec /usr/bin/arch "-$SCI_ARCH" "$PREVIEW_PYTHON" "$PREVIEW_SCRIPT" "$@"
fi

echo "XRD Phase Finder startup preview"
echo "Application root: $APP_ROOT"
echo

if [ ! -x "$SCI_ENV/bin/python" ]; then
    echo "1/4 Installing scientific Python environment..."
    "$APP_ROOT/toolkit/setup_sci_env.command"
else
    echo "1/4 Environment ready."
fi

if [ -d "$APP_ROOT/.git" ] && command -v git >/dev/null 2>&1; then
    echo "2/4 Checking GitHub updates..."
    (
        cd "$APP_ROOT"
        git fetch origin >/dev/null 2>&1 || exit 0
        LOCAL_REV="$(git rev-parse @ 2>/dev/null || true)"
        UPSTREAM_REV="$(git rev-parse @{u} 2>/dev/null || git rev-parse origin/main 2>/dev/null || true)"
        BASE_REV="$(git merge-base @ "$UPSTREAM_REV" 2>/dev/null || true)"
        if [ -n "$LOCAL_REV" ] && [ -n "$UPSTREAM_REV" ] && [ "$LOCAL_REV" != "$UPSTREAM_REV" ] && [ "$LOCAL_REV" = "$BASE_REV" ]; then
            echo "   Updating source..."
            git pull --ff-only >/dev/null
            "$APP_ROOT/toolkit/setup_sci_env.command"
        else
            echo "   Already up to date."
        fi
    ) || echo "   Auto-update skipped. Use update_macos.command for details."
else
    echo "2/4 Auto-update skipped: this is not a Git checkout or git is unavailable."
fi

echo "3/4 Starting XRD Phase Finder..."
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$APP_ROOT/XRD_Finder${PYTHONPATH+:$PYTHONPATH}"
export XRD_FINDER_DATA_DIR="$XRD_FINDER_USER_ROOT/data"
export MPLCONFIGDIR="$XRD_FINDER_USER_ROOT/matplotlib"
export XRD_FINDER_READY_FILE="$READY_FILE"
export QT_MAC_WANTS_LAYER=1
rm -f "$READY_FILE"

/usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" -m xrd_finder.apps.finder_gui "$@" &
APP_PID="$!"

echo "4/4 Waiting for application window..."
for _ in {1..120}; do
    if [ -f "$READY_FILE" ]; then
        echo "XRD Phase Finder is running."
        exit 0
    fi
    if ! kill -0 "$APP_PID" >/dev/null 2>&1; then
        echo
        echo "XRD Phase Finder exited during startup."
        read "?Press Enter to close..."
        exit 1
    fi
    sleep 1
done

echo "Startup is taking longer than expected. The app may still be opening."
read "?Press Enter to close..."
