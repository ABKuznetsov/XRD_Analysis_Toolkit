#!/bin/zsh
set -e

APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_ROOT"

export PYTHONPATH="$APP_ROOT/src${PYTHONPATH+:$PYTHONPATH}"
export QT_API=pyside6
export MPLCONFIGDIR="${TMPDIR:-/tmp}/crystal-blocks-matplotlib"
mkdir -p "$MPLCONFIGDIR"

find_python() {
    for candidate in \
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
        "../XRD_Analysis_Toolkit/.venv/bin/python" \
        "../../IR-Raman/.venv/bin/python" \
        "/usr/local/bin/python3" \
        "/opt/homebrew/bin/python3" \
        "python3"
    do
        if { [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1; } &&
           "$candidate" -c "import PySide6, numpy, scipy, pyvista, pyvistaqt, vtk, pymatgen, networkx" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "No compatible XRD/RAMAN Python environment was found."
    echo "Required: PySide6, NumPy, SciPy, PyVistaQt, VTK, pymatgen, networkx."
    read "?Press Enter to close..."
    exit 1
fi

exec "$PYTHON" -m crystal_viewer.app "$@"

