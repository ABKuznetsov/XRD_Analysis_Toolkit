"""Optional update notification after first paint, independent of GUI workers."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import sys
from threading import Event, Thread
from urllib.parse import urlparse

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, QTimer, Signal, Slot, Qt, QEvent, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from xrd_finder import __version__
from xrd_finder.services.security_mode import offline_mode_enabled
from xrd_finder.services.cache_paths import default_data_root
from xrd_finder.services.update_installer import (
    DownloadCancelled, InstallerAsset, download_installer, installer_from_manifest,
    spawn_installer_after_exit,
)


RELEASES_URL = 'https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases'
MANIFEST_ROOT = 'https://raw.githubusercontent.com/ABKuznetsov/XRD_Analysis_Toolkit/main/launcher/updates'


@dataclass(frozen=True)
class UpdateResult:
    version: str = ''
    url: str = RELEASES_URL
    error: str = ''
    installer: InstallerAsset | None = None


def parse_update(payload: dict, *, platform: str = sys.platform) -> UpdateResult:
    info = payload.get('apps', {}).get('xrd_finder', payload)
    key = 'macos' if platform == 'darwin' else 'windows' if platform == 'win32' else 'linux'
    version = str(info.get('platform_versions', {}).get(key) or info.get('version') or '')
    Version(version)  # Malformed responses must never advertise an update.
    url = str(info.get('release_page_url') or info.get('release_notes_url') or RELEASES_URL)
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or not parsed.path.startswith('/ABKuznetsov/XRD_Analysis_Toolkit/releases')):
        url = RELEASES_URL
    return UpdateResult(version, url, installer=installer_from_manifest(info, platform))


def fetch_update() -> UpdateResult:
    # Import SSL/network libraries only in the I/O worker, never on first paint.
    import ssl
    from urllib.request import Request, urlopen
    import certifi

    if offline_mode_enabled():
        return UpdateResult(error='Offline mode is enabled.')
    key = 'macos' if sys.platform == 'darwin' else 'windows' if sys.platform == 'win32' else 'linux'
    request = Request(f'{MANIFEST_ROOT}/xrd_finder_{key}.json',
                      headers={'User-Agent': f'XRD-Phase-Finder/{__version__}'})
    with urlopen(request, timeout=4, context=ssl.create_default_context(cafile=certifi.where())) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Update manifest is too large.')
    return parse_update(json.loads(data.decode('utf-8-sig')))


class UpdateController(QObject):
    completed = Signal(object)
    download_progress = Signal(object)
    download_completed = Signal(object)

    def __init__(self, window, *, settings=None):
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.busy = False
        self.closed = False
        self.manual = False
        self.result = None
        self.automatic_checked = False
        self.downloading = False
        self.downloaded_path = None
        self.downloaded_asset = None
        self.install_pending = False
        self._download_cancel = Event()
        self.offer = None
        self.progress_dialog = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.check)
        self.completed.connect(self._finished)
        self.download_progress.connect(self._progress)
        self.download_completed.connect(self._download_finished)
        label = getattr(window, 'background_status_label', None)
        if label is not None:
            label.linkActivated.connect(self._update_link)
        window.finished.connect(self.shutdown)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        # Finder implements closeEvent itself, so an accepted close need not
        # emit QDialog.finished. A non-spontaneous hide follows a closed window;
        # spontaneous OS events (e.g. minimising) must not disable updates.
        if (watched is getattr(self, 'window', None) and event.type() == QEvent.Type.Hide
                and not event.spontaneous()):
            self.shutdown()
        return False

    def schedule(self, *, delay_ms=1000):
        self.timer.start(delay_ms)

    def shutdown(self, *_):
        if getattr(self, 'closed', True):
            return
        self.closed = True
        self.timer.stop()
        self._download_cancel.set()
        self.window.removeEventFilter(self)

    def check(self, *, manual=False):
        if self.closed:
            return
        if self.downloading:
            if self.progress_dialog is not None:self.progress_dialog.show()
            return
        if manual and self.downloaded_path is not None and self.result is not None:
            self._show_offer(self.result)
            return
        if offline_mode_enabled():
            if manual:
                QMessageBox.information(self.window, 'Updates', 'Offline mode is enabled. Update checks are disabled.')
            return
        if self.busy:
            self.manual = self.manual or manual
            return
        if not manual and self.automatic_checked:
            return
        self.automatic_checked = True
        self.busy = True
        self.manual = manual
        # Do not use the window's QThread pool: its close path drains all owned
        # scientific jobs. A network request must not delay a quick open/close.
        def work():
            try:
                result = fetch_update()
            except Exception as exc:
                result = UpdateResult(error=str(exc) or type(exc).__name__)
            try:
                self.completed.emit(result)
            except RuntimeError:
                pass  # Window/Qt object was destroyed while the daemon waited.
        Thread(target=work, name='finder-update-check', daemon=True).start()

    @Slot(object)
    def _finished(self, result):
        self.busy = False
        if self.closed or offline_mode_enabled():
            return
        self.result = result
        try:
            available = not result.error and Version(result.version) > Version(__version__)
        except InvalidVersion:
            available = False
        if available:
            action = getattr(self.window, 'check_updates_action', None)
            if action is not None:
                action.setText(f'Update available: {result.version}...')
            label = getattr(self.window, 'background_status_label', None)
            if label is not None:
                label.setTextInteractionFlags(label.textInteractionFlags() | Qt.TextInteractionFlag.LinksAccessibleByMouse)
                label.setText(f'<a href="finder-update">Finder {escape(result.version)} is available — download and install</a>')
                label.setOpenExternalLinks(False)
            self._show_offer(result)
        elif self.manual:
            message = (f'Could not check for updates: {escape(result.error)}' if result.error
                       else f'Finder {__version__} is up to date.')
            QMessageBox.information(self.window, 'Updates', message)

    def _update_link(self, url):
        if url == 'finder-update' and self.result is not None:
            self._show_offer(self.result)
        else:
            QDesktopServices.openUrl(QUrl(url))

    def _show_offer(self, result):
        if self.closed:return
        if self.offer is not None:
            self.offer.raise_();self.offer.activateWindow();return
        message = self.offer = QMessageBox(self.window)
        message.setWindowTitle('Updates')
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(f'Finder {result.version} is available.')
        ready = self.downloaded_path is not None and self.downloaded_asset == result.installer
        if result.installer is not None:
            message.setInformativeText('The installer will open after Finder closes. You can save your project before continuing.')
            proceed = message.addButton('Install update' if ready else 'Download and install', QMessageBox.ButtonRole.AcceptRole)
        else:
            message.setInformativeText('An automatic installer is not available for this platform.')
            proceed = message.addButton('View release', QMessageBox.ButtonRole.AcceptRole)
        message.addButton('Later', QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(proceed)
        message.setWindowModality(Qt.WindowModality.WindowModal)
        message.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        def chosen(_):
            self.offer = None
            if self.closed or message.clickedButton() is not proceed:return
            if result.installer is None:QDesktopServices.openUrl(QUrl(result.url))
            elif ready:self.install_downloaded()
            else:self._download(result.installer)
        message.finished.connect(chosen)
        message.open()

    def _download(self, asset):
        if self.closed or self.downloading:return
        if offline_mode_enabled():
            QMessageBox.information(self.window, 'Updates', 'Offline mode is enabled. Download was not started.')
            return
        self.downloading = True
        self.downloaded_asset = asset
        self._download_cancel = cancel = Event()
        dialog = self.progress_dialog = QProgressDialog('Downloading Finder update…', 'Cancel', 0, 1000, self.window)
        dialog.setWindowTitle('Updates');dialog.setMinimumDuration(0)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False);dialog.setAutoReset(False)
        dialog.canceled.connect(cancel.set);dialog.show()
        directory = default_data_root().parent/'updates'
        def work():
            def progress(done, total):
                try:self.download_progress.emit((done,total))
                except RuntimeError:cancel.set()
            try:
                path = download_installer(asset, directory, progress=progress, cancelled=cancel.is_set)
                result = (path, '', cancel.is_set())
            except DownloadCancelled:result = (None, '', True)
            except Exception as error:result = (None, str(error) or type(error).__name__, False)
            try:self.download_completed.emit(result)
            except RuntimeError:pass
        Thread(target=work, name='finder-update-download', daemon=True).start()

    @Slot(object)
    def _progress(self, progress):
        if self.closed or self.progress_dialog is None:return
        done,total = progress
        dialog = self.progress_dialog
        dialog.setRange(0, 1000 if total else 0)
        if total:dialog.setValue(min(1000, int(1000*done/total)))
        dialog.setLabelText(f'Downloading Finder update: {done/1048576:.1f}'
                            +(f' / {total/1048576:.1f} MB' if total else ' MB'))

    @Slot(object)
    def _download_finished(self, result):
        self.downloading = False
        if self.closed:return
        path,error,cancelled = result
        cancelled = cancelled or self._download_cancel.is_set()
        if self.progress_dialog is not None:
            self.progress_dialog.close();self.progress_dialog.deleteLater();self.progress_dialog = None
        if cancelled:return
        if error:
            QMessageBox.warning(self.window, 'Update download failed', error);return
        self.downloaded_path = Path(path)
        self.install_downloaded()

    def install_downloaded(self):
        if self.closed or self.downloaded_path is None:return
        self.install_pending = True
        self.window.close()  # Existing save/cancel and scientific-job drain path.

    def cancel_installation(self):
        self.install_pending = False

    def prepare_installation_on_close(self):
        if not self.install_pending:return True
        try:
            self._installer_helper = spawn_installer_after_exit(self.downloaded_path, self.downloaded_asset.sha256)
        except Exception as error:
            self.install_pending = False
            QMessageBox.warning(self.window, 'Could not start update installer', str(error))
            return False
        self.install_pending = False
        return True


def update_controller(window) -> UpdateController:
    controller = getattr(window, '_update_controller', None)
    if controller is None:
        controller = UpdateController(window)
        window._update_controller = controller
    return controller


def schedule_update_check(window):
    update_controller(window).schedule()
