"""Warn once about loaded data outside the viewing range, without discarding it."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


def warn_outside_xrd_range(owner, pattern, values):
    if getattr(pattern, 'input_kind', '') == 'peak_list': return
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if not len(x): return
    low, high = float(np.min(x)), float(np.max(x))
    if low >= -1e-7 and high <= 125.+1e-7: return
    seen = getattr(owner, '_xrd_range_warnings', None)
    if seen is None:
        seen = owner._xrd_range_warnings = {}
    key = (id(owner.project), id(pattern), low, high)
    if key in seen: return
    seen[key] = f'{pattern.name}: {low:.6g}–{high:.6g}°'
    dialog = getattr(owner, '_xrd_range_warning_dialog', None)
    if dialog is None:
        dialog = owner._xrd_range_warning_dialog = QMessageBox(owner)
        dialog.setWindowTitle('XRD data outside viewing range')
        dialog.setIcon(QMessageBox.Warning)
        dialog.setStandardButtons(QMessageBox.Ok)
        dialog.setWindowFlags(Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        dialog.setAttribute(Qt.WA_ShowWithoutActivating, True)
        dialog.setWindowModality(Qt.NonModal)
    dialog.setText('Loaded XRD data extend outside 0–125°.\n'
        'The plot is limited to 0–125°; the complete measured data and source file are kept.\n\n'
        +'\n'.join(list(seen.values())[-5:]))
    dialog.show()
