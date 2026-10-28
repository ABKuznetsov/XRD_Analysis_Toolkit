"""Numeric controls for one absolute manual angular correction."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout

from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


class ManualCalibrationDialog(ScreenBoundDialog):
    def __init__(self, parent, pattern_name, correction, can_reset):
        super().__init__(parent)
        self.setWindowTitle('Manual angle calibration')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(400, 260)
        self.resize(480, 280)
        layout = QVBoxLayout(self)
        title = QLabel(pattern_name)
        title.setWordWrap(True)
        layout.addWidget(title)
        hint = QLabel('Adjust the total correction with the number or arrows. '
            'Positive values move measured peaks to lower angles.\n'
            'Corrected 2θ = original 2θ − correction.\n'
            'The main plot is a preview until you press Apply. '
            'Display-only zero correction is paused during this preview.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.correction = QDoubleSpinBox()
        self.correction.setDecimals(4)
        self.correction.setRange(-125., 125.)
        self.correction.setSingleStep(.01)
        self.correction.setSuffix(' °')
        self.correction.setValue(correction)
        self.correction.setAccessibleName('Total manual 2theta correction')
        form = QFormLayout()
        form.addRow('Total 2θ correction', self.correction)
        layout.addLayout(form)
        note = QLabel('Apply affects this measurement and its calculations. '
            'Reset undoes calibration and subsequent dependent processing. '
            'The source file and instrument profile are preserved.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Reset | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setProperty('uiRole', 'primary')
        self.reset_button = buttons.button(QDialogButtonBox.Reset)
        self.reset_button.setEnabled(can_reset)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
