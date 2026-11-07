"""Persistent import origins keep legacy public IDs valid for saved projects."""
from contextlib import closing
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re


ORIGIN_TABLE = 'local_cif_origins'
ORIGIN_SCHEMA = '''create table if not exists local_cif_origins (
    source text not null, entry_id text not null, relative_path text not null,
    primary key(source,relative_path), unique(source,entry_id))'''


class CifIdentityConflict(ValueError):
    """An import cannot safely associate an old public ID with an input file."""


def ensure_origin_schema(connection):
    connection.execute(ORIGIN_SCHEMA)


def cif_import_entries(named_files, source):
    """Return (relative path, public ID, file) without depending on neighbours."""
    entries = {}
    for name, value in named_files.items():
        stem = PurePosixPath(name).stem
        if source == 'COD' and re.fullmatch(r'\d{7}', stem):
            entries[stem] = (name, stem, value)  # Last numeric COD member wins.
    for name, value in sorted(named_files.items()):
        stem = PurePosixPath(name).stem
        if source == 'COD' and re.fullmatch(r'\d{7}', stem):
            continue
        digest = hashlib.sha256(name.encode('utf-8')).hexdigest()
        prefix = stem.encode('utf-8')[:120].decode('utf-8', errors='ignore')
        key = prefix+'--'+digest
        entries[key] = (name, key, value)
    return list(entries.values())


def bind_origins(connection, source, bindings, *, check=lambda: None):
    """Reserve path identities in the caller's transaction, never reassign IDs.

    A reservation can precede a worker commit. Failed/cancelled preparations do
    not create a phase; retrying still uses the same ID. Exports omit reservations
    without a committed phase. Each lookup is indexed, not a per-card full scan.
    """
    for name, key in bindings.items():
        check()
        existing = connection.execute(
            'select entry_id,relative_path from local_cif_origins '
            'where source=? and (relative_path=? or entry_id=?)',
            (source, name, key)).fetchall()
        if any(tuple(row) != (key, name) for row in existing):
            raise CifIdentityConflict('Conflicting saved CIF origin for '+source+' '+name)
        if not existing:
            connection.execute('insert into local_cif_origins values (?,?,?)',(source,key,name))


def validate_origins(connection):
    for source, key, name, present in connection.execute(
            'select o.source,o.entry_id,o.relative_path,p.entry_id from local_cif_origins o '
            'left join phases p on p.source=o.source and p.entry_id=o.entry_id'):
        path = PurePosixPath(name)
        if (not source or not key or not name or present is None or path.is_absolute()
                or '..' in path.parts or '\\' in name or ':' in name):
            raise ValueError('Invalid CIF import origin in prepared library')


def resolve_cif_import(cache, named_files, source, *, read_bytes, check=lambda:None, archive=False):
    """Adopt provable legacy owners, persist them, and plan before writing CIFs.

    Old folder imports retain their exact file path. Old suffixed IDs encode the
    relative path. A flattened old ZIP loses that path: adopt its basename ID
    only when one unclaimed input matches its committed CIF checksum. Otherwise
    refuse the ambiguous group instead of creating a duplicate or guessing.
    """
    entries = cif_import_entries(named_files, source)
    generic = [(name,key,value) for name,key,value in entries
               if not (source=='COD' and re.fullmatch(r'\d{7}',key))]
    if not generic:
        return entries
    with closing(cache._connect()) as connection:
        # Metadata only: never hydrate atoms or reflection arrays for this step.
        old = {row[0]: row[1] for row in connection.execute(
            'select entry_id,cif_path from phases where source=?',(source,))}
        origins = dict(connection.execute(
            'select relative_path,entry_id from local_cif_origins where source=?',(source,)))
    claimed = {key:name for name,key in origins.items()}
    ids = {}
    by_path = defaultdict(list)
    if not archive:
        for key, path in old.items():
            if path: by_path[os.path.abspath(path)].append(key)

    def claim(name, key):
        owner = claimed.get(key)
        if owner is not None and owner!=name:
            raise CifIdentityConflict('Conflicting CIF owner for '+source+' '+key)
        ids[name] = key
        claimed[key] = name

    for name, key, value in generic:
        check()
        if name in origins:
            claim(name,origins[name]); continue
        stem = PurePosixPath(name).stem
        digest = hashlib.sha256(name.encode('utf-8')).hexdigest()
        candidates = {candidate for candidate in [key,*[stem+'--'+digest[:n] for n in range(12,65,4)]]
                      if candidate in old}
        if not archive:
            candidates.update(by_path.get(os.path.abspath(value),()))
        if len(candidates)>1:
            raise CifIdentityConflict('Ambiguous existing CIF identities for '+name)
        if candidates:
            claim(name,next(iter(candidates)))

    groups = defaultdict(list)
    for name, key, value in generic:
        if name not in ids: groups[PurePosixPath(name).stem].append((name,key,value))
    with closing(cache._connect()) as connection:
        for stem, records in groups.items():
            check()
            if stem not in old or stem in claimed:
                continue
            # Prefer the stored structure hash if the original folder has changed
            # since it was indexed, or its CIF is now stored in a portable blob.
            row=connection.execute('select iic_method from phases where source=? and entry_id=?',
                                   (source,stem)).fetchone()
            try:
                previous = json.loads((row[0] if row else '') or '{}').get('structure','')
            except (ValueError,TypeError,AttributeError):
                previous = ''
            if not re.fullmatch(r'[a-f0-9]{64}',str(previous)):
                try: previous=hashlib.sha256(Path(old[stem]).read_bytes()).hexdigest()
                except OSError: previous=''
            matches=[]
            for name,key,value in records:
                check()
                digest=hashlib.sha256(read_bytes(name,value)).hexdigest()
                if previous and digest==previous:matches.append(name)
            if len(matches)!=1:
                raise CifIdentityConflict(
                    'Cannot safely associate legacy CIF ID '+source+':'+stem+
                    ' (ambiguous or changed original). Import its original unchanged CIF '
                    'by itself once to record the origin, then reimport the updated library.')
            claim(matches[0],stem)
    for name,key,value in generic:
        if name not in ids:claim(name,key)
    check()
    with closing(cache._connect()) as connection, connection:
        connection.execute('begin immediate')
        bind_origins(connection,source,ids,check=check)
        check()
    return [(name,ids.get(name,key),value) for name,key,value in entries]
