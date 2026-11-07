"""Prepare downloaded cards outside the GUI with the existing native worker pool."""
from xrd_finder.services.cod_inorganic_worker import prepare_paths
from contextlib import closing
from pathlib import Path
from xrd_finder.services.cod_inorganic_library import current_preparation


def prepare_candidate_cif_batch(cache_root, requests, ready, cancelled):
    jobs = [(str(index), str(path), dict(options)) for index, (options, path) in enumerate(requests)]
    prepare_paths(cache_root, jobs, ready=ready, cancelled=cancelled)


def prepare_saved_cifs(cache, *, progress=None, force=False, cancelled=lambda: False):
    """Update saved CIFs without serial native calculations in the parent."""
    from concurrent.futures import CancelledError
    def check():
        if cancelled():
            raise CancelledError('Saved CIF preparation cancelled')
    with closing(cache._connect()) as connection:
        rows = connection.execute("select source,entry_id,cif_path from phases where cif_path!=''").fetchall()
    paths = {(row['source'],row['entry_id']):Path(row['cif_path']) for row in rows
             if Path(row['cif_path']).is_file()}
    registered = set(paths.values())
    for source, directory in (('COD',cache.cif_dir),('USER',cache.root/'user_cif'),
                               ('MP',cache.root/'materials_project_cif'),('AFLOW',cache.root/'aflow_cif'),
                               ('OQMD',cache.root/'oqmd_cif')):
        for path in directory.glob('*.cif'):
            check()
            if path not in registered:
                paths.setdefault((source,path.stem),path)
    keys = list(paths)
    jobs = []
    successful = 0
    for offset in range(0,len(keys),100):
        check()
        batch = keys[offset:offset+100]
        entries = cache.iic_entries(batch) if not force else {}
        covered = cache.reference_range_coverage(batch,cancelled=cancelled) if not force else {}
        for key in batch:
            if not force and current_preparation(paths[key],entries.get(key),
                    covered=covered.get(key,False),calculated_iic=cache.calculated_iic):
                successful += 1
            else:
                jobs.append((dict(source=key[0],entry_id=key[1]),paths[key]))
        if progress:
            progress('Checking saved CIF records',min(offset+100,len(keys)),len(keys))
    finished = len(keys)-len(jobs)
    def ready(index, success, error):
        nonlocal successful,finished
        successful += bool(success)
        finished += 1
        if progress:
            progress('Preparing saved CIF records',finished,len(keys))
    prepare_candidate_cif_batch(cache.root,jobs,ready,cancelled)
    check()
    return successful
