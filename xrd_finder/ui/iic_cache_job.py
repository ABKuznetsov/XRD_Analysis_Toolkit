"""Upgrade persistent reference data in idle, outside the GUI process."""
from time import monotonic
from types import SimpleNamespace
from PySide6.QtCore import QObject,QEvent,QTimer
from PySide6.QtWidgets import QApplication,QWidget
from xrd_finder.services.isolated_iic import prepare_iic_cache_isolated
from xrd_finder.services.candidate_search_service import normalize_candidate_row


class IicCacheController(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window;self._busy=False;self._paused=True
        self._all=False;self._keys=set();self._ready=set();self._last_activity=monotonic()
        self._timer=QTimer(self);self._timer.setInterval(250);self._timer.timeout.connect(self._tick)
        QApplication.instance().installEventFilter(self)

    def request(self,rows=None):
        if rows is None:self._all=True
        else:
            for row in rows:
                key=tuple(normalize_candidate_row(row)[:2])
                if all(key):self._keys.add(key)
        self._timer.start()

    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Type.MouseButtonPress,QEvent.Type.KeyPress,QEvent.Type.Wheel):
            if isinstance(watched,QWidget) and (watched is self.window or self.window.isAncestorOf(watched)):
                self._last_activity=monotonic();self._paused=True
        return False

    def _foreground_busy(self):
        w=self.window
        accepted=getattr(w,'_accepted_profile_queue',None)
        gain=getattr(w,'gain_job_controller',None)
        search=getattr(w,'_observed_search_controller',None)
        return bool(getattr(w,'_auto_search_in_progress',False)
                    or len(getattr(w,'_background_tasks',()))>int(self._busy)
                    or getattr(w,'_candidate_gain_ranking_running',False)
                    or gain is not None and gain.running
                    or search is not None and getattr(search,'running',False)
                    or accepted is not None and (accepted.current is not None or accepted.pending))

    def _tick(self):
        w=self.window
        if getattr(w,'_preparation_close_confirmed',False):
            self._paused=True;self._timer.stop();return
        self._paused=monotonic()-self._last_activity<2. or self._foreground_busy()
        if self._paused:return
        keys=[self._ready.pop() for _ in range(min(8,len(self._ready)))]
        if keys:
            for value in w.local_phase_cache.iic_entries(keys).values():
                w._refresh_calculated_iic(SimpleNamespace(result=value))
        if self._busy:return
        if not self._all and not self._keys:
            if not self._ready:self._timer.stop()
            return
        keys=None if self._all else sorted(self._keys)
        self._all=False;self._keys.clear();self._busy=True
        def task(progress,partial):
            return prepare_iic_cache_isolated(w.local_phase_cache.root,keys=keys,
                progress=progress,ready=lambda source,entry:partial((source,entry)),
                paused=lambda:self._paused,cancelled=lambda:getattr(w,'_preparation_close_confirmed',False))
        def done(count):self._busy=False
        def failed(message,details):
            self._busy=False
            if not self._paused:w._set_background_status('Reference cache update stopped: '+str(message))
        w._run_background_task('Reference cache','Updating saved reference data...',task,done,failed,
            with_progress=True,on_partial=lambda key:self._ready.add(tuple(key)),operation_name='cache.iic.upgrade')


def schedule_iic_cache_refresh(window,rows=None):
    controller=getattr(window,'_iic_cache_controller',None)
    if controller is None:controller=window._iic_cache_controller=IicCacheController(window)
    controller.request(rows)
