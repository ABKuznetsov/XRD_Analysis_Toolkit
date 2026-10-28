from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from xrd_finder.services.gain_shortlist import common_zero_shift
from xrd_finder.services.observed_search_preparation import (
    ObservedSearchInput, ObservedSearchResult, prepare_observed_search,
)
from xrd_finder.ui.background_task import BackgroundTaskHandle


@dataclass(frozen=True, slots=True)
class ObservedSearchCapture:
    identity: tuple
    auto_cache_key: tuple | None
    inputs: ObservedSearchInput

    @property
    def measurement_key(self):
        # The last identity field guards request lifecycle, not peak physics.
        # Keep full identity validation when applying to the current window.
        return self.identity[:-1]


def capture_observed_search(window) -> ObservedSearchCapture | None:
    pattern = window._active_pattern()
    auto = getattr(window, '_scoring_source', 'Auto') == 'Auto'
    observed = window._active_observed_data() if auto else window._active_scoring_observed_data()
    if pattern is None or observed is None or not len(observed):
        return None
    profile = window._instrument_profile_for_pattern(pattern)
    removed = window._pattern_scoring_background_removed(pattern)
    wavelength, doublet = window._legacy_radiation_for_pattern(pattern)
    zero = common_zero_shift(getattr(window, 'match_zero_shifts', {}).values())
    auto_key = window._auto_scoring_cache_key(pattern, observed) if auto else None
    identity = (
        id(window.project), id(pattern), pattern.id, str(pattern.source_path),
        window._processed_probability_signature(observed),
        getattr(window, '_scoring_source', 'Auto'), bool(removed),
        bool(window.normalize_observed_patterns),
        tuple(tuple(bounds) for bounds in getattr(pattern, 'crop_ranges', ())),
        float(wavelength), bool(doublet),
        profile.calculation_key() if profile is not None else None, float(zero),
        window._finder_background_signature(window._pattern_finder_background_data(pattern)),
        tuple((item.get('Source', ''), item.get('Entry', '')) for item in window.match_candidates),
        getattr(window, '_candidate_search_request_token', 0),
    )
    preprocessing = getattr(window, '_auto_scoring_cache', {}).get(auto_key) if auto else None
    return ObservedSearchCapture(identity, auto_key, ObservedSearchInput(
        observed, auto, removed, profile, preprocessing, float(zero),
    ))


def observed_search_watch_key(window):
    # Check full array contents and instrument identity again before applying.
    pattern = window._active_pattern()
    return (
        id(window.project), id(pattern), getattr(pattern, 'source_path', None),
        getattr(window, '_scoring_source', 'Auto'), bool(window.normalize_observed_patterns),
        id(getattr(pattern, 'processed_points', None)),
        len(getattr(pattern, 'processed_points', ())),
        getattr(pattern, 'processed_background_removed', False),
        tuple(tuple(bounds) for bounds in getattr(pattern, 'crop_ranges', ())),
        getattr(window, '_candidate_search_request_token', 0),
        tuple(getattr(window, 'match_zero_shifts', {}).items()),
    )


def apply_observed_search_result(window, capture, result):
    result = deepcopy(result)
    if result.preprocessing is not None:
        window._auto_scoring_cache[capture.auto_cache_key] = result.preprocessing
        window._trim_auto_scoring_cache()
    key = window._active_probability_context_key()
    window._observed_probability_cache = (key, result.x, result.corrected, result.records)


class ObservedSearchController(QObject):
    drained = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._handle = None
        self._pending = None
        self._serial = 0
        self._cancel = Event()
        self._closing = False
        self._completed = None
        self._monitor = QTimer(self)
        self._monitor.setInterval(80)
        self._monitor.timeout.connect(self._check_inputs)

    @property
    def running(self):
        return self._handle is not None or self._pending is not None

    def invalidate(self):
        self._serial += 1
        self._cancel.set()
        self._pending = None
        self._monitor.stop()

    def request(self, on_success):
        if self._closing:
            return
        self.invalidate()
        try:
            capture = capture_observed_search(self.window)
        except Exception as exc:
            self._show_error(str(exc))
            return
        if capture is None:
            self._no_peaks()
            return
        self._pending = (capture, on_success)
        self.window._set_auto_search_busy(True)
        self.window._set_background_status('Preparing observed peaks...')
        if self._handle is None:
            self._start()

    def _start(self):
        capture, on_success = self._pending
        self._pending = None
        self._watch_key = observed_search_watch_key(self.window)
        serial = self._serial
        self._cancel = Event()
        cancel = self._cancel
        if self._completed is not None and self._completed[0] == capture.measurement_key:
            self._finish(serial, capture, on_success, self._completed[1])
            return
        inputs = capture.inputs
        handle = BackgroundTaskHandle(
            lambda: prepare_observed_search(inputs, cancelled=cancel.is_set), self,
            operation_name='match.prepare.observed',
        )
        self._handle = handle
        handle.finished.connect(lambda result: self._finish(serial, capture, on_success, result))
        handle.failed.connect(lambda message, details: self._fail(serial, capture, message or details))
        handle.stopped.connect(self._stopped)
        self._monitor.start()
        handle.start()

    def _check_inputs(self):
        if self._watch_key != observed_search_watch_key(self.window):
            self._discard()

    def _discard(self):
        self.invalidate()
        self.window._set_auto_search_busy(False)
        self.window._set_background_status('Observed data changed; run search again')

    def _finish(self, serial, capture, on_success, result: ObservedSearchResult):
        if self._closing or serial != self._serial or self._cancel.is_set():
            return
        self._monitor.stop()
        if not self._verify_capture(capture):
            return
        if not result.records:
            self._no_peaks()
            return
        self._completed = (capture.measurement_key, result)
        apply_observed_search_result(self.window, capture, result)
        on_success(capture, deepcopy(result))

    def _verify_capture(self, capture):
        try:
            current = capture_observed_search(self.window)
        except Exception as exc:
            self._show_error(str(exc))
            return False
        if current is None or current.identity != capture.identity:
            self._discard()
            return False
        return True

    def _fail(self, serial, capture, message):
        if not self._closing and serial == self._serial and not self._cancel.is_set():
            self._monitor.stop()
            if self._verify_capture(capture):
                self._show_error(message)

    def _show_error(self, message):
        self.window._set_auto_search_busy(False)
        self.window._set_background_status('Observed peak preparation failed')
        QMessageBox.warning(self.window, 'Identify phases preparation failed', message)

    def _no_peaks(self):
        self.window._set_auto_search_busy(False)
        self.window._set_background_status('No usable peaks in the active pattern')
        QMessageBox.information(self.window, 'Identify phases', 'No usable peaks were detected in the active pattern.')

    def _stopped(self):
        self._handle = None
        if self._closing:
            self._pending = None
            self.drained.emit()
        elif self._pending is not None:
            self._start()

    def request_close(self):
        self._closing = True
        self.invalidate()
        return self._handle is None
