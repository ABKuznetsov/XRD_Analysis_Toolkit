"""Run CPU-heavy Gain in an owned process so native work cannot hold Qt's GIL."""
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import time


def run_gain_job_isolated(inputs, *, progress=None, cancelled=lambda: False):
    from concurrent.futures import CancelledError
    from xrd_finder.services.gain_calculation import GainJobResult, run_gain_job
    from xrd_finder.services.reference_preparation import prepare_gain_references
    if getattr(sys, 'frozen', False):
        return run_gain_job(inputs, progress=progress, cancelled=cancelled)
    try:
        if inputs.cache_root:
            prepare_gain_references(inputs, progress=progress, cancelled=cancelled)
    except CancelledError:
        return GainJobResult([], cancelled=True)
    if cancelled():
        return GainJobResult([], cancelled=True)
    package_root = str(Path(__file__).resolve().parents[2])
    environment = os.environ.copy()
    environment['PYTHONPATH'] = package_root + os.pathsep + environment.get('PYTHONPATH', '')
    with tempfile.TemporaryDirectory(prefix='xrd-gain-worker-') as folder:
        root = Path(folder)
        (root/'input.pickle').write_bytes(pickle.dumps(inputs))
        with (root/'stdout').open('wb') as output, (root/'stderr').open('wb') as errors:
            process = subprocess.Popen([sys.executable, '-m',
                'xrd_finder.services.isolated_gain', str(root)], stdout=output,
                stderr=errors, cwd=package_root, env=environment)
        previous = None
        try:
            while process.poll() is None:
                if cancelled():
                    return GainJobResult([], cancelled=True)
                try:
                    update = json.loads((root/'progress.json').read_text())
                except (FileNotFoundError, ValueError):
                    update = None
                if update is not None and update != previous:
                    previous = update
                    if progress:
                        progress(*update)
                time.sleep(.015)
            if process.returncode:
                raise RuntimeError('Gain worker failed: '+(root/'stderr').read_text()[-4000:])
            return pickle.loads((root/'result.pickle').read_bytes())
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3.)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()


def main(root):
    from xrd_finder.services.gain_calculation import run_gain_job
    root = Path(root)
    inputs = pickle.loads((root/'input.pickle').read_bytes())
    def progress(*values):
        temporary = root/'progress.pending'
        temporary.write_text(json.dumps(values))
        temporary.replace(root/'progress.json')
    # Parent has prepared all references and owns/cancels its preparation
    # children. This process never starts descendants of its own.
    result = run_gain_job(inputs, progress=progress, references_prepared=True)
    (root/'result.pickle').write_bytes(pickle.dumps(result))


if __name__ == '__main__':
    main(sys.argv[1])
