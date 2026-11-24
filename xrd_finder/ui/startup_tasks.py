"""Give first paint and project restoration priority over optional startup work."""
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox

from xrd_finder.services.runtime_diagnostics import trace_operation


class StartupTasks(QObject):
    def __init__(self, window, restore, ready, delay_ms, background_delay_ms):
        super().__init__(window)
        self.window = window
        self.restore = restore
        self.ready = ready
        self.background_delay_ms = background_delay_ms
        self._science_warmup_thread = None
        self._was_enabled = window.isEnabled()
        if restore is not None:
            window.setEnabled(False)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._finish_opening)
        self.background_timer = QTimer(self)
        self.background_timer.setSingleShot(True)
        self.background_timer.timeout.connect(lambda: self._start_background())
        self.timer.start(delay_ms)

    def _available(self):
        return (self.window.isVisible()
                and not getattr(self.window, '_preparation_close_confirmed', False))

    def _finish_opening(self):
        if not self._available():
            self.window.setEnabled(self._was_enabled)
            return
        try:
            if self.restore is not None:
                with trace_operation('startup.restore_project', slow_ms=0):
                    self.restore()
        except Exception as error:
            QMessageBox.warning(self.window, 'Open project failed', str(error))
        finally:
            self.window.setEnabled(self._was_enabled)
        if not self._available():
            return
        if self.ready is not None:
            self.ready()
        self._start_science_warmup()
        self.background_timer.start(self.background_delay_ms)

    def _start_science_warmup(self):
        if self._science_warmup_thread is not None or not self._available():
            return
        from threading import Event, Thread
        from xrd_finder.services.science_warmup import warm_calculation_modules
        cancelled = Event()
        self.window.destroyed.connect(lambda *_: cancelled.set())
        self._science_warmup_thread = Thread(
            target=warm_calculation_modules,
            kwargs={'cancelled': cancelled.is_set},
            name='xrd-calculation-warmup',
            daemon=True,
        )
        self._science_warmup_thread.start()

    def _start_background(self):
        if not self._available():
            return
        from xrd_finder.ui.deferred_updates import schedule_update_check
        from xrd_finder.ui.database_warmup import schedule_database_warmup
        from xrd_finder.ui.import_cleanup_job import schedule_import_cleanup
        from xrd_finder.ui.learning_startup import schedule_learning_offer
        schedule_update_check(self.window)
        schedule_database_warmup(self.window)
        schedule_import_cleanup(self.window)
        schedule_learning_offer(self.window)
        self.window._start_match_pdf2_preload()


def schedule_startup_tasks(window, *, restore=None, ready=None,
                           delay_ms=150, background_delay_ms=5000):
    controller = StartupTasks(window, restore, ready, delay_ms, background_delay_ms)
    window._startup_tasks = controller
    return controller
