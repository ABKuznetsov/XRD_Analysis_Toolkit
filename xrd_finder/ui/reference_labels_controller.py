"""Fetch only reference metadata, without blocking the GUI or preparing CIFs."""
import json
from threading import Event, Thread

from PySide6.QtCore import QObject, QTimer, Signal
from xrd_finder.services.security_mode import offline_mode_enabled

PROJECT_LABELS = 'reference_labels_v1'


def _merge(target, incoming):
    for key, data in incoming.items():
        if not isinstance(data, dict):
            continue
        if (key[0] == 'MP' and not isinstance(data.get('theoretical'), bool)
                and isinstance(target.get(key, {}).get('theoretical'), bool)):
            continue
        target[key] = data


def _project_labels(pattern):
    if pattern is None:
        return {}
    try:
        data = json.loads(pattern.metadata.get(PROJECT_LABELS, '{}'))
        return {tuple(key.split(':', 1)): value for key, value in data.items()
                if isinstance(key, str) and ':' in key and isinstance(value, dict)}
    except (ValueError, TypeError, AttributeError):
        return {}


class ReferenceLabelsController(QObject):
    completed = Signal(object)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.running = False
        self._pending = False
        self._stopped = Event()
        self._attempted = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start)
        self.completed.connect(self._done)
        owner.candidate_table.referenceRowsChanged.connect(self.request)

    def request(self):
        if self._stopped.is_set():
            return
        self._pending = True
        self._timer.start(150)

    def refresh(self):
        self._attempted.clear()
        self._force_refresh = True
        self.request()

    def cancel(self):
        self._stopped.set()
        self._pending = False
        self._timer.stop()
        # A slow HTTP request must never make closing Finder wait for a worker.

    def _start(self):
        if self.running or self._stopped.is_set():
            return
        self._pending = False
        table = self.owner.candidate_table
        keys = list(dict.fromkeys(table.reference_keys()))
        if not keys:
            return
        pattern = self.owner._active_pattern()
        records = dict(table._reference_labels)
        _merge(records, _project_labels(pattern))
        table.set_reference_labels(records)
        store = self.owner.local_phase_cache.reference_label_store
        pdf = self.owner.match_pdf2
        mp = self.owner.materials_project
        online = bool(mp.api_key) and not offline_mode_enabled()
        force = getattr(self, '_force_refresh', False)
        self._force_refresh = False
        attempted = set(self._attempted)
        project = self.owner.project
        self.running = True

        def work():
            tried = set()
            errors = []
            try:
                cached = store.get_many(keys)
                _merge(records, cached)
                if not self._stopped.is_set():
                    _merge(records, pdf.reference_labels([entry for source, entry in keys if source == 'PDF2']))
                for key in keys:
                    if key[0] == 'RRUFF':
                        records.setdefault(key, {'kind': 'rruff'})
                missing = [entry for source, entry in keys if source == 'MP'
                           and (force or not isinstance(records.get((source, entry), {}).get('theoretical'), bool))
                           and (force or entry not in attempted)] if online else []
                for start in range(0, len(missing), 100):
                    if self._stopped.is_set():
                        break
                    batch = missing[start:start+100]
                    tried.update(batch)
                    try:
                        result = mp.reference_labels(batch)
                        _merge(records, result)
                    except Exception as error:
                        errors.append(str(error))
                        break
                changed = {key: records[key] for key in keys
                           if key in records and records[key] != cached.get(key)}
                if changed and not self._stopped.is_set():
                    store.save_many(changed)
            except Exception as error:
                errors.append(str(error))
            try:
                self.completed.emit((project, keys, records, tried, errors))
            except RuntimeError:
                pass  # The window may already have been destroyed.

        Thread(target=work, name='reference-labels', daemon=True).start()

    def _done(self, result):
        self.running = False
        if self._stopped.is_set():
            return
        project, keys, records, tried, errors = result
        self._attempted.update(tried)
        if self.owner.project is project:
            table = self.owner.candidate_table
            current = set(table.reference_keys())
            table.set_reference_labels({key: value for key, value in records.items() if key in current})
            pattern = self.owner._active_pattern()
            if pattern is not None:
                embedded = _project_labels(pattern)
                _merge(embedded, {key: value for key, value in records.items() if key in current})
                if embedded:
                    pattern.metadata[PROJECT_LABELS] = json.dumps(
                        {':'.join(key): value for key, value in embedded.items()},
                        ensure_ascii=False, separators=(',', ':'))
        if self._pending:
            self._timer.start(150)
