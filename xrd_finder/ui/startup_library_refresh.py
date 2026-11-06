"""A visible required upgrade gate before the main window constructs its services."""
from threading import Event
from time import monotonic
import json
from pathlib import Path

from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QDialog,QHBoxLayout,QLabel,QMessageBox,QProgressBar,QPushButton,QVBoxLayout

from xrd_finder.services.cache_paths import default_phase_cache_root
from xrd_finder.services.cache_storage import COMPACT_STORAGE_VERSION
from xrd_finder.services.startup_library_refresh import inspect_legacy_library,refresh_legacy_library
from xrd_finder.ui.app_settings import app_settings
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog
from xrd_finder.ui.theme import is_dark_theme,window_style,theme_colors


class StartupLibraryRefreshDialog(ScreenBoundDialog):
    def __init__(self,root,info,*,api_key='',refresh=refresh_legacy_library):
        super().__init__()
        self.root=root;self.api_key=api_key;self.refresh=refresh
        self.running=False;self.outcome=None;self.cancel_event=Event();self.exit_pending=False;self.skipped=False
        self.setWindowTitle('Update your XRD library')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        dark=is_dark_theme(self);c=theme_colors(dark)
        self.setStyleSheet(window_style(dark)+f'''
            QProgressBar {{ background:{c['input']}; color:{c['text']}; border:1px solid {c['border']};
                border-radius:4px; min-height:20px; text-align:center; }}
            QProgressBar::chunk {{ background:#087f69; border-radius:3px; }}
            QPushButton#startupUpdate {{ background:#087f69; color:white; border-color:#119b7f; }}
            QPushButton#startupUpdate:disabled {{ background:{c['alt']}; color:{c['muted']}; }}
        ''')
        self.resize(660,360)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,20,24,20);layout.setSpacing(14)
        heading=QLabel('Update your library for Finder 1.7.0')
        heading.setStyleSheet('font-size:20px;font-weight:600;');heading.setWordWrap(True);layout.addWidget(heading)
        info_label=QLabel(f'Found {info.cards:,} cards in the previous storage format. '
            'Finder will download available online CIFs again, prepare reference profiles and update the library. '
            'Local CIFs and cards that cannot be downloaded will be preserved. '
            'Only one working database will remain. Internet access and temporary disk space are needed.')
        info_label.setWordWrap(True);info_label.setStyleSheet('font-size:14px;');layout.addWidget(info_label)
        self.status=QLabel('Update now, or keep your existing library and skip this offer permanently.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,1);layout.addWidget(self.progress_bar)
        self.counts=QLabel('');layout.addWidget(self.counts)
        self.activity=QLabel('');layout.addWidget(self.activity)
        row=QHBoxLayout();row.addStretch(1)
        self.exit_button=QPushButton('Exit');self.exit_button.clicked.connect(self.close)
        self.skip_button=QPushButton("Skip and don't ask again");self.skip_button.clicked.connect(self.skip)
        self.update_button=QPushButton('Update library');self.update_button.clicked.connect(self.begin)
        self.update_button.setObjectName('startupUpdate')
        row.addWidget(self.exit_button);row.addWidget(self.skip_button);row.addWidget(self.update_button);layout.addLayout(row)
        self.pulse_timer=QTimer(self);self.pulse_timer.setInterval(300);self.pulse_timer.timeout.connect(self.pulse)
        self.started=0.;self.pulses=0
        for widget in (self.progress_bar,self.counts,self.activity):widget.hide()

    def pulse(self):
        self.pulses+=1;seconds=int(monotonic()-self.started)
        self.activity.setText(f'Working{"."*(self.pulses%4)}  ·  {seconds//60:02d}:{seconds%60:02d} elapsed')

    def begin(self):
        if self.running:return
        if self.outcome is not None and self.outcome.activated:
            self.accept();return
        self.running=True;self.outcome=None;self.cancel_event.clear();self.exit_pending=False
        self.started=monotonic();self.pulse();self.pulse_timer.start()
        for widget in (self.progress_bar,self.counts,self.activity):widget.show()
        self.update_button.setEnabled(False);self.skip_button.setEnabled(False);self.exit_button.setText('Cancel and exit')
        self.status.setText('Preparing library update…');self.progress_bar.setRange(0,0)
        handle=BackgroundTaskHandle(lambda emit:self.refresh(self.root,api_key=self.api_key,
            progress=emit,cancelled=self.cancel_event.is_set),self,accepts_progress=True,
            operation_name='database.startup.refresh')
        self.handle=handle
        def progress(label,value,maximum):
            self.status.setText(label);self.progress_bar.setRange(0,maximum);self.progress_bar.setValue(value)
            self.counts.setText(f'{value:,} / {maximum:,}' if maximum else 'In progress…')
        def finished(result):
            self.outcome=result
            text=f'Library updated: {result.cards:,} cards. Downloaded {result.downloaded:,} CIFs; prepared {result.prepared:,} profiles.'
            if result.failures:
                text+=f' {len(result.failures):,} cards could not be refreshed; their saved data were retained.'
            if result.notice:text+='\n'+result.notice
            self.status.setText(text);self.progress_bar.setRange(0,1);self.progress_bar.setValue(1)
        def failed(message,details):
            self.status.setText('Update stopped. Your saved library is retained.\n'+(message or details))
            self.progress_bar.setRange(0,1);self.progress_bar.setValue(0)
        def stopped():
            self.running=False;self.pulse_timer.stop();self.activity.setText('')
            self.exit_button.setText('Exit');self.exit_button.setEnabled(True)
            self.update_button.setEnabled(True);self.skip_button.setEnabled(True)
            if self.exit_pending:self.reject()
            elif self.outcome is not None and self.outcome.activated:
                if self.outcome.failures or self.outcome.notice:self.update_button.setText('Continue to Finder')
                else:self.accept()
            else:self.update_button.setText('Retry update')
        handle.progress.connect(progress);handle.finished.connect(finished)
        handle.failed.connect(failed);handle.stopped.connect(stopped);handle.start()

    def skip(self):
        if not self.running:
            self.skipped=True;self.accept()

    def closeEvent(self,event):
        if self.running:
            self.exit_pending=True;self.cancel_event.set();self.exit_button.setEnabled(False)
            self.status.setText('Stopping update… Waiting for downloads and calculations to finish safely.')
            event.ignore()
        else:super().closeEvent(event)

    def reject(self):
        if self.running:self.close()
        else:super().reject()


def offer_startup_library_refresh(root=None,*,settings=None):
    root=default_phase_cache_root() if root is None else root
    settings=app_settings() if settings is None else settings
    path=str((Path(root)/'index.sqlite').resolve())
    try:remembered=json.loads(str(settings.value('database/startup_library_refresh','',type=str) or '{}'))
    except (ValueError,TypeError):remembered={}
    if (isinstance(remembered,dict) and remembered.get('path')==path
            and remembered.get('format')==COMPACT_STORAGE_VERSION and remembered.get('decision') in ('updated','skipped')):
        return True
    try:info=inspect_legacy_library(root)
    except Exception as error:
        QMessageBox.warning(None,'Library update','Cannot read the existing library. Your files were retained.\n'+str(error))
        return False
    if info is None:
        if Path(path).is_file():
            settings.setValue('database/startup_library_refresh',json.dumps(dict(
                path=path,format=COMPACT_STORAGE_VERSION,decision='updated')))
            settings.sync()
        return True
    key=str(settings.value('materials_project/api_key','',type=str) or '')
    dialog=StartupLibraryRefreshDialog(root,info,api_key=key)
    app=QApplication.instance();quit_on_close=app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    try:
        accepted=dialog.exec()==QDialog.DialogCode.Accepted
        if accepted and (dialog.skipped or dialog.outcome is not None and dialog.outcome.activated):
            settings.setValue('database/startup_library_refresh',json.dumps(dict(
                path=path,format=COMPACT_STORAGE_VERSION,decision='skipped' if dialog.skipped else 'updated')))
            settings.sync()
        return accepted
    finally:
        app.setQuitOnLastWindowClosed(quit_on_close)
        dialog.deleteLater()
