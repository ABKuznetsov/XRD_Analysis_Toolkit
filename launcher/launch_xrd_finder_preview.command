#!/bin/zsh
set -e
unsetopt BG_NICE 2>/dev/null || true

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCI_ROOT="$HOME/Library/Application Support/Sci"
OFFER_SETUP_ONLY=0
if [ "${1:-}" = "--offer-setup" ]; then
    OFFER_SETUP_ONLY=1
    shift
fi

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
    if /usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" "$APP_ROOT/launcher/fast_start.py" --probe; then
        [ "$OFFER_SETUP_ONLY" -eq 1 ] && exit 0
        NATIVE_LOGS="${XRD_FINDER_LOG_DIR:-$SCI_LOGS}"
        mkdir -p "$NATIVE_LOGS"
        exec /usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" "$APP_ROOT/launcher/fast_start.py" \
            --in-process --data-root "$XRD_FINDER_USER_ROOT/data" --logs-root "$SCI_LOGS" "$@" \
            >>"$NATIVE_LOGS/xrd_finder_console.log" 2>&1
    else
        START_STATUS=$?
    fi
    if [ "$START_STATUS" -ne 75 ]; then
        export XRD_FINDER_STARTUP_ERROR="${XRD_FINDER_LOG_DIR:-$SCI_LOGS}/xrd_finder_console.log"
    fi
fi

show_startup_error() {
    echo "$1" >&2
    /usr/bin/osascript - "$1" <<'APPLESCRIPT' || true
on run argv
    display alert "XRD Phase Finder" message (item 1 of argv) as critical
end run
APPLESCRIPT
}

# First installation must work without Python, Tk, Homebrew or developer tools.
if [ -n "${XRD_FINDER_STARTUP_ERROR:-}" ]; then
    show_startup_error "Finder could not open. See: $XRD_FINDER_STARTUP_ERROR"
    exit 1
fi
case "${XRD_FINDER_OFFLINE:-}" in
    1|true|TRUE|yes|YES|on|ON)
        show_startup_error "Offline mode is enabled. Install the Sci runtime before launching Finder."
        exit 1
        ;;
esac
if [ -f "${XRD_FINDER_DATA_DIR:-$XRD_FINDER_USER_ROOT/data}/settings/security.json" ] && \
    grep -Eq '"offline_mode"[[:space:]]*:[[:space:]]*true' "${XRD_FINDER_DATA_DIR:-$XRD_FINDER_USER_ROOT/data}/settings/security.json"; then
    show_startup_error "Offline mode is enabled. Install the Sci runtime before launching Finder."
    exit 1
fi
FIRST_RUN="$APP_ROOT/launcher/first_run_macos.command"
if [ ! -f "$FIRST_RUN" ]; then
    show_startup_error "The environment setup script is missing. Reinstall XRD Phase Finder."
    exit 1
fi
CHOICE="$(/usr/bin/osascript <<'APPLESCRIPT'
display dialog "Prepare Python and the scientific environment now?\n\nA Terminal window will show the download and installation progress. If Python is missing, its official installer will ask for your Mac administrator password.\n\nChoose Later to prepare the environment when you next open Finder." with title "XRD Phase Finder setup" buttons {"Later", "Set up now"} default button "Set up now"
APPLESCRIPT
)" || exit 0
[[ "$CHOICE" = *"Set up now"* ]] || exit 0
printf -v SETUP_COMMAND '%q ' /bin/zsh "$FIRST_RUN" "$@"
if ! /usr/bin/osascript - "$SETUP_COMMAND" <<'APPLESCRIPT'
on run argv
    tell application "Terminal"
        activate
        do script (item 1 of argv)
    end tell
end run
APPLESCRIPT
then
    show_startup_error "Could not open Terminal. Open launcher/first_run_macos.command from the installed application to prepare the environment."
    exit 1
fi
