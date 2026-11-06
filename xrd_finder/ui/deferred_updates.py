"""Optional update notification after first paint, independent of GUI workers."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import sys
from threading import Thread
import time
from urllib.parse import urlparse

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, QTimer, Signal, Slot, Qt, QEvent
from PySide6.QtWidgets import QMessageBox

from xrd_finder import __version__
from xrd_finder.services.security_mode import offline_mode_enabled
from xrd_finder.ui.app_settings import app_settings


RELEASES_URL = 'https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases'
MANIFEST_ROOT = 'https://raw.githubusercontent.com/ABKuznetsov/XRD_Analysis_Toolkit/main/launcher/updates'


@dataclass(frozen=True)
class UpdateResult:
    version: str = ''
    url: str = RELEASES_URL
    error: str = ''


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
    return UpdateResult(version, url)


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

    def __init__(self, window, *, settings=None):
        super().__init__(window)
        self.window = window
        self.settings = settings if settings is not None else app_settings()
        self.setting_key = f'updates/last_attempt/{sys.platform}/{__version__}'
        self.busy = False
        self.closed = False
        self.manual = False
        self.result = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.check)
        self.completed.connect(self._finished)
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

    def schedule(self, *, delay_ms=5000):
        self.timer.start(delay_ms)

    def shutdown(self, *_):
        if getattr(self, 'closed', True):
            return
        self.closed = True
        self.timer.stop()
        self.window.removeEventFilter(self)

    def check(self, *, manual=False):
        if self.closed:
            return
        if offline_mode_enabled():
            if manual:
                QMessageBox.information(self.window, 'Updates', 'Offline mode is enabled. Update checks are disabled.')
            return
        if self.busy:
            self.manual = self.manual or manual
            return
        try:
            last = float(self.settings.value(self.setting_key, 0))
        except (TypeError, ValueError):
            last = 0
        if not manual and 0 <= time.time() - last < 86400:
            return
        self.settings.setValue(self.setting_key, time.time())
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
                label.setText(f'<a href="{escape(result.url, quote=True)}">Finder {escape(result.version)} is available — view release</a>')
                label.setOpenExternalLinks(True)
        if self.manual:
            message = (f'Finder {result.version} is available. '
                       f'<a href="{escape(result.url, quote=True)}">View release and installers</a>.' if available
                       else f'Could not check for updates: {escape(result.error)}' if result.error
                       else f'Finder {__version__} is up to date.')
            QMessageBox.information(self.window, 'Updates', message)


def update_controller(window) -> UpdateController:
    controller = getattr(window, '_update_controller', None)
    if controller is None:
        controller = UpdateController(window)
        window._update_controller = controller
    return controller


def schedule_update_check(window):
    update_controller(window).schedule()
