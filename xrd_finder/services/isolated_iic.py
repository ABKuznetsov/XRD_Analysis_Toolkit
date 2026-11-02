"""One low-priority cache-upgrade process; each completed card is committed."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path


def prepare_iic_cache_isolated(cache_root, *, keys=None, ready=None, progress=None,
                               paused=lambda:False, cancelled=lambda:False):
    from xrd_finder.services.local_phase_cache import LocalPhaseCache
    from xrd_finder.services.observed_search_preparation import ObservedSearchCancelled
    if cancelled():raise ObservedSearchCancelled()
    cache=LocalPhaseCache.read_only(cache_root)
    entries=cache.outdated_iic_entries(keys)
    if not entries:return 0
    if getattr(sys,'frozen',False):
        # Do not move this CPU work back onto the GUI interpreter in a frozen build.
        raise RuntimeError('Background I/Ic upgrade needs a Python worker runtime')
    package_root=str(Path(__file__).resolve().parents[2])
    environment=os.environ.copy()
    environment.update(PYTHONPATH=package_root+os.pathsep+environment.get('PYTHONPATH',''),
        PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',
        MKL_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
    with tempfile.TemporaryDirectory(prefix='xrd-iic-cache-') as folder:
        root=Path(folder)
        (root/'input.json').write_text(json.dumps(dict(root=str(cache_root),keys=[[e.source,e.entry_id,e.cif_path] for e in entries])))
        (root/'events.jsonl').touch()
        process=None;count=0;was_paused=None
        try:
            with (root/'stdout').open('wb') as output,(root/'stderr').open('wb') as errors:
                flags=getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0) if os.name=='nt' else 0
                process=subprocess.Popen([sys.executable,'-m','xrd_finder.services.isolated_iic',str(root)],
                    cwd=package_root,env=environment,stdout=output,stderr=errors,creationflags=flags)
            with (root/'events.jsonl').open() as events:
                while True:
                    if cancelled():raise ObservedSearchCancelled()
                    wait=bool(paused())
                    if wait!=was_paused:
                        if wait:(root/'pause').touch()
                        else:(root/'pause').unlink(missing_ok=True)
                        was_paused=wait
                    while True:
                        offset=events.tell();line=events.readline()
                        if not line.endswith('\n'):
                            events.seek(offset);break
                        source,entry=json.loads(line);count+=1
                        if ready:ready(source,entry)
                        if progress and not wait:progress('Updating cached reference data',count,len(entries))
                    if process.poll() is not None:
                        if process.returncode:raise RuntimeError('I/Ic worker failed: '+(root/'stderr').read_text()[-2000:])
                        # The event file is flushed before the child exits.
                        for line in events:
                            source,entry=json.loads(line);count+=1
                            if ready:ready(source,entry)
                        return count
                    time.sleep(.025)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=.1)


def main(root):
    from xrd_finder.services.local_phase_cache import LocalPhaseCache
    root=Path(root);request=json.loads((root/'input.json').read_text())
    if hasattr(os,'nice'):
        try:os.nice(10)
        except OSError:pass
    cache=LocalPhaseCache(request['root']);parent=os.getppid()
    with (root/'events.jsonl').open('a',buffering=1) as events:
        for source,entry,path in request['keys']:
            while (root/'pause').exists():
                if os.getppid()!=parent:return
                time.sleep(.05)
            if os.getppid()!=parent:return
            cache.update_calculated_iic(source,entry,path)
            events.write(json.dumps([source,entry])+'\n')


if __name__=='__main__':main(sys.argv[1])
