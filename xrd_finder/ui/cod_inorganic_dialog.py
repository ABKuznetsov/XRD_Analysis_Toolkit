"""Explicit download/preparation of the identifier-only inorganic COD selection."""
import json
import threading
import math
import time

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout

from xrd_finder.services.cod_inorganic_library import (
    SELECTION_DATE, SELECTION_SOURCE, load_selection, prepare_inorganic_library,
)
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


class CodInorganicDialog(ScreenBoundDialog):
    def __init__(self, controller):
        super().__init__(controller.owner)
        self.controller = controller
        self.setWindowTitle('Inorganic COD library')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(680, 470)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        self.description = QLabel(
            f'<b>{len(load_selection()):,} COD structures</b> · selection {SELECTION_DATE}<br><br>'
            'Finder contains only the COD identifier list. Original CIF files are downloaded '
            'from COD in batches. Download and local CrIStMa calculation run in parallel to prepare the SQLite search index.<br><br>'
            'This is a large library. Download and calculation time depends on your connection and computer. '
            'You can cancel and continue later: downloaded CIFs and successfully prepared records are retained. '
            'Unchanged, current records are not recalculated.<br><br>'
            f'Selection source: <a href="{SELECTION_SOURCE}">Crystal Impact COD Inorganics</a>')
        self.description.setWordWrap(True)
        self.description.setOpenExternalLinks(True)
        layout.addWidget(self.description)
        self.status = QLabel('Press Download and prepare SQL to start or continue.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.download_label = QLabel('CIF download: waiting to start')
        self.download_label.setWordWrap(True)
        layout.addWidget(self.download_label)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0,len(load_selection()))
        self.download_progress.setValue(0)
        layout.addWidget(self.download_progress)
        self.sql_label = QLabel('SQL preparation: waiting to start')
        self.sql_label.setWordWrap(True)
        layout.addWidget(self.sql_label)
        self.sql_progress = QProgressBar()
        self.sql_progress.setRange(0,len(load_selection()))
        self.sql_progress.setValue(0)
        layout.addWidget(self.sql_progress)
        self.time_label = QLabel('Elapsed: 0 s · remaining: estimating…')
        self.time_label.setWordWrap(True)
        layout.addWidget(self.time_label)
        row = QHBoxLayout()
        self.start_button = QPushButton('Download and prepare SQL')
        self.start_button.clicked.connect(controller.start)
        self.cancel_button = QPushButton('Close')
        self.cancel_button.clicked.connect(self.close)
        row.addWidget(self.start_button)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)

    def closeEvent(self, event):
        if self.controller.running:
            self.controller.cancel()
            self.status.setText('Stopping… Completed downloads and SQL records will be retained.')
            self.cancel_button.setEnabled(False)
            event.ignore()
        else:
            event.accept()

    def reject(self):
        self.close()


