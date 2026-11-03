"""Shared atomic CIF files and per-file locks for COD download channels."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import threading
from weakref import WeakValueDictionary

_guard = threading.Lock()
_locks = WeakValueDictionary()


@contextmanager
def lock_cifs(paths, *, check_cancelled=lambda: None):
    keys = sorted({os.path.normcase(os.path.abspath(path)) for path in paths})
    with _guard:
        locks = []
        for key in keys:
            lock = _locks.get(key)
            if lock is None:
                lock = threading.RLock()
                _locks[key] = lock
            locks.append(lock)
    acquired = []
    try:
        for lock in locks:
            while not lock.acquire(timeout=.1):
                check_cancelled()
            acquired.append(lock)
            check_cancelled()
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()


def atomic_save_cif(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.part', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
