"""Lossless cached JSON with a small independently readable peak header."""
from __future__ import annotations

import hashlib
import json
import struct
import zlib

MAGIC = b'XRDJ\x01'
SQL_MAGIC = b'XRDS\x01'
HEADER = struct.Struct('>HQI')  # prefix bytes, original UTF-8 bytes, prefix CRC32
FIXED_BYTES = len(MAGIC)+HEADER.size+32
MAX_JSON_BYTES = 256*1024*1024
MAX_PREFIX_BYTES = 900  # Entire support header fits substr(...,1,1024).


def _peak_header(text: str) -> bytes:
    offset = 0
    while offset<len(text) and text[offset].isspace():
        offset += 1
    if offset==len(text) or text[offset]!='[':
        return b''
    offset += 1
    while offset<len(text) and text[offset].isspace():
        offset += 1
    try:
        first,_ = json.JSONDecoder().raw_decode(text,offset)
    except ValueError:
        return b'[]'
    if not isinstance(first,dict):
        return b''
    metadata = {k:first[k] for k in ('intensity_origin','reference_support') if k in first}
    return json.dumps([metadata],ensure_ascii=True,separators=(',',':')).encode()


def pack_json(text: str | bytes, *, peaks: bool = False) -> str | bytes:
    """Preserve original JSON text exactly; small/non-beneficial fields stay text."""
    text = unpack_json(text)
    body = text.encode('utf-8')
    if len(body)<1024 or len(body)>MAX_JSON_BYTES:
        return text
    prefix = _peak_header(text) if peaks else b''
    if len(prefix)>MAX_PREFIX_BYTES:
        return text
    packed = (MAGIC+HEADER.pack(len(prefix),len(body),zlib.crc32(prefix))
              +hashlib.sha256(body).digest()+prefix+zlib.compress(body,6))
    return packed if len(packed)<len(body) else text


def _header(value: bytes) -> tuple[int,int,bytes,bytes]:
    if value[:len(MAGIC)] not in (MAGIC, SQL_MAGIC) or len(value)<FIXED_BYTES:
        raise ValueError('Unsupported or truncated cached JSON format')
    prefix_size,body_size,crc = HEADER.unpack_from(value,len(MAGIC))
    if prefix_size>MAX_PREFIX_BYTES or body_size>MAX_JSON_BYTES:
        raise ValueError('Invalid cached JSON size')
    offset = FIXED_BYTES+prefix_size
    prefix = value[FIXED_BYTES:offset]
    if len(prefix)!=prefix_size or zlib.crc32(prefix)!=crc:
        raise ValueError('Cached peak header is damaged')
    digest = value[len(MAGIC)+HEADER.size:FIXED_BYTES]
    return offset,body_size,digest,prefix


def unpack_json(value: str | bytes) -> str:
    if isinstance(value,str):
        return value
    if not isinstance(value,(bytes,bytearray,memoryview)):
        raise ValueError('Invalid cached JSON field type')
    value = bytes(value)
    if value.startswith(b'XRDS'):
        raise ValueError('SQL-backed peak JSON requires its reflection database')
    if not value.startswith(b'XRDJ'):
        try:
            return value.decode('utf-8')
        except UnicodeError as exc:
            raise ValueError('Cached JSON is not valid UTF-8') from exc
    offset,size,digest,_prefix = _header(value)
    try:
        decoder = zlib.decompressobj()
        body = decoder.decompress(value[offset:],size+1)
        if (len(body)!=size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                or hashlib.sha256(body).digest()!=digest):
            raise ValueError('Cached JSON payload is damaged')
        return body.decode('utf-8')
    except (zlib.error,UnicodeError) as exc:
        raise ValueError('Cannot decode cached JSON payload') from exc


def peak_prefix(value: str | bytes) -> str:
    """Accept either a legacy text prefix or the first 1024 packed bytes."""
    if isinstance(value,str):
        return value
    value = bytes(value)
    if value.startswith((b'XRDJ', b'XRDS')):
        return _header(value)[3].decode('utf-8')
    return value.decode('utf-8')
