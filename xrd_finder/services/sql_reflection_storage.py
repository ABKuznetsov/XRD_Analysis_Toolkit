"""Exact peak JSON reconstructed from authoritative SQLite reflection columns.

Only serializer metadata and extra fields are stored twice. Unusual payloads
that cannot be reconstructed exactly retain the independent packed JSON.
"""
from __future__ import annotations

import hashlib
import json
import zlib
import sys
from collections import OrderedDict
from pathlib import Path
from threading import RLock

from xrd_finder.services.cache_json import (
    SQL_MAGIC, HEADER, MAX_JSON_BYTES, MAX_PREFIX_BYTES, _header, _peak_header,
    pack_json, unpack_json,
)
from xrd_finder.services.normalized_reflections import ordered_card_query

SQL_FIELDS = ('d', 'two_theta', 'intensity', 'raw_intensity', 'h', 'k', 'l',
              'multiplicity', 'intrinsic_intensity', 'intensity_origin')
_CASTS = {'float': float, 'int': int, 'str': str, 'NoneType': lambda _: None, 'bool': bool}
_SETTINGS = ((True, (',', ':')), (True, (', ', ': ')),
             (False, (',', ':')), (False, (', ', ': ')))


def is_sql_peaks(value):
    return isinstance(value, (bytes, bytearray, memoryview)) and bytes(value).startswith(SQL_MAGIC)


def _sql_rows(connection, source, entry_id):
    # Do not depend on the connection's Row/dict factory or field order elsewhere.
    records = connection.execute(
        ordered_card_query(connection,('peak_index',*SQL_FIELDS)), (source, entry_id)).fetchall()
    return [dict(zip(('peak_index', *SQL_FIELDS), row)) for row in records]


def _restore(metadata, rows):
    count, keys, types, extras = (metadata[k] for k in ('count', 'keys', 'types', 'extras'))
    if (not isinstance(count, int) or not 0 < count <= MAX_JSON_BYTES // 2
            or len(rows) != count or any(row['peak_index'] != i for i, row in enumerate(rows))):
        raise ValueError('SQL reflection count/order is missing or inconsistent')
    if (not isinstance(keys, list) or len(keys) != len(set(keys))
            or any(key not in SQL_FIELDS for key in keys)
            or len(types) != len(keys) or any(kind not in _CASTS for kind in types)
            or not isinstance(extras, dict)):
        raise ValueError('Invalid SQL peak reconstruction metadata')
    if any(not isinstance(fields, dict) or set(fields).intersection(keys)
           or not str(index).isdigit() or int(index) >= count for index, fields in extras.items()):
        raise ValueError('Invalid additional SQL peak fields')
    result = []
    for i, row in enumerate(rows):
        fields = {key: _CASTS[kind](row[key]) for key, kind in zip(keys, types)}
        fields.update(extras.get(str(i), {}))
        result.append(fields)
    return json.dumps(result, ensure_ascii=metadata['ascii'], separators=tuple(metadata['separators']))