class CodInorganicController(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.running = False
        self.cancel_event = threading.Event()
        self.dialog = CodInorganicDialog(self)
        self.handle = None
        self.latest_progress = None
        self.started_at = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_time)

    def show(self):
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def cancel(self):
        self.cancel_event.set()

    def start(self):
        if self.running:
            return
        self.running = True
        self.cancel_event.clear()
        self.latest_progress = None
        self.started_at = time.monotonic()
        for bar in (self.dialog.download_progress,self.dialog.sql_progress):
            bar.setRange(0,len(load_selection()))
            bar.setValue(0)
        self.dialog.download_label.setText('CIF download: checking existing files…')
        self.dialog.sql_label.setText('SQL preparation: checking current records…')
        self._refresh_time()
        self.timer.start()
        self.dialog.start_button.setEnabled(False)
        self.dialog.cancel_button.setEnabled(True)
        self.dialog.cancel_button.setText('Cancel')
        self.dialog.status.setText('Checking downloaded CIFs and prepared SQL records…')
        panel = getattr(self.owner,'database_panel',None)
        if panel is not None:
            panel.setEnabled(False)
        cache = self.owner.local_phase_cache
        self.handle = handle = BackgroundTaskHandle(
            lambda emit,partial: prepare_inorganic_library(cache,progress=emit,status=partial,
                                                           cancelled=self.cancel_event.is_set),
            self.owner,accepts_progress=True,accepts_partial=True,operation_name='database.cod_inorganic')
        self.owner._background_tasks.add(handle)
        self.owner._background_task_threads.add(handle)
        handle.progress.connect(self._progress)
        handle.partial.connect(self._snapshot)
        handle.finished.connect(self._finished)
        handle.failed.connect(self._failed)
        handle.stopped.connect(lambda: self._stopped(handle))
        handle.start()

    def _progress(self, text, value, maximum):
        if getattr(self.owner,'_preparation_close_confirmed',False):
            return
        self.dialog.status.setText(f'{text}: {value:,} / {maximum:,}')
        self.owner._set_background_status(f'{text}: {value:,} / {maximum:,}')

    def _snapshot(self, shot):
        self.latest_progress = shot
        self.dialog.download_progress.setRange(0,shot.total)
        self.dialog.download_progress.setValue(shot.available+shot.download_failed)
        self.dialog.sql_progress.setRange(0,shot.total)
        self.dialog.sql_progress.setValue(shot.processed)
        self.dialog.download_label.setText(
            f'CIF download: {shot.available:,} / {shot.total:,} available · reused {shot.reused:,}'
            f' · failed {shot.download_failed:,} · remaining: {_duration(shot.download_seconds)}')
        self.dialog.sql_label.setText(
            f'SQL preparation: {shot.processed:,} / {shot.total:,} checked'
            f' · ready {shot.prepared+shot.skipped:,}'
            f' · unavailable {shot.download_failed+shot.preparation_failed:,}'
            f' · remaining: {_duration(shot.processing_seconds)}')
        if self.running and not self.cancel_event.is_set() and shot.available:
            self.dialog.status.setText('Preparing SQL…' if shot.download_finished else
                                       'Downloading CIFs and preparing SQL in parallel…')
        self._refresh_time()

    def _refresh_time(self):
        shot = self.latest_progress
        elapsed = time.monotonic()-self.started_at if self.started_at is not None else (shot.elapsed_seconds if shot else 0.)
        remaining = shot.remaining_seconds if shot else None
        self.dialog.time_label.setText(f'Elapsed: {_duration(elapsed)} · remaining: {_duration(remaining)}')

    def _finished(self, result):
        self.timer.stop()
        self._refresh_time()
        if result.cancelled:
            self.dialog.time_label.setText(self.dialog.time_label.text().split(' · remaining:')[0]+' · cancelled')
        title = 'Cancelled' if result.cancelled else 'Finished'
        text = (f'{title}. Downloaded: {result.downloaded:,}; reused CIFs: {result.reused:,}; '
                f'prepared now: {result.prepared:,}; already ready: {result.skipped:,}; '
                f'not downloaded: {len(result.download_failed):,}; not prepared: {len(result.preparation_failed):,}.')
        if result.failed:
            path = self.owner.local_phase_cache.root/'cod_inorganic_failures.json'
            try:
                path.write_text(json.dumps(dict(download=result.download_failed,preparation=result.preparation_failed),
                                           ensure_ascii=False, indent=2),encoding='utf-8')
                text += f'\nDetails: {path}'
            except OSError as error:
                text += '\nCould not save failure details: '+str(error)
        self.dialog.status.setText(text)
        if result.prepared or result.skipped:
            self.owner.settings.setValue('sources/cod_local', True)
            if self.owner.database_panel is not None:
                self.owner.database_panel.set_source_checked('sources/cod_local', True)
        if not getattr(self.owner,'_preparation_close_confirmed',False):
            self.owner._refresh_database_rows()
            self.owner._set_background_status(text)
        self.owner._background_tasks.discard(self.handle)

    def _failed(self, message, details):
        self.timer.stop()
        self._refresh_time()
        self.dialog.time_label.setText(self.dialog.time_label.text().split(' · remaining:')[0]+' · stopped')
        self.dialog.status.setText('Preparation stopped: '+(message or details))
        self.owner._background_tasks.discard(self.handle)

    def _stopped(self, handle):
        self.timer.stop()
        self.owner._background_task_threads.discard(handle)
        self.running = False
        self.handle = None
        self.dialog.start_button.setEnabled(True)
        self.dialog.cancel_button.setEnabled(True)
        self.dialog.cancel_button.setText('Close')
        panel = getattr(self.owner,'database_panel',None)
        if panel is not None:
            panel.setEnabled(True)
        if getattr(self.owner,'_preparation_close_confirmed',False):
            self.owner._finish_preparation_close()


def _duration(seconds):
    if seconds is None:
        return 'estimating…'
    seconds = max(0,math.ceil(seconds))
    if seconds < 60:
        return f'{seconds} s'
    minutes = math.ceil(seconds/60)
    if minutes < 60:
        return f'{minutes} min'
    hours,minutes = divmod(minutes,60)
    return f'{hours} h {minutes} min'
