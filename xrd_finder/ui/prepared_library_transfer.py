"""Visible, cancellable local transfer of a fully prepared phase library."""
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QFileDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from xrd_finder.services.prepared_library_archive import export_prepared_library, import_prepared_library
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


class _TransferDialog(ScreenBoundDialog):
    def __init__(self, controller, title, path):
        super().__init__(controller.owner)
        self.controller = controller
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(620,230)
        layout = QVBoxLayout(self)
        self.path_label = QLabel(str(path));self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        self.status = QLabel('Starting…');self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar();self.progress.setRange(0,0)
        layout.addWidget(self.progress)
        self.button = QPushButton('Cancel');self.button.clicked.connect(self.close)
        layout.addWidget(self.button)

    def closeEvent(self,event):
        if self.controller.running:
            self.controller.cancel()
            self.status.setText('Stopping… Saved source data are retained.')
            self.button.setEnabled(False)
            event.ignore()
        else:
            event.accept()

    def reject(self):
        self.close()


class PreparedLibraryTransfer(QObject):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner = owner
        self.running = False
        self.cancel_event = threading.Event()
        self.dialog = None

    def cancel(self):
        self.cancel_event.set()

    def start(self,importing):
        if self.running:
            self.dialog.show();self.dialog.raise_()
            return
        title = 'Import prepared library' if importing else 'Export prepared library'
        file_filter = 'Prepared XRD library (*.xpflib)'
        if importing:
            path,_ = QFileDialog.getOpenFileName(self.owner,title,str(Path.home()),file_filter)
        else:
            path,_ = QFileDialog.getSaveFileName(self.owner,title,str(Path.home()/'Desktop/XRD_lab_library.xpflib'),file_filter)
        if not path:
            return
        self.cancel_event.clear()
        self.running = True
        self.dialog = _TransferDialog(self,title,path)
        panel = getattr(self.owner,'database_panel',None)
        if panel is not None:
            panel.setEnabled(False)
        action = import_prepared_library if importing else export_prepared_library
        handle = BackgroundTaskHandle(
            lambda emit:action(self.owner.local_phase_cache,path,progress=emit,cancelled=self.cancel_event.is_set),
            self.owner,accepts_progress=True,operation_name='database.prepared_library_transfer')
        self.owner._background_tasks.add(handle)
        self.owner._background_task_threads.add(handle)

        def progress(text,value,maximum):
            self.dialog.status.setText(text)
            self.dialog.progress.setRange(0,maximum)
            self.dialog.progress.setValue(value)

        def finished(result):
            text=(f'Finished. Cards: {result.phases:,}; prepared: {result.ready:,}; '
                  f'original CIF files: {result.files:,}.')
            if result.missing_cifs:
                text+=f' Original CIFs missing on the source computer: {result.missing_cifs:,}.'
            if importing:
                text+=' Ready calculations and search indexes were restored without CrIStMa recalculation.'
                if 'COD' in result.sources:
                    self.owner.settings.setValue('sources/cod_local',True)
                    if panel is not None:panel.set_source_checked('sources/cod_local',True)
                if 'MP' in result.sources:
                    self.owner.settings.setValue('materials_project/enabled',True)
                    if panel is not None:panel.set_materials_project_checked(True)
                self.owner._refresh_database_rows()
            self.dialog.progress.setRange(0,1);self.dialog.progress.setValue(1)
            self.dialog.status.setText(text)
            self.owner._background_tasks.discard(handle)

        def failed(message,details):
            text='Cancelled. Original data and committed library records are retained.' if self.cancel_event.is_set() else 'Transfer failed: '+(message or details)
            self.dialog.status.setText(text)
            self.dialog.progress.setRange(0,1);self.dialog.progress.setValue(0)
            self.owner._background_tasks.discard(handle)

        def stopped():
            self.owner._background_task_threads.discard(handle)
            self.running = False
            self.dialog.button.setEnabled(True);self.dialog.button.setText('Close')
            if panel is not None:panel.setEnabled(True)
            if getattr(self.owner,'_preparation_close_confirmed',False):self.owner._finish_preparation_close()

        handle.progress.connect(progress);handle.finished.connect(finished)
        handle.failed.connect(failed);handle.stopped.connect(stopped)
        self.dialog.show();self.dialog.raise_();self.dialog.activateWindow()
        handle.start()
