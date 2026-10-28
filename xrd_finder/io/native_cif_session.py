"""Share a native read only within one preparation transaction/thread.

The CrIStMa result is consumed without mutation. Nothing survives the scope:
changed files and subsequent requests always get a fresh parse.
"""
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import cristma

_reads = ContextVar('xrd_native_cif_reads', default=None)


def read_native_cif(path):
    cache = _reads.get()
    if cache is None:
        return cristma.read(path, format='cif')
    key = str(Path(path).resolve())
    if key not in cache:
        cache[key] = cristma.read(path, format='cif')
    return cache[key]


def native_cif_session(function):
    @wraps(function)
    def run(*args, **kwargs):
        if _reads.get() is not None:
            return function(*args, **kwargs)
        token = _reads.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _reads.reset(token)
    return run
