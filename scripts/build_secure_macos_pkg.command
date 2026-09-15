#!/bin/zsh
set -e
export COPYFILE_DISABLE=1

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

cd "$ROOT"
exec "$PYTHON" -m xrd_finder.tools.secure_macos_installer --app-root "$ROOT" --output-dir "$ROOT/dist" "$@"
