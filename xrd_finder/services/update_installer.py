"""Verified update downloads and a small, detached post-exit installer helper."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlparse

REPOSITORY_PATH = '/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/'
MAX_INSTALLER_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class InstallerAsset:
    url: str
    sha256: str
    size_bytes: int = 0


class DownloadCancelled(Exception):
    pass


def trusted_download_url(url, *, initial=False):
    try:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if initial:
            return parsed.hostname == 'github.com' and parsed.path.startswith(REPOSITORY_PATH)
        return parsed.hostname == 'github.com' or parsed.hostname in (
            'release-assets.githubusercontent.com', 'objects.githubusercontent.com',
            'github-releases.githubusercontent.com')
    except (ValueError, TypeError):
        return False


def installer_from_manifest(info, platform):
    key = 'macos' if platform == 'darwin' else 'windows' if platform == 'win32' else 'linux'
    suffix = '.pkg' if key == 'macos' else '.exe' if key == 'windows' else '.deb'
    assets = info.get('assets', [])
    candidates = [a for a in assets if isinstance(a, dict) and a.get('platform') == key] if isinstance(assets, list) else []
    prefix = '' if key == 'windows' else key+'_'
    candidates.append(dict(url=info.get(prefix+'installer_url'), sha256=info.get(prefix+'installer_sha256'),
                           size_bytes=info.get(prefix+'installer_size_bytes', 0)))
    for item in candidates:
        url = str(item.get('url') or '')
        digest = str(item.get('sha256') or '').lower()
        filename = unquote(urlparse(url).path.rsplit('/', 1)[-1])
        try:
            size = int(item.get('size_bytes') or 0)
        except (ValueError, TypeError):
            continue
        if (trusted_download_url(url, initial=True) and re.fullmatch(r'[0-9a-f]{64}', digest)
                and re.fullmatch(r'[A-Za-z0-9_.-]+', filename) and filename.lower().endswith(suffix)
                and 0 <= size <= MAX_INSTALLER_BYTES and 'secure' not in filename.lower()):
            return InstallerAsset(url, digest, size)
    return None


def verify_installer(path, sha256):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', sha256):
        raise ValueError('The update checksum is missing or invalid.')
    path = Path(path)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != sha256.lower():
        raise ValueError('Downloaded installer checksum does not match. Please retry the update.')


def download_installer(asset, directory, *, progress=lambda done,total:None, cancelled=lambda:False, opener=None):
    if not trusted_download_url(asset.url, initial=True):
        raise ValueError('Invalid update download address.')
    filename = unquote(urlparse(asset.url).path.rsplit('/', 1)[-1])
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', filename):
        raise ValueError('Invalid installer filename.')
    if not 0 <= asset.size_bytes <= MAX_INSTALLER_BYTES:
        raise ValueError('The update installer is too large.')
    from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
    if opener is None:
        import ssl
        import certifi
        class Redirects(HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                if not trusted_download_url(newurl):
                    raise ValueError('Untrusted update redirect.')
                return super().redirect_request(request, fp, code, msg, headers, newurl)
        client = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())), Redirects())
        opener = lambda request: client.open(request, timeout=10)
    directory = Path(directory);directory.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='finder-update-', dir=directory))
    target = folder/filename;partial = folder/(filename+'.part')
    try:
        if cancelled():raise DownloadCancelled()
        request = Request(asset.url, headers={'User-Agent':'XRD-Phase-Finder-Updater','Accept-Encoding':'identity'})
        with opener(request) as response, partial.open('wb') as stream:
            if not trusted_download_url(response.geturl()):raise ValueError('Untrusted update redirect.')
            total = asset.size_bytes or int(response.headers.get('Content-Length') or 0)
            if not 0 <= total <= MAX_INSTALLER_BYTES:raise ValueError('The update installer is too large.')
            received = 0
            while True:
                if cancelled():raise DownloadCancelled()
                chunk = response.read(64*1024)
                if not chunk:break
                received += len(chunk)
                if received > MAX_INSTALLER_BYTES or (total and received > total):
                    raise ValueError('Unexpected update installer size.')
                stream.write(chunk);progress(received, total)
        if cancelled():raise DownloadCancelled()
        if total and received != total:raise ValueError('The update download is incomplete. Please retry.')
        verify_installer(partial, asset.sha256)
        for attempt in range(6):
            try:
                partial.replace(target);break
            except PermissionError:
                if attempt == 5:raise
                if cancelled():raise DownloadCancelled()
                time.sleep(.05*(attempt+1))
        return target
    except BaseException:
        partial.unlink(missing_ok=True);target.unlink(missing_ok=True)
        folder.rmdir()
        raise


def wait_for_parent_exit(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:return  # Finder has already exited.
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel.WaitForSingleObject(handle, 300000) != 0:
                raise TimeoutError('Finder is still running. Close Finder before installing the update.')
        finally:kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            try:os.kill(pid, 0)
            except ProcessLookupError:return
            time.sleep(.1)
        raise TimeoutError('Finder is still running. Close Finder before installing the update.')


def open_installer(path):
    if os.name == 'nt':os.startfile(str(path))
    else:subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])


def install_after_exit(path, sha256, parent_pid, *, waiter=wait_for_parent_exit, launcher=open_installer):
    waiter(parent_pid)
    verify_installer(path, sha256)
    launcher(Path(path))


def spawn_installer_after_exit(path, sha256):
    path = Path(path).resolve();verify_installer(path, sha256)
    command = [sys.executable, str(Path(__file__).resolve()), '--parent-pid', str(os.getpid()),
               '--installer', str(path), '--sha256', sha256]
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:options['start_new_session'] = True
    return subprocess.Popen(command, **options)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    try:install_after_exit(args.installer, args.sha256, args.parent_pid)
    except Exception as error:
        (args.installer.parent/'installation-error.txt').write_text(str(error), encoding='utf-8')
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'XRD Phase Finder update', 0x10)
        raise SystemExit(1)
