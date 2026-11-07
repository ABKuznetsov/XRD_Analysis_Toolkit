"""Named CIF connections: folders, archives, archive URLs and mapped JSON APIs."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import os
import tempfile
from urllib.parse import quote, urljoin, urlsplit
from uuid import uuid4

from xrd_finder.services.cod_cif_store import atomic_save_cif, lock_cifs
from xrd_finder.services.cod_inorganic_library import LibraryCancelled
from xrd_finder.services.database_http_session import DatabaseHttpSession
from xrd_finder.services.local_cif_preparation import prepare_local_cif_library
from xrd_finder.services.network import create_ssl_context
from xrd_finder.services.source_registry import is_custom_source

SETTINGS_KEY = 'databases/custom_connections_v1'
KINDS = {'folder','zip','zip_url','json_api'}


def _check(cancelled):
    if cancelled():
        raise LibraryCancelled('Database operation cancelled')


def _http_url(url):
    parsed=urlsplit(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTP(S) address without embedded credentials')
    return url


@dataclass
class LibraryConnection:
    name: str
    kind: str
    location: str
    source: str = field(default_factory=lambda:'LIB_'+uuid4().hex[:12].upper())
    enabled: bool = True
    api_key: str = ''
    auth_header: str = 'Authorization'
    results_path: str = ''
    id_field: str = 'id'
    formula_field: str = 'formula'
    name_field: str = 'name'
    cif_field: str = 'cif_url'
    preset: str = ''

    def validate(self):
        if not self.name.strip() or self.kind not in KINDS or not is_custom_source(self.source):
            raise ValueError('Enter a database name and choose a supported connection type')
        if not self.location.strip():
            raise ValueError('Enter a folder, file or online address')
        if self.preset:
            from xrd_finder.services.curated_libraries import PRESETS
            if self.preset not in PRESETS or PRESETS[self.preset].source!=self.source or self.kind not in {'zip','zip_url'}:
                raise ValueError('Invalid prepared library preset; use its original CIF archive')
        if self.kind in {'zip_url','json_api'}:
            _http_url(self.location.replace('{query}','test').replace('{limit}','500'))
        if self.kind=='json_api':
            if not self.id_field.strip() or not self.cif_field.strip():
                raise ValueError('The API needs ID and CIF URL field names')
        if self.api_key and (not self.auth_header or any(c in self.auth_header+self.api_key for c in '\r\n')):
            raise ValueError('Invalid authentication header')
        return self

    def headers(self, url):
        # A separate CIF host must never receive the database API credential.
        if self.api_key and urlsplit(url).netloc==urlsplit(self.location).netloc and urlsplit(url).scheme==urlsplit(self.location).scheme:
            return {self.auth_header:self.api_key}
        return {}


def load_connections(settings):
    try:
        records=json.loads(settings.value(SETTINGS_KEY,'[]'))
        return [LibraryConnection(**item).validate() for item in records]
    except (ValueError,TypeError):
        return []


def save_connections(settings, connections):
    for connection in connections:connection.validate()
    if len({c.source for c in connections})!=len(connections):
        raise ValueError('Duplicate database connection identity')
    settings.setValue(SETTINGS_KEY,json.dumps([asdict(c) for c in connections]))
    settings.sync()


def _read(response, maximum, cancelled):
    body=bytearray()
    while True:
        _check(cancelled)
        chunk=response.read(min(256*1024, maximum+1-len(body)))
        if not chunk:return bytes(body)
        body.extend(chunk)
        if len(body)>maximum:raise ValueError('Database response exceeds the size limit')


def _field(record, path):
    value=record
    for part in path.split('.') if path else ():
        if not isinstance(value,dict) or part not in value:
            raise ValueError('JSON field not found: '+path)
        value=value[part]
    return value


class JsonCifSource:
    def __init__(self, connection):
        self.connection=connection.validate()
        self.session=DatabaseHttpSession(create_ssl_context())
        self.cif_urls={}

    def search(self, query, *, cancelled=lambda:False):
        c=self.connection
        url=c.location.replace('{query}',quote(str(query),safe='')).replace('{limit}','500')
        _http_url(url);_check(cancelled)
        with self.session.open(url,headers=c.headers(url),timeout=15.) as response:
            data=json.loads(_read(response,8*1024*1024,cancelled))
        records=_field(data,c.results_path)
        if not isinstance(records,list):
            raise ValueError('API results must be a JSON array; set the results field path')
        rows={}
        for record in records[:500]:
            _check(cancelled)
            raw_id=_field(record,c.id_field)
            if not isinstance(raw_id,(str,int)) or isinstance(raw_id,bool):
                raise ValueError('API card ID must be a string or integer')
            entry=str(raw_id).strip()
            cif_url=_http_url(urljoin(url,str(_field(record,c.cif_field))))
            if not entry:raise ValueError('API returned an empty card ID')
            self.cif_urls[entry]=cif_url
            def optional(path):
                try:return str(_field(record,path) or '') if path else ''
                except ValueError:return ''
            formula=optional(c.formula_field)
            # Last complete record wins for duplicate IDs; its metadata and
            # download URL must refer to the same card version.
            rows[entry]=[c.source,entry,formula,optional(c.name_field) or formula or entry,'','','','']
        return list(rows.values())

    def download_cif(self, entry, target, *, cancelled=lambda:False):
        url=self.cif_urls.get(entry)
        if not url:raise ValueError('Search this database again to obtain the CIF download link')
        target=Path(target);target.mkdir(parents=True,exist_ok=True)
        path=target/(hashlib.sha256(entry.encode()).hexdigest()+'.cif')
        with lock_cifs([path],check_cancelled=lambda:_check(cancelled)):
            if path.is_file():return path
            _check(cancelled)
            with self.session.open(url,headers=self.connection.headers(url),timeout=15.) as response:
                data=_read(response,8*1024*1024,cancelled)
            return atomic_save_cif(path,data)


def prepare_connection(cache, connection, *, progress=None, status=None, cancelled=lambda:False):
    c=connection.validate();_check(cancelled)
    if c.preset:
        from xrd_finder.services.curated_libraries import prepare_curated_library
        return prepare_curated_library(cache,c,progress=progress,status=status,cancelled=cancelled)
    if c.kind=='json_api':
        raise ValueError('Use Search database to query this JSON API and prepare the returned CIF cards')
    path=Path(c.location).expanduser()
    if c.kind=='zip_url':
        temporary=None
        try:
            folder=cache.root/'downloads';folder.mkdir(parents=True,exist_ok=True)
            session=DatabaseHttpSession(create_ssl_context())
            with session.open(c.location,headers=c.headers(c.location),timeout=20.) as response:
                with tempfile.NamedTemporaryFile(dir=folder,suffix='.part',delete=False) as output:
                    temporary=Path(output.name);size=0
                    while True:
                        _check(cancelled);chunk=response.read(256*1024)
                        if not chunk:break
                        size+=len(chunk)
                        if size>512*1024*1024:raise ValueError('CIF ZIP download exceeds 512 MB')
                        output.write(chunk)
                        if progress:progress('Downloading CIF archive (bytes)',size,0)
            path=folder/(c.source+'.zip');os.replace(temporary,path)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    if c.kind=='folder' and not path.is_dir():raise ValueError('CIF folder does not exist')
    if c.kind!='folder' and not path.is_file():raise ValueError('CIF ZIP file does not exist')
    return prepare_local_cif_library(cache,path,archive=c.kind!='folder',source=c.source,
        progress=progress,status=status,cancelled=cancelled)
