"""Explicit cancellable reference preparation, separate from numeric ranking."""
from concurrent.futures import CancelledError
from contextlib import closing
from pathlib import Path
from xrd_finder.services.local_phase_cache import LocalPhaseCache, DERIVED_CACHE_VERSION, REINDEXABLE_CACHE_VERSIONS


def prepare_reference_rows(cache, rows, *, wavelength, progress=None, cancelled=lambda: False):
    structural_sources = {'COD', 'USER', 'MP', 'CCDC', 'AFLOW', 'OQMD'}
    keys = list(dict.fromkeys((str(row[0]).upper(), str(row[1])) for row in rows
        if len(row) > 1 and str(row[0]).upper() in structural_sources and row[1]))
    coverage = cache.reference_range_coverage(keys, wavelength=wavelength, cancelled=cancelled)
    pending = [key for key in keys if not coverage[key]]
    # Catalog-only cards have nothing to calculate locally. Keep them visible
    # as unavailable without spawning interpreters or hydrating their JSON.
    states = cache.preparation_states(pending)
    local = [key for key in pending if key in states and states[key].cif_path
             and Path(states[key].cif_path).is_file()]
    local_keys = set(local)
    unavailable = [key for key in pending if key not in local_keys]
    pending = local
    # Spawned interpreters avoid blocking the GUI on native parser/GIL work.
    # Small fixtures and frozen binaries retain the same sequential contract.
    import sys
    if len(pending) >= 8 and not getattr(sys, 'frozen', False):
        return unavailable + _prepare_parallel(cache, pending, wavelength, progress, cancelled)
    for index, (source, entry_id) in enumerate(pending):
        if cancelled():
            raise CancelledError('Reference preparation cancelled')
        if progress:
            progress('Preparing validated reference lines', index+1, len(pending))
        if not cache.ensure_reference_range(source, entry_id, wavelength=wavelength):
            unavailable.append((source, entry_id))
    return unavailable


def _prepare_parallel(cache, keys, wavelength, progress, cancelled):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tempfile
    import time
    # Each child owns its SQLite connection; transactions remain atomic.
    count = min(4, max(1, (os.cpu_count() or 2)//2), len(keys))
    queue = list(keys)
    running = []
    unavailable = []
    completed = 0
    environment = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[2])
    environment['PYTHONPATH'] = package_root + os.pathsep + environment.get('PYTHONPATH', '')
    # Redirect protocols to owned temporary files; no pipe can fill while the
    # parent polls cancellation, and diagnostics remain available on errors.
    with tempfile.TemporaryDirectory(prefix='xrd-reference-workers-') as folder:
        try:
            while queue or running:
                if cancelled():
                    raise CancelledError('Reference preparation cancelled')
                while queue and len(running) < count:
                    # Small batches keep progress and cancellation granular.
                    chunk = queue[:8]; del queue[:8]
                    request = {'root':str(cache.root), 'keys':chunk, 'wavelength':float(wavelength)}
                    label = str(completed) + '-' + str(len(queue))
                    input_path = Path(folder)/(label+'.input')
                    output_path = Path(folder)/(label+'.output')
                    error_path = Path(folder)/(label+'.error')
                    input_path.write_text(json.dumps(request))
                    with input_path.open('rb') as source, output_path.open('wb') as output, error_path.open('wb') as errors:
                        process = subprocess.Popen([sys.executable, '-m',
                            'xrd_finder.services.reference_preparation_worker'], stdin=source,
                            stdout=output, stderr=errors, env=environment, cwd=package_root)
                    running.append((process,chunk,output_path,error_path))
                for item in list(running):
                    process,chunk,output_path,error_path = item
                    if process.poll() is None:
                        continue
                    running.remove(item)
                    if process.returncode:
                        raise RuntimeError('Reference preparation failed: '+error_path.read_text()[-2000:])
                    results = json.loads(output_path.read_text())
                    unavailable.extend((source,entry) for source,entry,ready in results if not ready)
                    completed += len(chunk)
                    if progress:
                        progress('Preparing validated reference lines', completed, len(keys))
                time.sleep(.01)
        finally:
            for process,*_ in running:
                if process.poll() is None:
                    process.terminate()
            for process,*_ in running:
                try:
                    process.wait(timeout=3.)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
    return unavailable


def prepare_gain_references(inputs, *, progress=None, cancelled=lambda: False):
    cache = LocalPhaseCache(inputs.cache_root)
    # Existing geometry determines the SQL population. Metadata-only cards are
    # not silently promoted, and accepted/visible explicit cards are included.
    sources = tuple(inputs.local_sources)
    rows = [list(r[:2]) for r in inputs.rows[:120]]
    rows.extend([c.get('Source',''), c.get('Entry','')] for c in inputs.candidates)
    if sources:
        marks = ','.join('?' for _ in sources)
        with closing(cache._connect()) as connection:
            rows.extend([r['source'], r['entry_id']] for r in connection.execute(
                f"select source,entry_id from phases where source in ({marks}) and peaks_json != ''",
                sources))
    return prepare_reference_rows(cache, rows,
        wavelength=inputs.instrument_profile.radiation.components[0].wavelength_angstrom,
        progress=progress, cancelled=cancelled)
