"""Reviewable, cancellable working-library optimization in an owned Qt worker."""
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QHBoxLayout,QLabel,QProgressBar,QPushButton,QVBoxLayout

from xrd_finder.services.cache_storage import CURRENT_STORAGE_VERSION
from xrd_finder.services.library_storage_migration import migrate_library_storage
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


def _busy(owner):
    if (getattr(owner,'_preparation_close_confirmed',False)
            or getattr(owner,'_library_storage_migration_active',False)
            or getattr(owner,'_background_task_threads',None)
            or getattr(owner,'_background_tasks',None)
            or getattr(owner,'_auto_search_in_progress',False)
            or getattr(owner,'_candidate_gain_ranking_running',False)
            or getattr(owner,'_candidate_gain_idle_check_pending',False)):
        return True
    for name in ('gain_job_controller','_observed_search_controller','preview_observation_controller',
                 '_cod_inorganic_controller','_prepared_library_transfer','_loaded_match_queue'):
        controller = getattr(owner,name,None)
        if controller is not None and (getattr(controller,'running',False) or getattr(controller,'pending',None)):
            return True
    accepted = getattr(owner,'_accepted_profile_queue',None)
    if accepted is not None and (accepted.current is not None or accepted.pending):
        return True
    visible = getattr(owner,'visible_profile_calculation_queue',None)
    if visible is not None and visible.is_busy:
        return True
    service = getattr(owner,'candidate_search_service',None)
    queue = getattr(service,'preparation_queue',None)
    if queue is not None:
        progress = queue.progress()
        if any(getattr(progress,field,0) for field in ('queued','downloading','indexing')):
            return True
    return False


class _MigrationDialog(ScreenBoundDialog):
    def __init__(self,controller):
        super().__init__(controller.owner)
        self.controller = controller
        self.setWindowTitle('Optimize library storage')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(640,300)
        layout = QVBoxLayout(self)
        info = QLabel('Use compact SQL storage without recalculating CIFs. A verified backup of '
                      'the original library is saved first. Temporary free disk space is required. '
                      'Close other Finder windows before starting.')
        info.setWordWrap(True);layout.addWidget(info)
        path = QLabel(str(controller.owner.local_phase_cache.index_path))
        path.setWordWrap(True);path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path)
        self.status = QLabel('Ready. Existing calculations and CIF paths will be preserved.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress = QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.backup = QLabel('Original backup: '+str(controller.owner.local_phase_cache.root/'storage_backups'))
        self.backup.setWordWrap(True);self.backup.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.backup)
        buttons = QHBoxLayout()
        self.optimize = QPushButton('Optimize');self.optimize.clicked.connect(controller.begin)
        self.button = QPushButton('Close');self.button.clicked.connect(self.close)
        buttons.addWidget(self.optimize);buttons.addWidget(self.button);layout.addLayout(buttons)

    def closeEvent(self,event):
        if self.controller.running:
            self.controller.cancel()
            self.status.setText('Stopping… A committed storage change will remain active; the backup is retained.')
            self.button.setEnabled(False)
            event.ignore()
        else:
            event.accept()

    def reject(self):
        self.close()


class LibraryStorageMigration(QObject):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner = owner
        self.running = False
        self.dialog = None
        self.result = None
        self.cancel_event = Event()

    def start(self):
        if self.dialog is None or not self.dialog.isVisible() and not self.running:
            self.dialog = _MigrationDialog(self)
        self.dialog.show();self.dialog.raise_();self.dialog.activateWindow()

    def cancel(self):
        self.cancel_event.set()

    def begin(self):
        if self.running:
            return False
        try:
            busy = _busy(self.owner)
        except Exception as error:
            self.dialog.status.setText('Cannot check background activity: '+str(error))
            return False
        if busy:
            self.dialog.status.setText('Wait for searches, downloads and profile preparation to finish, then try again.')
            return False
        self.cancel_event.clear();self.result = None
        self.running = True;self.owner._library_storage_migration_active = True
        self.dialog.optimize.setEnabled(False)
        self.dialog.button.setText('Cancel')
        self.dialog.progress.setRange(0,0)
        panel = getattr(self.owner,'database_panel',None)
        if panel is not None:panel.setEnabled(False)
        cache = self.owner.local_phase_cache
        backup = cache.root/'storage_backups'/('index-before-'+str(cache.storage_version)+'-'+uuid4().hex[:12]+'.sqlite')
        handle = BackgroundTaskHandle(
            lambda emit:migrate_library_storage(cache.index_path,backup,
                progress=emit,cancelled=self.cancel_event.is_set),self.owner,
            accepts_progress=True,operation_name='database.storage.migration')
        self.owner._background_tasks.add(handle);self.owner._background_task_threads.add(handle)

        def progress(label,value,maximum):
            self.dialog.status.setText(label)
            self.dialog.progress.setRange(0,maximum);self.dialog.progress.setValue(value)

        def finished(result):
            self.result = result
            if result.activated or result.already_current:
                # Keep the shared cache/service objects and valid scientific
                # results; only persistence policy and text reuse have changed.
                cache.storage_version = CURRENT_STORAGE_VERSION
                cache.compact_storage = True
                cache._peak_text_cache.clear()
            if result.already_current:
                text = ('Storage was already optimized. Unused space compacted.' if result.compacted else
                        'The library is already using optimized storage. No backup or recalculation was needed.')
                if result.compacted and result.after_bytes is not None:
                    text += f' Database: {result.before_bytes/1024**2:.1f} → {result.after_bytes/1024**2:.1f} MiB.'
                self.dialog.backup.setText('No new backup created.')
            else:
                sizes = (f'Database: {result.before_bytes/1024**2:.1f} → {result.after_bytes/1024**2:.1f} MiB. '
                         if result.after_bytes is not None else '')
                text = 'Optimized storage is active. '+sizes+'Calculations were preserved.'
                self.dialog.backup.setText(f'Original backup retained ({result.before_bytes/1024**2:.1f} MiB): '+str(result.backup_path))
            if result.notice:text+='\n'+result.notice
            self.dialog.status.setText(text)
            self.dialog.progress.setRange(0,1);self.dialog.progress.setValue(1)
            self.owner._background_tasks.discard(handle)

        def failed(message,details):
            text = ('Cancelled before activation. The original library is unchanged.' if self.cancel_event.is_set()
                    else 'Optimization failed before activation. Original library retained.\n'+(message or details))
            self.dialog.status.setText(text)
            self.dialog.progress.setRange(0,1);self.dialog.progress.setValue(0)
            self.owner._background_tasks.discard(handle)

        def stopped():
            self.owner._background_task_threads.discard(handle)
            self.running = False;self.owner._library_storage_migration_active = False
            self.dialog.button.setText('Close');self.dialog.button.setEnabled(True)
            retry = self.result is not None and not self.result.compacted and bool(self.result.notice)
            self.dialog.optimize.setEnabled(self.result is None or retry)
            self.dialog.optimize.setText('Retry compaction' if retry else 'Optimize')
            if panel is not None:panel.setEnabled(True)
            if getattr(self.owner,'_library_migration_close_pending',False):
                self.owner._library_migration_close_pending = False
                self.dialog.close()
                self.owner.close()
            elif getattr(self.owner,'_preparation_close_confirmed',False):
                self.owner._finish_preparation_close()

        handle.progress.connect(progress);handle.finished.connect(finished)
        handle.failed.connect(failed);handle.stopped.connect(stopped)
        handle.start()
        return True
