"""Local folder/ZIP preparation using the existing persistent native workers."""
from pathlib import Path, PurePosixPath
from contextlib import closing
import hashlib
import time
from zipfile import ZipFile

from xrd_finder.services.cod_cif_store import atomic_save_cif, lock_cifs
from xrd_finder.services.cod_inorganic_library import (
    LibraryCancelled, LibraryResult, MAX_CIF_BYTES, current_preparation,
)
from xrd_finder.services.cod_inorganic_worker import prepare_paths
from xrd_finder.services.cod_library_progress import LibraryProgress
from xrd_finder.services.cif_import_identity import cif_import_entries, resolve_cif_import


def _local_cif_identities(named_files, source):
    """Keep COD numbers; identify every other CIF by its own relative path.

    Hash even an unambiguous basename: adding/removing a neighbouring file must
    never reassign an existing ID. Use the full digest so suffix length cannot
    depend on other filenames either. Exact duplicate archive paths still use
    the last member. Previously stored IDs are not renamed or deleted here.
    """
    return {key:value for _name,key,value in cif_import_entries(named_files,source)}


def prepare_local_cif_library(cache, path, *, archive=False, progress=None,
                              status=None, cancelled=lambda: False, source='COD', include_member=None):
    source = str(source).upper()
    result = LibraryResult(total=0)
    paths = {}
    previous_paths = {}
    state = None
    last_publish = 0.

    def check():
        if cancelled():
            raise LibraryCancelled('Local CIF preparation cancelled')

    def publish(force=False):
        nonlocal last_publish
        if state is not None and status is not None:
            now = time.monotonic()
            if force or now - last_publish >= .2:
                status(state.snapshot())
                last_publish = now

    def report(text, value, total):
        check()
        if progress:
            progress(text, value, total)
        publish()

    try:
        check()
        report('Reading local CIF files', 0, 0)
        if archive:
            target = cache.root / ('cod_bulk_cif' if source == 'COD' else source.lower()+'_bulk_cif')
            with ZipFile(path) as archive_file:
                members = {}
                for member in archive_file.infolist():
                    check()
                    name = PurePosixPath(member.filename)
                    if member.is_dir() or name.suffix.lower() != '.cif':
                        continue
                    if include_member is not None and not include_member(member.filename):
                        continue
                    if name.is_absolute() or '..' in name.parts or '\\' in member.filename or ':' in member.filename:
                        result.download_failed[member.filename] = 'Unsafe path in CIF archive'
                        continue
                    members[member.filename] = member
                def read_member(_name, member):
                    if not 0 < member.file_size <= MAX_CIF_BYTES or member.flag_bits & 1:
                        raise ValueError('Empty, encrypted or excessive CIF in archive')
                    return archive_file.read(member)
                members = resolve_cif_import(cache,members,source,read_bytes=read_member,
                                             check=check,archive=True)
                for index, (_name, key, member) in enumerate(members):
                    check()
                    try:
                        if not 0 < member.file_size <= MAX_CIF_BYTES or member.flag_bits & 1:
                            raise ValueError('Empty, encrypted or excessive CIF in archive')
                        body = archive_file.read(member)
                        check()
                        # Never replace a CIF still referenced by a committed
                        # card before its new reflections have been prepared.
                        digest = hashlib.sha256(body).hexdigest()[:16]
                        output = target / (key + '-' + digest + '.cif')
                        with lock_cifs([output], check_cancelled=check):
                            if not output.is_file() or output.read_bytes() != body:
                                atomic_save_cif(output, body)
                        paths[key] = output
                    except LibraryCancelled:
                        raise
                    except Exception as error:
                        result.download_failed[key] = str(error)
                    if index % 100 == 0:
                        report('Reading CIF archive', index + 1, len(members))
        else:
            folder = Path(path)
            named_files = {}
            for file in sorted(folder.rglob('*')):
                check()
                if file.is_file() and file.suffix.lower() == '.cif':
                    named_files[file.relative_to(folder).as_posix()] = file
            records = resolve_cif_import(cache,named_files,source,
                read_bytes=lambda _name,file:file.read_bytes(),check=check)
            paths = {key:file for _name,key,file in records}
        result.total = len(paths) + len(result.download_failed)
        result.reused = len(paths)
        state = LibraryProgress(result.total)
        jobs = []
        keys = list(paths)
        for offset in range(0, len(keys), 100):
            check()
            batch = keys[offset:offset + 100]
            identities = [(source, key) for key in batch]
            entries = cache.iic_entries(identities)
            previous_paths.update({key: Path(entry.cif_path) for (_source, key), entry in entries.items()
                                   if entry.cif_path})
            covered = cache.reference_range_coverage(identities, cancelled=cancelled)
            for key in batch:
                check()
                file = paths[key]
                state.file_available(True)
                if current_preparation(file, entries.get((source, key)), covered=covered.get((source, key), False),
                                       calculated_iic=cache.calculated_iic):
                    result.skipped += 1
                    state.card_ready(skipped=True)
                else:
                    jobs.append((key, str(file)))
            report('Checking prepared CIF records', offset + len(batch), len(keys))
        state.finish_download(len(result.download_failed))
        publish(True)

        def ready(key, success, error):
            if success:
                result.prepared += 1
                old = previous_paths.get(key)
                if archive and old is not None and old != paths[key] and old.parent == target:
                    with closing(cache._connect()) as connection:
                        used = connection.execute('select 1 from phases where cif_path=? limit 1', (str(old),)).fetchone()
                    if used is None:
                        try:
                            old.unlink(missing_ok=True)
                        except OSError:
                            pass
            else:
                result.preparation_failed[key] = error or 'CIF could not be prepared'
            state.card_ready(failed=not success)
            report('Preparing CIF records', result.prepared + result.skipped + len(result.preparation_failed), len(paths))

        if jobs:
            state.start_processing()
            prepare_paths(cache.root, jobs, ready=ready, cancelled=cancelled, source=source)
        check()
        state.finish()
    except LibraryCancelled:
        result.cancelled = True
    finally:
        publish(True)
    return result
