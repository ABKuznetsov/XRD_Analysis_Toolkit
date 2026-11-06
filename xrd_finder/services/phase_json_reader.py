"""Incremental legacy library reader; memory follows one value, not the file."""
from concurrent.futures import CancelledError
import json

CHUNK_CHARS = 64*1024
MAX_VALUE_CHARS = 256*1024**2
_WHITESPACE = ' \t\r\n'


class _Reader:
    def __init__(self,stream,cancelled,progress):
        self.stream,self.cancelled,self.progress = stream,cancelled,progress
        self.buffer = ''
        self.position = 0
        self.eof = False
        self.decoder = json.JSONDecoder()

    def check(self):
        if self.cancelled():
            raise CancelledError('Phase library import cancelled')

    def grow(self,amount=CHUNK_CHARS):
        self.check()
        self.buffer = self.buffer[self.position:]
        self.position = 0
        part = self.stream.read(amount)
        self.eof = not part
        self.buffer += part
        if self.progress:
            self.progress(self.stream.tell())

    def peek(self):
        while True:
            self.check()
            while self.position<len(self.buffer) and self.buffer[self.position] in _WHITESPACE:
                self.position += 1
            if self.position<len(self.buffer):
                return self.buffer[self.position]
            if self.eof:
                return ''
            self.grow()

    def expect(self,token):
        if self.peek()!=token:
            raise ValueError('Invalid phase library JSON: expected '+repr(token))
        self.position += 1

    def value(self):
        if not self.peek():
            raise ValueError('Truncated phase library JSON')
        while True:
            self.check()
            try:
                value,end = self.decoder.raw_decode(self.buffer,self.position)
            except json.JSONDecodeError as error:
                if self.eof:
                    raise ValueError('Invalid or truncated phase library JSON') from error
            else:
                if end-self.position>MAX_VALUE_CHARS:
                    raise ValueError('A phase library JSON value is too large')
                if end==len(self.buffer) and not self.eof:
                    # A number ending at a chunk edge may continue with . or e.
                    self.grow(1)
                    continue
                following = self.buffer[end:end+1]
                if not following or following in _WHITESPACE+',]}:':
                    self.position = end
                    return value
                if not (isinstance(value,(int,float)) and following in '.eE' and not self.eof):
                    raise ValueError('Invalid phase library JSON value separator')
            remaining = len(self.buffer)-self.position
            if remaining>=MAX_VALUE_CHARS:
                raise ValueError('A phase library JSON value is too large or invalid')
            self.grow(min(max(CHUNK_CHARS,remaining),MAX_VALUE_CHARS+1-remaining))


def iter_phase_entries(stream, *, cancelled=lambda:False, progress=None):
    """Yield entries; exhausting the iterator validates the entire container.

    The caller must exhaust a validation pass before writing to a destination:
    legacy headers may appear after entries. Unknown root metadata is decoded
    and checked, with the same per-value limit as individual cards.
    """
    reader = _Reader(stream,cancelled,progress)
    reader.expect('{')
    library = None
    seen = set()
    first = True
    while reader.peek()!='}':
        if not first:
            reader.expect(',')
        first = False
        key = reader.value()
        if not isinstance(key,str):
            raise ValueError('Invalid phase library JSON object key')
        reader.expect(':')
        if key in ('library','entries'):
            if key in seen:
                raise ValueError('Duplicate phase library JSON field: '+key)
            seen.add(key)
        if key=='entries':
            reader.expect('[')
            first_entry = True
            while reader.peek()!=']':
                if not first_entry:
                    reader.expect(',')
                first_entry = False
                yield reader.value()
            reader.expect(']')
        else:
            value = reader.value()
            if key=='library':
                library = value
    reader.expect('}')
    if reader.peek():
        raise ValueError('Trailing data after phase library JSON')
    if library not in ('user_phase_library','phase_library'):
        raise ValueError('Unsupported phase library file')
    if 'entries' not in seen:
        raise ValueError('Phase library file does not contain entries')
