from __future__ import annotations

from threading import Event

import numpy as np
from PySide6.QtCore import QObject, Signal

from xrd_finder.services.overlay_observation import prepare_overlay_observation
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.structure_overlay import overlay_observation_key


class PreviewObservationController(QObject):
    """One preparation per observation, one latest preview continuation."""

    drained = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._handle = None
        self._pending = None
        self._latest = None
        self._identity = None
        self._serial = 0
        self._cancel = Event()
        self._closing = False

    @property
    def running(self):
        return self._handle is not None or self._pending is not None

    def _input_identity(self, observed):
        window = self.window
        key = overlay_observation_key(observed, window._estimate_background,
                                      window._observed_peak_positions, window._estimate_profile_fwhm)
        return id(window.project), id(window._active_pattern()), key

    def request(self, observed, cache, on_ready, on_error):
        if self._closing:
            return
        identity = self._input_identity(observed)
        continuation = (cache, on_ready, on_error)
        if (self._handle is not None and self._latest is not None
                and not self._cancel.is_set() and identity == self._identity):
            self._latest = continuation
            return
        self.invalidate()
        values = np.asarray(observed, dtype=float)
        owned = np.frombuffer(values.tobytes(), dtype=float).reshape(values.shape)
        self._pending = identity, owned, continuation
        if self._handle is None:
            self._start()

    def invalidate(self):
        self._serial += 1
        self._cancel.set()
        self._pending = None
        self._latest = None

    def _start(self):
        self._identity, observed, self._latest = self._pending
        self._pending = None
        self._cancel = Event()
        cancel, serial = self._cancel, self._serial
        handle = BackgroundTaskHandle(
            lambda: prepare_overlay_observation(observed, cancelled=cancel.is_set), self,
            operation_name='candidate.preview.prepare',
        )
        self._handle = handle
        handle.finished.connect(lambda result: self._finish(serial, result))
        handle.failed.connect(lambda message, details: self._fail(serial, message or details))
        handle.stopped.connect(self._stopped)
        handle.start()

    def _valid(self, serial):
        if self._closing or serial != self._serial or self._cancel.is_set() or self._latest is None:
            return False
        try:
            observed = self.window._active_observed_data()
            return observed is not None and self._identity == self._input_identity(observed)
        except (OSError, TypeError, ValueError):
            return False

    def _finish(self, serial, result):
        if not self._valid(serial):
            return
        cache, on_ready, _on_error = self._latest
        self._latest = None
        cache.remember(self._identity[2], *result)
        on_ready()

    def _fail(self, serial, message):
        if self._valid(serial):
            _cache, _on_ready, on_error = self._latest
            self._latest = None
            on_error(message)

    def _stopped(self):
        self._handle = None
        if self._closing:
            self.drained.emit()
        elif self._pending is not None:
            self._start()
        else:
            self._latest = None
            self._identity = None

    def request_close(self):
        self._closing = True
        self.invalidate()
        return self._handle is None
