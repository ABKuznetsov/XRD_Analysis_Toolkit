"""Recover tracked import scratch in idle, never in the GUI thread."""
from threading import Event
from time import monotonic
from PySide6.QtCore import QObject,QEvent,QTimer
from PySide6.QtWidgets import QApplication,QWidget

from xrd_finder.services.import_recovery import cleanup_interrupted_imports
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.library_storage_migration import _busy


class ImportCleanupController(QObject):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner=owner;self.running=False;self._pending=False
        self._last_activity=monotonic();self._cancel=Event();self.result=None
        self._timer=QTimer(self);self._timer.setInterval(250);self._timer.timeout.connect(self._tick)
        QApplication.instance().installEventFilter(self)

    def request(self):
        self._pending=True;self._last_activity=monotonic();self._timer.start()

    def cancel(self):
        self._pending=False;self._cancel.set();self._timer.stop()

    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Type.MouseButtonPress,QEvent.Type.KeyPress,QEvent.Type.Wheel):
            if isinstance(watched,QWidget) and (watched is self.owner or self.owner.isAncestorOf(watched)):
                self._last_activity=monotonic()
                if self.running:self._cancel.set();self._pending=True
        return False

    def _tick(self):
        owner=self.owner
        if getattr(owner,'_preparation_close_confirmed',False):self.cancel();return
        if self.running or not self._pending:return
        if monotonic()-self._last_activity<2. or _busy(owner):return
        self._pending=False;self.running=True;self.result=None;self._cancel.clear()
        handle=BackgroundTaskHandle(lambda emit:cleanup_interrupted_imports(owner.local_phase_cache,
            progress=emit,cancelled=self._cancel.is_set),owner,accepts_progress=True,
            operation_name='database.import.cleanup')
        owner._background_tasks.add(handle);owner._background_task_threads.add(handle)

        def done(result):
            self.result=result
            self._pending=self._pending or result.more_pending or bool(result.active_batches or result.deferred_batches)
            owner._background_tasks.discard(handle)

        def failed(message,details):
            owner._background_tasks.discard(handle)
            if not self._cancel.is_set() and not getattr(owner,'_preparation_close_confirmed',False):
                owner._set_background_status('Import cleanup deferred: '+str(message or details))

        def stopped():
            owner._background_task_threads.discard(handle);self.running=False
            if getattr(owner,'_import_cleanup_close_pending',False):
                owner._import_cleanup_close_pending=False;owner.close();return
            if getattr(owner,'_preparation_close_confirmed',False):
                owner._finish_preparation_close();return
            if self.result is not None and self.result.files_removed and not _busy(owner):
                owner._set_background_status(f'Cleaned {self.result.files_removed} interrupted import files.')
            if self._pending:
                self._last_activity=monotonic();self._timer.start()
            else:self._timer.stop()

        handle.finished.connect(done);handle.failed.connect(failed);handle.stopped.connect(stopped)
        handle.start()


def schedule_import_cleanup(owner):
    if getattr(owner,'_preparation_close_confirmed',False):return None
    controller=getattr(owner,'_import_cleanup_controller',None)
    if controller is None:controller=owner._import_cleanup_controller=ImportCleanupController(owner)
    controller.request()
    return controller
