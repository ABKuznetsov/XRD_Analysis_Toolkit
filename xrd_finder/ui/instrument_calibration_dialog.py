"""Whole-pattern standard calibration preview, launched from Resolution."""
from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from xrd_finder.services.instrument_calibration import (
    calibrate_instrument, calibrated_draft, find_standard_peaks, validate_standard_data,
)
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.observed_patterns import load_observed_file_data
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog
from xrd_finder.ui.xrd_plot import create_xrd_plot_widget


class InstrumentCalibrationDialog(ScreenBoundDialog):
    parametersReady = Signal(object)

    def __init__(self, profile, *, pattern_path='', cif_path='', reference_library=None, parent=None):
        super().__init__(parent)
        self._bounds_window = parent
        while self._bounds_window is not None and self._bounds_window.parentWidget() is not None:
            self._bounds_window = self._bounds_window.parentWidget()
        self.setWindowTitle('Calibrate instrument profile')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1120, 700); self.setMinimumSize(840, 530)
        self.profile = profile
        self._reference_library = reference_library
        self._reference_picker = None
        self.data = None
        self.peaks = np.empty((0, 2))
        self.result = None
        self.busy = False
        self._job = None
        self._cancel = Event()
        self._closing = False
        self._build()
        self.cif_path.setText(cif_path)
        if pattern_path:
            # An owned timer cannot outlive a closed dialog.
            self._initial_load = QTimer(self)
            self._initial_load.setSingleShot(True)
            self._initial_load.timeout.connect(lambda: self.load_pattern(pattern_path) if not self._closing else None)
            self._initial_load.start(0)

    def _build(self):
        outer = QVBoxLayout(self)
        content = QHBoxLayout(); outer.addLayout(content, 1)
        plots = QVBoxLayout(); content.addLayout(plots, 3)
        self.plot = create_xrd_plot_widget()
        self.plot.setLabel('left', 'Intensity'); self.plot.setLabel('bottom', '2θ (°)')
        self.plot.addLegend(labelTextColor='#222222')
        self.difference = create_xrd_plot_widget()
        self.difference.setLabel('left', 'ΔI'); self.difference.setLabel('bottom', '2θ (°)')
        self.difference.setXLink(self.plot)
        self.difference.getAxis('left').setStyle(maxTickLevel=0)
        plots.addWidget(self.plot, 5); plots.addWidget(self.difference, 2)
        side = QWidget(); side.setMinimumWidth(250)
        controls = QVBoxLayout(side); controls.setContentsMargins(6, 0, 0, 0)
        content.addWidget(side, 1)
        self.pattern_path = QLineEdit(); self.pattern_path.setReadOnly(True)
        self.pattern_path.setPlaceholderText('Measured standard pattern')
        self.pattern_path.setMinimumWidth(0)
        self.load_pattern_button = QPushButton('Load standard XRD…')
        self.load_pattern_button.clicked.connect(self._browse_pattern)
        controls.addWidget(self.load_pattern_button); controls.addWidget(self.pattern_path)
        self.cif_path = QLineEdit(); self.cif_path.setPlaceholderText('Standard CIF')
        self.cif_path.setMinimumWidth(0)
        self.cif_path.textChanged.connect(self._invalidate)
        self.load_cif_button = QPushButton('Load standard CIF…')
        self.load_cif_button.clicked.connect(self._browse_cif)
        controls.addWidget(self.load_cif_button); controls.addWidget(self.cif_path)
        self.database_button = QPushButton('Choose from databases…')
        self.database_button.clicked.connect(self._choose_database_reference)
        self.database_button.setToolTip('Choose a standard CIF from project structures or configured databases.')
        controls.addWidget(self.database_button)
        self.find_peaks_button = QPushButton('Find peaks')
        self.find_peaks_button.clicked.connect(self._find_peaks)
        self.calculate_button = QPushButton('Calculate profile')
        self.calculate_button.setProperty('uiRole', 'primary')
        self.calculate_button.clicked.connect(self._calculate)
        controls.addWidget(self.find_peaks_button); controls.addWidget(self.calculate_button)
        form = QFormLayout(); form.setVerticalSpacing(5)
        self.metrics = {}
        for key, caption in (('u','U'), ('v','V'), ('w','W'), ('x','X'), ('y','Y'),
                             ('rwp','Rwp (%)'), ('rp','Rp (%)'), ('zero','Fit zero (°)')):
            value = QLabel('—'); value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.metrics[key] = value; form.addRow(caption, value)
        controls.addLayout(form)
        self.metrics['zero'].setToolTip('Calculated reflection positions + fitted zero match measured positions. This offset is not exported as broadening.')
        units = QLabel('TCH: U, V, W in °²; X, Y in °')
        units.setProperty('uiRole', 'muted'); units.setWordWrap(True); controls.addWidget(units)
        assumption = QLabel('! Coarse-grained standard: size/strain broadening is assumed negligible. All broadening is instrumental.')
        assumption.setWordWrap(True); assumption.setProperty('uiRole', 'attention'); controls.addWidget(assumption)
        controls.addStretch(1)
        self.status = QLabel('Load the measured standard and its CIF.')
        self.status.setTextFormat(Qt.TextFormat.PlainText); self.status.setWordWrap(True)
        outer.addWidget(self.status)
        buttons = QHBoxLayout(); outer.addLayout(buttons)
        self.cancel_button = QPushButton('Cancel calculation')
        self.cancel_button.clicked.connect(self._cancel_job); self.cancel_button.hide()
        buttons.addWidget(self.cancel_button); buttons.addStretch(1)
        self.use_button = QPushButton('Use parameters'); self.use_button.setProperty('uiRole', 'primary')
        self.use_button.clicked.connect(self._use_parameters)
        buttons.addWidget(self.use_button)
        close = QPushButton('Close'); close.clicked.connect(self.reject); buttons.addWidget(close)
        self._sync_controls()

    def _browse_pattern(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, 'Measured calibration standard', '',
            'XRD data (*.txt *.xy *.dat *.csv *.xye);;All files (*)')
        if path: self.load_pattern(path)

    def _browse_cif(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, 'Standard CIF', '', 'CIF (*.cif);;All files (*)')
        if path: self.cif_path.setText(path)

    def _invalidate(self, *_):
        self.result = None
        for label in self.metrics.values(): label.setText('—')
        self._sync_controls()
        self._draw()

    def _choose_database_reference(self):
        if self.busy or self._reference_library is None: return
        from xrd_finder.ui.calibration_reference_dialog import CalibrationReferenceDialog
        if self._reference_picker is not None:
            self._reference_picker.deleteLater()
        picker = CalibrationReferenceDialog(self)
        self._reference_picker = picker
        picker.cancelRequested.connect(self._cancel_job)
        def search(query):
            if self.busy: return
            picker.set_busy(True); picker.status.setText('Searching structure databases…')
            self._start_job(lambda progress: self._reference_library.search(query,
                cancelled=self._cancel.is_set, progress=progress), picker.set_rows, 'Searching reference CIFs…',
                on_error=picker.status.setText, on_stopped=lambda: picker.set_busy(False))
        def select(row):
            if self.busy: return
            picker.set_busy(True); picker.status.setText('Loading selected CIF…')
            def chosen(path):
                if not picker.isVisible(): return
                self.cif_path.setText(str(path))
                self.cif_path.setToolTip(f"{row['Source']} {row['Entry']} · {row.get('Phase','')}\n{path}")
                self._invalidate()
                self.status.setText(f"Standard CIF: {row['Source']} {row['Entry']} · {row.get('Phase','')}")
                picker.accept()
            self._start_job(lambda progress: self._reference_library.resolve(row,
                cancelled=self._cancel.is_set, progress=progress), chosen, 'Loading selected CIF…',
                on_error=picker.status.setText, on_stopped=lambda: picker.set_busy(False))
        picker.searchRequested.connect(search); picker.referenceRequested.connect(select)
        picker.show()

    def _sync_controls(self):
        self.load_pattern_button.setEnabled(not self.busy)
        self.load_cif_button.setEnabled(not self.busy)
        self.database_button.setEnabled(not self.busy and self._reference_library is not None)
        self.cif_path.setEnabled(not self.busy)
        self.find_peaks_button.setEnabled(self.data is not None and not self.busy)
        self.calculate_button.setEnabled(self.data is not None and bool(self.cif_path.text().strip()) and not self.busy)
        self.use_button.setEnabled(self.result is not None and self.result.transferable and not self.busy)
        self.cancel_button.setVisible(self.busy)
        self.cancel_button.setEnabled(self.busy and not self._cancel.is_set())

    def load_pattern(self, path):
        if self.busy or self._closing: return
        self.data = None; self.peaks = np.empty((0, 2))
        self.pattern_path.setText(str(path)); self.pattern_path.setToolTip(str(path)); self._invalidate()
        def loaded(data):
            self.data = data
            self.status.setText(f'{len(data):,} measured points · {data[0,0]:g}–{data[-1,0]:g}° 2θ')
            self._draw()
        self._start_job(lambda _progress: validate_standard_data(load_observed_file_data(path)), loaded,
                        'Loading raw standard data…')

    def _find_peaks(self):
        if self.busy or self.data is None: return
        snapshot = self.data.copy()
        def found(peaks):
            self.peaks = peaks
            self.status.setText(f'{len(peaks)} measured peaks marked. Calibration uses the whole pattern.')
            self._draw()
        self._start_job(lambda _progress: find_standard_peaks(snapshot), found, 'Finding measured peaks…')

    def _calculate(self):
        if self.busy or self.data is None: return
        data, path, profile = self.data.copy(), self.cif_path.text().strip(), self.profile
        self._invalidate()
        def completed(result):
            self.result = result
            for name in ('u', 'v', 'w', 'x', 'y'):
                self.metrics[name].setText(f'{getattr(result.profile.resolution, name):.7g}')
            self.metrics['rwp'].setText(f'{result.rwp*100.:.2f}')
            self.metrics['rp'].setText(f'{result.rp*100.:.2f}')
            self.metrics['zero'].setText(f'{result.zero_shift_deg:.3f}')
            self.status.setText(' '.join(result.diagnostics) if result.diagnostics else
                f'Calibration ready · {result.elapsed_seconds:.1f} s. Use parameters to continue in Instrument settings.')
            self._draw()
        self._start_job(lambda progress: calibrate_instrument(data, path, profile,
            cancelled=self._cancel.is_set, progress=progress), completed, 'Preparing calibration…')

    def _start_job(self, work, success, status, *, on_error=None, on_stopped=None):
        previous_result = self.result
        self._cancel = Event(); self.busy = True
        self.status.setText(status); self.status.setToolTip(''); self._sync_controls()
        handle = BackgroundTaskHandle(work, self, accepts_progress=True, operation_name='instrument.calibration')
        self._job = handle
        # The main Finder also waits for this worker before destroying its
        # child dialogs. Standalone instrument editors have no such registry.
        owner = self.parentWidget()
        while owner is not None and not hasattr(owner, '_background_task_threads'):
            owner = owner.parentWidget()
        if owner is not None: owner._background_task_threads.add(handle)
        def finished(result):
            if not self._cancel.is_set() and not self._closing: success(result)
        def failed(message, details):
            if not self._closing:
                self.status.setText('Cancelled.' if self._cancel.is_set() else (message or 'Calibration failed.'))
                self.status.setToolTip(details)
                if on_error is not None: on_error(self.status.text())
        def stopped():
            self._job = None; self.busy = False
            if self._cancel.is_set():
                self.result = previous_result
                if self.result is None:
                    for label in self.metrics.values(): label.setText('—')
                    self._draw()
                if not self._closing: self.status.setText('Cancelled.')
            self._sync_controls()
            if on_stopped is not None: on_stopped()
            if self._closing: super(InstrumentCalibrationDialog, self).reject()
            if owner is not None:
                owner._background_task_threads.discard(handle)
                if getattr(owner, '_preparation_close_confirmed', False): owner._finish_preparation_close()
        handle.finished.connect(finished); handle.failed.connect(failed)
        handle.progress.connect(lambda text, *_: self.status.setText(text) if not self._closing else None)
        handle.stopped.connect(stopped); handle.start()

    def _cancel_job(self):
        if not self.busy: return
        self._cancel.set(); self.cancel_button.setEnabled(False)
        self.status.setText('Cancelling…')

    def _draw(self):
        if not hasattr(self, 'plot'): return
        self.plot.clear(); self.difference.clear()
        if self.data is None: return
        x, y = self.data.T
        self.plot.plot(x, y, pen=pg.mkPen('#222222', width=1), name='Observed')
        if len(self.peaks):
            self.plot.plot(self.peaks[:,0], self.peaks[:,1], pen=None, symbol='o', symbolSize=6,
                symbolBrush='#d93345', symbolPen=None)
        if self.result is not None:
            result = self.result
            self.plot.plot(result.x, result.calculated, pen=pg.mkPen('#087f69', width=1.4), name='Calculated')
            self.plot.plot(result.x, result.background, pen=pg.mkPen('#8b91a0', style=Qt.PenStyle.DashLine), name='Background')
            self.difference.plot(result.x, result.residual, pen=pg.mkPen('#8056b9', width=1))
        self.plot.autoRange(padding=.025); self.difference.autoRange(padding=.025)

    def _use_parameters(self):
        if self.busy or self.result is None or not self.result.transferable: return
        draft = calibrated_draft(self.profile, self.result, standard_name=Path(self.pattern_path.text()).stem)
        self.parametersReady.emit(draft); self.accept()

    def reject(self):
        self._closing = True
        if self._reference_picker is not None and self._reference_picker.isVisible():
            self._reference_picker.reject()
        if hasattr(self, '_initial_load'): self._initial_load.stop()
        if self.busy: self._cancel_job()
        else: super().reject()

    def closeEvent(self, event):
        self.reject()
        if self.busy: event.ignore()
        else: event.accept()
