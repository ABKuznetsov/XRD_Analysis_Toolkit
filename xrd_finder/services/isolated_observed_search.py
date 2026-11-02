"""Own first-search numeric preparation outside the GUI interpreter."""
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import time


def run_observed_search_isolated(inputs, *, progress=None, cancelled=lambda:False):
    from xrd_finder.services.observed_search_preparation import ObservedSearchCancelled, prepare_observed_search
    from xrd_finder.services.runtime_diagnostics import diagnostic_logger
    if cancelled():
        raise ObservedSearchCancelled()
    if getattr(sys,'frozen',False):
        return prepare_observed_search(inputs,progress=progress,cancelled=cancelled)
    started=time.monotonic()
    package_root=str(Path(__file__).resolve().parents[2])
    environment=os.environ.copy()
    environment['PYTHONPATH']=package_root+os.pathsep+environment.get('PYTHONPATH','')
    environment['PYTHONDONTWRITEBYTECODE']='1'
    with tempfile.TemporaryDirectory(prefix='xrd-observed-search-') as folder:
        root=Path(folder)
        (root/'input.pickle').write_bytes(pickle.dumps(inputs))
        process=None
        previous=None
        def report():
            nonlocal previous
            try:update=json.loads((root/'progress.json').read_text())
            except (OSError,ValueError):return
            if update != previous:
                previous=update
                if progress:progress(*update)
        try:
            if cancelled():raise ObservedSearchCancelled()
            with (root/'stdout').open('wb') as output,(root/'stderr').open('wb') as errors:
                process=subprocess.Popen([sys.executable,'-m',
                    'xrd_finder.services.isolated_observed_search',str(root)],
                    cwd=package_root,env=environment,stdout=output,stderr=errors)
            while process.poll() is None:
                if cancelled():raise ObservedSearchCancelled()
                report()
                time.sleep(.015)
            if cancelled():raise ObservedSearchCancelled()
            if process.returncode:
                raise RuntimeError('Observed peak worker failed: '+(root/'stderr').read_text()[-2500:])
            report()
            result=pickle.loads((root/'result.pickle').read_bytes())
            result.timings['process_seconds']=time.monotonic()-started
            diagnostic_logger().info(
                'event=observed_preparation points=%s peaks=%s background_ms=%.1f peaks_ms=%.1f total_ms=%.1f process_ms=%.1f',
                len(result.x),len(result.records),result.timings['background_seconds']*1000.,
                result.timings['peaks_seconds']*1000.,result.timings['total_seconds']*1000.,
                result.timings['process_seconds']*1000.)
            return result
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=.1)


def main(root):
    from xrd_finder.services.observed_search_preparation import prepare_observed_search
    root=Path(root)
    inputs=pickle.loads((root/'input.pickle').read_bytes())
    def progress(*values):
        temporary=root/'progress.pending'
        temporary.write_text(json.dumps(values))
        temporary.replace(root/'progress.json')
    result=prepare_observed_search(inputs,progress=progress)
    (root/'result.pickle').write_bytes(pickle.dumps(result))


if __name__=='__main__':
    main(sys.argv[1])