def pack_sql_peaks(text, connection, source, entry_id, *, fallback=None):
    """Use SQL only when rebuilding proves byte-for-byte equality and saves space."""
    text = unpack_sql_peaks(text, connection, source, entry_id)
    fallback = pack_json(text, peaks=True) if fallback is None else fallback
    body = text.encode('utf-8')
    if not 1024 <= len(body) <= MAX_JSON_BYTES:
        return fallback
    try:
        original = json.loads(text)
        if not isinstance(original, list) or not original or not all(isinstance(r, dict) for r in original):
            return fallback
        keys = [key for key in original[0] if key in SQL_FIELDS]
        types = [type(original[0][key]).__name__ for key in keys]
        if not keys or any(kind not in _CASTS for kind in types):
            return fallback
        if any([k for k in row if k in SQL_FIELDS] != keys
               or [type(row[k]).__name__ for k in keys] != types for row in original):
            return fallback
        extra = {str(i): {key: value for key, value in row.items() if key not in keys}
                 for i, row in enumerate(original)}
        extra = {i: fields for i, fields in extra.items() if fields}
        metadata = dict(count=len(original), keys=keys, types=types, extras=extra)
        rows = _sql_rows(connection, source, entry_id)
        preferred = (text.isascii(), (', ', ': ') if ': ' in text[:64] else (',', ':'))
        settings = (preferred, *(setting for setting in _SETTINGS if setting!=preferred))
        for ascii_text, separators in settings:
            metadata.update(ascii=ascii_text, separators=separators)
            if _restore(metadata, rows) == text:
                break
        else:
            return fallback
        prefix = _peak_header(text)
        if len(prefix) > MAX_PREFIX_BYTES:
            return fallback
        descriptor = json.dumps(metadata, ensure_ascii=True, separators=(',', ':')).encode()
        if len(descriptor) > len(body):
            return fallback
        packed = (SQL_MAGIC + HEADER.pack(len(prefix), len(body), zlib.crc32(prefix))
                  + hashlib.sha256(body).digest() + prefix + zlib.compress(descriptor, 6))
        fallback_size = len(fallback if isinstance(fallback, bytes) else fallback.encode('utf-8'))
        return packed if len(packed) < fallback_size else fallback
    except (ValueError, TypeError, KeyError, OverflowError):
        return fallback


def unpack_sql_peaks(value, connection, source, entry_id):
    if not is_sql_peaks(value):
        return unpack_json(value)
    value = bytes(value)
    offset, size, digest, _prefix = _header(value)
    try:
        decoder = zlib.decompressobj()
        descriptor = decoder.decompress(value[offset:], size + 1)
        if (len(descriptor) > size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
            raise ValueError('SQL peak descriptor is damaged')
        metadata = json.loads(descriptor)
        text = _restore(metadata, _sql_rows(connection, source, entry_id))
        body = text.encode('utf-8')
        if len(body) != size or hashlib.sha256(body).digest() != digest:
            raise ValueError('SQL reflection data changed: peak checksum mismatch')
        return text
    except (zlib.error, UnicodeError, TypeError, KeyError, OverflowError) as error:
        raise ValueError('SQL-backed peak data is damaged') from error


class SqlPeakTextCache:
    """Small object-local LRU; primary SQL remains the persisted source.

    The payload digest identifies the original text. File generations also
    invalidate entries after another connection changes the primary SQL rows.
    Do not cache a reconstruction if a writer committed while it was read.
    """
    def __init__(self, path, *, max_cards=8, max_bytes=16*1024*1024):
        self.path = Path(path)
        self.max_cards, self.max_bytes = max_cards, max_bytes
        self._entries, self._bytes = OrderedDict(), 0
        self._lock = RLock()

    def _generation(self):
        values = []
        for path in (self.path, Path(str(self.path)+'-wal')):
            try:
                stat = path.stat()
                values.append((stat.st_ino,stat.st_size,stat.st_mtime_ns))
            except FileNotFoundError:
                values.append(None)
        return tuple(values)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def read(self, value, connection, source, entry_id, *, generation=None):
        generation = self._generation() if generation is None else generation
        key = (source,entry_id,bytes(value),generation)
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and generation==self._generation():
                self._entries.move_to_end(key)
                return hit
        text = unpack_sql_peaks(value,connection,source,entry_id)
        size = sys.getsizeof(text)
        with self._lock:
            if generation==self._generation() and size<=self.max_bytes and self.max_cards>0:
                # Remove older generations and respect both independent limits.
                for old in list(self._entries):
                    if old[-1]!=generation:
                        self._bytes -= sys.getsizeof(self._entries.pop(old))
                if key not in self._entries:
                    self._entries[key] = text
                    self._bytes += size
                while len(self._entries)>self.max_cards or self._bytes>self.max_bytes:
                    self._bytes -= sys.getsizeof(self._entries.popitem(last=False)[1])
        return text
