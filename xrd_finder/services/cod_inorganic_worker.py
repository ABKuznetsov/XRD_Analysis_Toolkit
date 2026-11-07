"""Bounded persistent native interpreters for explicit bulk library preparation."""
from collections import deque
from contextlib import contextmanager
import warnings
import json
import os
from queue import Empty
from pathlib import Path
import subprocess
import sys
import tempfile
import time


@contextmanager
def _worker_directory():
    temporary = tempfile.TemporaryDirectory(prefix='xrd-cod-native-workers-')
    try:
        yield temporary.name
    finally:
        # Windows can briefly retain redirected-file handles after wait().
        # Cleanup must not replace a successful calculation or cancellation.
        for attempt in range(20):
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if attempt == 19:
                    warnings.warn('Could not remove COD worker temporary logs: '+temporary.name,
                                  RuntimeWarning)
                else:
                    time.sleep(.05)


class _JobSource:
    def __init__(self, paths, source_done):
        self.streaming = source_done is not None
        self.pending = paths if self.streaming else deque(paths)
        self.done = source_done if self.streaming else lambda: True

    def empty(self):
        return self.pending.empty() if self.streaming else not self.pending

    def finished(self):
        return self.done() and self.empty()

    def take(self):
        if self.streaming:
            try:
                return self.pending.get_nowait()
            except Empty:
                return None
        return self.pending.popleft() if self.pending else None


def prepare_paths(cache_root, paths, *, workers=None, ready=None, cancelled=lambda: False,
                  source_done=None,source='COD'):
    from xrd_finder.services.cod_inorganic_library import LibraryCancelled
    source_name=source
    source = _JobSource(paths, source_done)
    while source.empty() and not source.finished():
        if cancelled():
            raise LibraryCancelled('COD preparation cancelled')
        time.sleep(.02)
    if cancelled():
        raise LibraryCancelled('COD preparation cancelled')
    if source.finished():
        return
    count = max(1,min(4,int(workers or max(1,(os.cpu_count() or 2)//2))))
    if not source.streaming:
        count = min(count,len(source.pending))
    package_root = str(Path(__file__).resolve().parents[2])
    environment = os.environ.copy()
    environment['PYTHONPATH'] = package_root+os.pathsep+environment.get('PYTHONPATH','')
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    environment['OMP_NUM_THREADS'] = '1'
    environment['OPENBLAS_NUM_THREADS'] = '1'
    running = []
    with _worker_directory() as folder:
        try:
            for index in range(count):
                output_path = Path(folder)/(str(index)+'.jsonl')
                error_path = Path(folder)/(str(index)+'.stderr')
                with output_path.open('wb') as output, error_path.open('wb') as errors:
                    process = subprocess.Popen([sys.executable,'-u','-m',
                        'xrd_finder.services.cod_inorganic_worker','--worker',str(cache_root)],
                        stdin=subprocess.PIPE,stdout=output,stderr=errors,cwd=package_root,
                        env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                slot = dict(process=process,reader=output_path.open('rb'),errors=error_path,current=None,source=source_name)
                running.append(slot)
                _assign(slot,source)
            while not source.finished() or any(slot['current'] is not None for slot in running):
                if cancelled():
                    raise LibraryCancelled('COD preparation cancelled')
                for slot in running:
                    if slot['current'] is None:
                        _assign(slot,source)
                        if slot['current'] is None:
                            continue
                    reader = slot['reader']
                    offset = reader.tell()
                    line = reader.readline()
                    if line and line.endswith(b'\n'):
                        result = json.loads(line)
                        if result['id'] != slot['current']:
                            raise RuntimeError('COD native worker returned an unexpected identifier')
                        if ready:
                            ready(result['id'],bool(result['ready']),str(result.get('error','')))
                        slot['current'] = None
                        _assign(slot,source)
                    elif line:
                        reader.seek(offset)
                    if slot['current'] is not None and slot['process'].poll() is not None:
                        saved = reader.tell()
                        tail = reader.readline()
                        reader.seek(saved)
                        if not tail.endswith(b'\n'):
                            details = slot['errors'].read_text(encoding='utf-8',errors='replace')[-1500:]
                            raise RuntimeError('COD native worker stopped before completing a card: '+details)
                time.sleep(.01)
        finally:
            for slot in running:
                process = slot['process']
                if process.stdin is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                if process.poll() is None:
                    if slot['current'] is not None:
                        process.terminate()
                    try:
                        process.wait(timeout=.5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2.)
                slot['reader'].close()


def _assign(slot, source):
    job = source.take()
    if job is not None:
        identifier,path = job[:2]
        options = job[2] if len(job) > 2 else {}
        slot['current'] = identifier
        request = dict(options, id=identifier, path=str(path))
        request.setdefault('source',slot['source'])
        slot['process'].stdin.write((json.dumps(request)+'\n').encode())
        slot['process'].stdin.flush()
    elif source.finished() and not slot['process'].stdin.closed:
        slot['process'].stdin.close()


def main(cache_root):
    from xrd_finder.services.local_phase_cache import LocalPhaseCache
    cache = LocalPhaseCache(cache_root)
    for line in sys.stdin:
        request = json.loads(line)
        try:
            from xrd_finder.services.cod_online_service import CodEntry
            fallback = CodEntry(**request['fallback']) if request.get('fallback') else None
            success = cache.index_cif(request['path'],source=request.get('source','COD'),
                entry_id=request.get('entry_id',request['id']), fallback=fallback,
                reference_range=tuple(request['reference_range']) if request.get('reference_range') else None)
            error = '' if success else getattr(cache,'_last_reference_preparation_error','CIF preparation failed')
        except Exception as exc:
            success,error = False,str(exc)
        print(json.dumps(dict(id=request['id'],ready=bool(success),error=error)),flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker':
        raise SystemExit('Expected --worker CACHE_ROOT')
    main(sys.argv[2])
