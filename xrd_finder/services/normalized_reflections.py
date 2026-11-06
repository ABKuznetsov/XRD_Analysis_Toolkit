"""Lossless reflection dictionaries; scientific columns stay directly indexed.

The public phase_peaks view retains the old read/write contract. Integer card
keys are independent of phases.rowid, so VACUUM and card upserts cannot reassign
reflections. Origin strings are interned, including mixed origins within a card.
"""
from concurrent.futures import CancelledError
from contextlib import closing, contextmanager
import sqlite3

FIELDS = ('source','entry_id','peak_index','two_theta','d','intensity',
          'norm_intensity','top_rank','raw_intensity','h','k','l','multiplicity',
          'intrinsic_intensity','intensity_origin')
LINE_FIELDS = FIELDS[2:-1]
LEGACY_DDL = """create table phase_peaks (
    source text not null, entry_id text not null, peak_index integer not null,
    two_theta real not null, d real, intensity real not null default 0,
    norm_intensity real not null default 0, top_rank integer,
    raw_intensity real not null default 0, h integer, k integer, l integer,
    multiplicity integer, intrinsic_intensity real,
    intensity_origin text not null default '', primary key(source,entry_id,peak_index))"""

_TABLES = (
    """create table reflection_cards (
        phase_id integer primary key, source text not null, entry_id text not null,
        unique(source,entry_id))""",
    """create table reflection_origins (
        origin_id integer primary key, value text not null unique)""",
    """create table reflection_lines (
        phase_id integer not null, peak_index integer not null,
        two_theta real not null, d real, intensity real not null default 0,
        norm_intensity real not null default 0, top_rank integer,
        raw_intensity real not null default 0, h integer, k integer, l integer,
        multiplicity integer, intrinsic_intensity real, origin_id integer not null,
        primary key(phase_id,peak_index),
        foreign key(phase_id) references reflection_cards(phase_id),
        foreign key(origin_id) references reflection_origins(origin_id)) without rowid""",
)
VIEW_DDL = ('create view phase_peaks as select c.source,c.entry_id,'
            + ','.join('r.'+name for name in LINE_FIELDS)
            + ',o.value as intensity_origin from reflection_lines r '
              'join reflection_cards c on c.phase_id=r.phase_id '
              'join reflection_origins o on o.origin_id=r.origin_id')
_TRIGGERS = (
    """create trigger phase_peaks_insert instead of insert on phase_peaks begin
        insert into reflection_cards(source,entry_id) values(new.source,new.entry_id)
            on conflict(source,entry_id) do nothing;
        insert into reflection_origins(value) values(coalesce(new.intensity_origin,''))
            on conflict(value) do nothing;
        insert into reflection_lines(phase_id,peak_index,two_theta,d,intensity,
            norm_intensity,top_rank,raw_intensity,h,k,l,multiplicity,intrinsic_intensity,origin_id)
        values((select phase_id from reflection_cards where source=new.source and entry_id=new.entry_id),
            new.peak_index,new.two_theta,new.d,coalesce(new.intensity,0),
            coalesce(new.norm_intensity,0),new.top_rank,coalesce(new.raw_intensity,0),
            new.h,new.k,new.l,new.multiplicity,new.intrinsic_intensity,
            (select origin_id from reflection_origins where value=coalesce(new.intensity_origin,'')))
        on conflict(phase_id,peak_index) do update set
            two_theta=excluded.two_theta,d=excluded.d,intensity=excluded.intensity,
            norm_intensity=excluded.norm_intensity,top_rank=excluded.top_rank,
            raw_intensity=excluded.raw_intensity,h=excluded.h,k=excluded.k,l=excluded.l,
            multiplicity=excluded.multiplicity,intrinsic_intensity=excluded.intrinsic_intensity,
            origin_id=excluded.origin_id;
    end""",
    """create trigger phase_peaks_delete instead of delete on phase_peaks begin
        delete from reflection_lines where phase_id=(select phase_id from reflection_cards
            where source=old.source and entry_id=old.entry_id) and peak_index=old.peak_index;
    end""",
)


def normalized_reflections(connection):
    return connection.execute("select 1 from sqlite_master where type='view' and name='phase_peaks'").fetchone() is not None


def create_indexes(connection):
    connection.execute('create index if not exists idx_reflection_lines_d '
        'on reflection_lines(d,phase_id,peak_index,top_rank,norm_intensity,intensity)')
    connection.execute('create index if not exists idx_reflection_lines_top_rank '
        'on reflection_lines(top_rank,two_theta,phase_id) where top_rank is not null')


@contextmanager
def _transaction(connection):
    # A savepoint never commits its caller's migration/import transaction.
    connection.execute('savepoint reflection_storage')
    try:
        yield
        connection.execute('release reflection_storage')
    except BaseException:
        connection.execute('rollback to reflection_storage')
        connection.execute('release reflection_storage')
        raise


def _check(cancelled):
    if cancelled():
        raise CancelledError('Reflection storage conversion cancelled; original retained')


