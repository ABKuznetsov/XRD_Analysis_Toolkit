#!/bin/zsh
# Runs in a visible Terminal, including when the Mac has no Python at all.
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCI_ROOT="$HOME/Library/Application Support/Sci"
LOG_FILE="$SCI_ROOT/logs/setup.log"

echo "XRD Phase Finder — first-time environment setup"
echo "Python (if needed) → scientific environment → Finder"
echo "Downloads can take several minutes. Progress is shown here."
echo "Setup log: $LOG_FILE"
echo
/bin/zsh "$APP_ROOT/launcher/setup_sci_env.command"
SETUP_STATUS=$?
if [ "$SETUP_STATUS" -ne 0 ]; then
    echo
    echo "Setup did not complete (exit $SETUP_STATUS). Finder has not been started."
    echo "See the error above and the full log: $LOG_FILE"
    if [ -f "$LOG_FILE" ]; then
        tail -n 15 "$LOG_FILE"
    fi
    read -r "?Press Enter to close this setup window..."
    exit "$SETUP_STATUS"
fi
echo
echo "Environment ready. Opening XRD Phase Finder..."
exec /bin/zsh "$APP_ROOT/launcher/launch_xrd_finder_preview.command" "$@"
