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
XRD_FINDER_USER_ROOT="$SCI_ROOT/apps/xrd_phase_finder"
SCI_LOGS="$SCI_ROOT/logs"
PREVIEW_SCRIPT="$APP_ROOT/launcher/launch_xrd_finder_preview_macos.py"

mkdir -p "$SCI_ROOT" "$XRD_FINDER_USER_ROOT" "$SCI_LOGS"

# A prepared runtime goes straight to Finder. No Tk window, network request,
# scientific imports in a probe, or minimum splash-screen display time.
if [ -x "$SCI_ENV/bin/python" ] && [ -f "$APP_ROOT/launcher/fast_start.py" ]; then
    if /usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" "$APP_ROOT/launcher/fast_start.py" \
        --data-root "$XRD_FINDER_USER_ROOT/data" --logs-root "$SCI_LOGS" "$@"; then
        exit 0
    else
        START_STATUS=$?
    fi
    if [ "$START_STATUS" -ne 75 ]; then
        export XRD_FINDER_STARTUP_ERROR="${XRD_FINDER_LOG_DIR:-$SCI_LOGS}/xrd_finder_console.log"
    fi
fi

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

# Only first installation/repair reaches this fallback when Tk is unavailable.
if [ -n "${XRD_FINDER_STARTUP_ERROR:-}" ]; then
    echo "Finder could not open. See: $XRD_FINDER_STARTUP_ERROR" >&2
    exit 1
fi
case "${XRD_FINDER_OFFLINE:-}" in
    1|true|TRUE|yes|YES|on|ON)
        echo "Offline mode is enabled. Install the Sci runtime before launching Finder." >&2
        exit 1
        ;;
esac
if [ -f "${XRD_FINDER_DATA_DIR:-$XRD_FINDER_USER_ROOT/data}/settings/security.json" ] && \
    grep -Eq '"offline_mode"[[:space:]]*:[[:space:]]*true' "${XRD_FINDER_DATA_DIR:-$XRD_FINDER_USER_ROOT/data}/settings/security.json"; then
    echo "Offline mode is enabled. Install the Sci runtime before launching Finder." >&2
    exit 1
fi
"$APP_ROOT/launcher/setup_sci_env.command"
exec /usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" "$APP_ROOT/launcher/fast_start.py" \
    --data-root "$XRD_FINDER_USER_ROOT/data" --logs-root "$SCI_LOGS" "$@"