def normalize_reflections(connection, *, progress=None, cancelled=lambda:False):
    _check(cancelled)
    if normalized_reflections(connection):
        return
    with _transaction(connection):
        for sql in _TABLES:
            connection.execute(sql)
        connection.execute('insert into reflection_cards(source,entry_id) '
            'select distinct source,entry_id from phase_peaks order by source,entry_id')
        connection.execute('insert into reflection_origins(value) '
            'select distinct intensity_origin from phase_peaks order by intensity_origin')
        if progress:
            progress('Sharing reflection identifiers and origins',0,0)
        _check(cancelled)
        columns=','.join('p.'+field for field in LINE_FIELDS)
        connection.execute('insert into reflection_lines select c.phase_id,'+columns+',o.origin_id '
            'from phase_peaks p join reflection_cards c on c.source=p.source and c.entry_id=p.entry_id '
            'join reflection_origins o on o.value=p.intensity_origin')
        _check(cancelled)
        before=connection.execute('select count(*) from phase_peaks').fetchone()[0]
        after=connection.execute('select count(*) from reflection_lines').fetchone()[0]
        if before!=after:
            raise ValueError('Reflection count changed during storage conversion')
        connection.execute('drop table phase_peaks')
        connection.execute(VIEW_DDL)
        for sql in _TRIGGERS:
            connection.execute(sql)
        create_indexes(connection)
        _check(cancelled)


def denormalize_reflections(connection, *, cancelled=lambda:False):
    """Compatibility export/import staging only; no scientific reconstruction."""
    if not normalized_reflections(connection):
        return
    _check(cancelled)
    with _transaction(connection):
        connection.execute(LEGACY_DDL.replace('table phase_peaks (','table phase_peaks_legacy (',1))
        connection.execute('insert into phase_peaks_legacy select '+','.join(FIELDS)+' from phase_peaks')
        if connection.execute('select count(*) from phase_peaks_legacy').fetchone()[0] != connection.execute('select count(*) from reflection_lines').fetchone()[0]:
            raise ValueError('Reflection dictionary contains missing references')
        _check(cancelled)
        connection.execute('drop view phase_peaks')  # SQLite drops its INSTEAD OF triggers.
        for table in ('reflection_lines','reflection_cards','reflection_origins'):
            connection.execute('drop table '+table)
        connection.execute('alter table phase_peaks_legacy rename to phase_peaks')
        _check(cancelled)


def range_join(connection):
    """Covering index path shared by automatic and manually selected peaks."""
    if normalized_reflections(connection):
        return ('reflection_lines pp indexed by idx_reflection_lines_d '
                'cross join reflection_cards pc on pc.phase_id=pp.phase_id '
                'cross join phases p on p.source=pc.source and p.entry_id=pc.entry_id')
    return ('phase_peaks pp indexed by idx_phase_peaks_d '
            'join phases p on p.source=pp.source and p.entry_id=pp.entry_id')


def ordered_card_query(connection, columns):
    """Avoid sorting/joining a whole compatibility view in profile scoring."""
    if normalized_reflections(connection):
        fields=','.join('o.value as intensity_origin' if field=='intensity_origin' else 'pp.'+field for field in columns)
        origin_join=(' join reflection_origins o on o.origin_id=pp.origin_id'
                     if 'intensity_origin' in columns else '')
        return (f'select {fields} from reflection_lines pp'+origin_join+
                ' where pp.phase_id=(select phase_id from reflection_cards where source=? and entry_id=?) '
                'order by pp.peak_index')
    return ('select '+','.join('pp.'+field for field in columns)+
            ' from phase_peaks pp indexed by sqlite_autoindex_phase_peaks_1 '
            'where pp.source=? and pp.entry_id=? order by pp.peak_index')


def indexed_card_count(connection):
    """Count occupied card keys, including after deletions left dictionary keys.

    Keep the origin join: the compatibility view also excludes lines whose
    dictionary entry is missing. Do not turn incomplete data into ready cards.
    """
    if normalized_reflections(connection):
        return int(connection.execute('select count(*) from reflection_cards c where exists('
            'select 1 from reflection_lines r join reflection_origins o on o.origin_id=r.origin_id '
            'where r.phase_id=c.phase_id)').fetchone()[0])
    return int(connection.execute("select count(distinct source || ':' || entry_id) from phase_peaks").fetchone()[0])


def validate_normalized_schema(connection):
    """Archive schemas must match our own definitions before reading any view."""
    with closing(sqlite3.connect(':memory:')) as expected:
        for sql in (*_TABLES,VIEW_DDL,*_TRIGGERS):
            expected.execute(sql)
        canonical={r[0]:(r[1],r[2]) for r in expected.execute(
            "select name,type,sql from sqlite_master where type in ('table','view','trigger')")}
    for name,(kind,sql) in canonical.items():
        row=connection.execute('select type,sql from sqlite_master where name=?',(name,)).fetchone()
        if row is None or tuple(row)!=(kind,sql):
            raise ValueError('Unsupported normalized reflection schema')
    return frozenset(canonical)
