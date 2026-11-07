"""Warm enabled database clients after first paint, without occupying GUI jobs."""
from threading import Thread

from PySide6.QtCore import QTimer
from xrd_finder.services.security_mode import offline_mode_enabled


def schedule_database_warmup(window, *, delay_ms=2000):
    timer = QTimer(window)
    timer.setSingleShot(True)
    def start():
        timer.deleteLater()
        if offline_mode_enabled() or getattr(window, '_preparation_close_confirmed', False):
            return
        services = []
        if window.settings.value('sources/cod_online', True, type=bool):
            services.append(window.cod_online)
        mp = window.materials_project
        if mp.api_key and window.settings.value('materials_project/enabled', False, type=bool):
            services.append(mp)
        def warm(service):
            try:
                service.warm_up()
            except Exception:
                # A warmup is optional. The real search retains normal errors
                # and retries; offline servers must never block application use.
                pass
        for service in services:
            Thread(target=warm, args=(service,), name='xrd-database-warmup', daemon=True).start()
    timer.timeout.connect(start)
    timer.start(delay_ms)
