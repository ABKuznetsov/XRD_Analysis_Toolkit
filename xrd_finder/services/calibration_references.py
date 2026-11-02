"""Select actual calibration CIFs without borrowing the main pattern's filters."""
from concurrent.futures import CancelledError
from pathlib import Path

from xrd_finder.services.candidate_rows import normalize_candidate_row
from xrd_finder.services.network import ensure_online_allowed
from xrd_finder.finder.composition_validation import chemical_search_key


STRUCTURE_SOURCES = frozenset({'COD', 'USER', 'CCDC', 'MP', 'AFLOW', 'OQMD'})


class CalibrationReferenceLibrary:
    def __init__(self, cache, *, search_service=None, options=None, resolver=None, project_rows=()):
        self.cache = cache
        self.search_service = search_service
        self.options = options
        self.resolver = resolver
        self.project_rows = tuple(dict(row) for row in project_rows)

    def search(self, query, *, cancelled=lambda:False, progress=lambda *_:None):
        if cancelled(): raise CancelledError('Reference search cancelled.')
        query = query.strip()
        needle = query.casefold()
        formula_key = chemical_search_key(query)
        rows = [dict(row) for row in self.project_rows if not needle or any(
            needle in str(row.get(field, '')).casefold() for field in ('Entry','Formula','Phase'))
            or (formula_key and formula_key == chemical_search_key(row.get('Formula','')))]
        progress('Searching structure databases…', 0, 0)
        # All installed structure sources are eligible; element/source filters
        # from the unrelated sample being studied must not hide its standard.
        entries = self.cache.search(text=query, sources=sorted(STRUCTURE_SOURCES),
            limit=300, summary_only=True, deduplicate=False, cancelled=cancelled)
        rows.extend(dict(Source=e.source, Entry=e.entry_id, Formula=e.formula,
                         Phase=e.name, Spacegroup=e.spacegroup) for e in entries)
        if query and self.search_service is not None:
            remote = self.search_service.search_text(query, self.options,
                progress=progress, partial_results=lambda _rows:None, cancelled=cancelled)
            for raw in remote:
                row = normalize_candidate_row(raw)
                if row[0] in STRUCTURE_SOURCES and row[1]:
                    rows.append(dict(zip(('Source','Entry','Formula','Phase','Spacegroup','Notes'),row[:6])))
        if cancelled(): raise CancelledError('Reference search cancelled.')
        result = []; seen = set()
        for row in rows:
            key = row['Source'], row['Entry']
            if key not in seen: result.append(row); seen.add(key)
        return result

    def resolve(self, row, *, cancelled=lambda:False, progress=lambda *_:None):
        if cancelled(): raise CancelledError('Reference selection cancelled.')
        source, entry = row.get('Source',''), row.get('Entry','')
        if source == 'PROJECT':
            path = Path(row.get('_Path',''))
        elif source in STRUCTURE_SOURCES:
            path = self.cache.cif_path(source, entry)
            if path is None:
                if source not in {'COD','MP','AFLOW','OQMD'} or self.resolver is None:
                    raise ValueError('This card has no available CIF. Import or download its structure first.')
                ensure_online_allowed('Calibration CIF download')
                progress(f'Loading CIF · {source} {entry}…', 0, 0)
                path = self.resolver(dict(row))
        else:
            raise ValueError('Choose a structure card with a CIF, not a reference-only pattern.')
        if cancelled(): raise CancelledError('Reference selection cancelled.')
        if path is None or not Path(path).is_file():
            raise ValueError('The selected CIF file is unavailable.')
        return Path(path)
