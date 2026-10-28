from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from threading import Event
from time import monotonic

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from xrd_finder.finder.profile_calculator import array_fingerprint
from xrd_finder.services.gain_calculation import GainJobInput, run_gain_job
from xrd_finder.services.isolated_gain import run_gain_job_isolated
from xrd_finder.ui.background_task import BackgroundTaskHandle


def accepted_profile_snapshot(window, pattern) -> dict:
    """Read a coherent cached fit only; never calculate or download on capture."""
    if pattern is None or not window.match_candidates:
        return {}
    cache = window.match_profile_result_cache
    if not cache:
        return {}
    result = cache.get(window._finder_cache_key(pattern, window.match_candidates))
    if result is None or not getattr(result, "sample_broadening_requested", False):
        return {}
    by_key = {candidate.candidate_key: candidate for candidate in result.candidates}
    keys = [window._candidate_key(candidate) for candidate in window.match_candidates]
    if len(by_key) != len(keys) or set(by_key) != set(keys):
        return {}
    snapshot = {
        "accepted_fit_x": np.asarray(result.pattern_x, dtype=float),
        "accepted_fit_target": np.asarray(result.pattern_y, dtype=float)-np.asarray(result.background, dtype=float),
        "accepted_fit_profiles": np.asarray([by_key[key].profile for key in keys], dtype=float),
        "accepted_fit_broadening": [by_key[key].sample_broadening for key in keys],
    }
    mass_profiles = [getattr(by_key[key], 'mass_profile', []) for key in keys]
    if all(len(profile) == len(result.pattern_x) for profile in mass_profiles):
        snapshot['accepted_fit_mass_profiles'] = np.asarray(mass_profiles, dtype=float)
        snapshot['accepted_fit_peak_positions'] = np.asarray(
            [position for key in keys for position in getattr(by_key[key], 'peak_two_theta', [])], dtype=float)
    return snapshot


def capture_gain_job(window) -> tuple[tuple, GainJobInput]:
    pattern = window._active_pattern()
    auto = getattr(window, "_scoring_source", "Auto") == "Auto"
    observed = window._active_observed_data() if auto else window._active_scoring_observed_data()
    background = window._pattern_finder_background_data(pattern)
    rows = window._candidate_state_rows(window.candidate_table.ranking_row_values())
    profile = window._gain_instrument_profile()
    wavelength, doublet = window._gain_radiation()
    inorganic = window.inorganics_checkbox
    organic = window.organics_checkbox
    linked_ids = set(getattr(pattern, "linked_phase_ids", []) or [])
    linked_structures = {phase.structure_id for phase in window.project.phases if phase.id in linked_ids}
    inputs = GainJobInput(
        observed=observed, instrument_profile=profile,
        candidates=window.match_candidates, rows=rows,
        background=background,
        finder_observed=(observed if background is not None and not auto else None),
        scoring_source=getattr(window, "_scoring_source", "Auto"),
        background_removed=window._pattern_scoring_background_removed(pattern),
        preprocess_auto=auto, wavelength=wavelength, include_kalpha2=doublet,
        zero_shifts=window.match_zero_shifts, cell_scales=window.match_cell_scales,
        profile_fwhm=float(getattr(window, "_last_match_profile_fwhm", 0.) or 0.),
        profile_eta=float(getattr(window, "_last_match_profile_eta", 0.) or 0.),
        hidden_matches=window._candidate_hidden_match_by_key,
        cache_root=str(window.local_phase_cache.root),
        pdf2_root=str(window.match_pdf2.root) if window.match_pdf2.is_configured() else "",
        embedded_paths=getattr(window.project.finder_state, "candidate_cif_paths", {}) or {},
        project_phases=window.project.phases,
        project_structures=[structure for structure in window.project.structures
                            if structure.id in linked_structures or structure.phase_id in linked_ids],
        linked_phase_ids=list(getattr(pattern, "linked_phase_ids", []) or []),
        local_sources=window._local_cache_sources(), excluded_elements=window._excluded_elements(),
        required_elements=list(window.selected_element_order), optional_elements=window._optional_elements(),
        restrict_to_selected_elements=False,
        allow_inorganic=True if inorganic is None or organic is None else inorganic.isChecked(),
        allow_organic=True if inorganic is None or organic is None else organic.isChecked(),
        gain_overlap_locked=bool(getattr(window, "_gain_overlap_locked", False)),
        observed_cache_scope=(
            id(window.project), getattr(pattern, "id", None),
            str(getattr(pattern, "source_path", "")),
            bool(getattr(window, "normalize_observed_patterns", False)),
            getattr(pattern, "processed_label", ""),
            bool(getattr(pattern, "processed_background_removed", False)),
            tuple(tuple(bounds) for bounds in getattr(pattern, "crop_ranges", ())),
        ),
        **accepted_profile_snapshot(window, pattern),
    )
    payload = {}
    for name in inputs.__dataclass_fields__:
        if name == "observed_peak_cache":
            continue
        value = getattr(inputs, name)
        if name in {"observed", "finder_observed", "background"}:
            payload[name] = None if value is None else (
                array_fingerprint(value[:, 0]), array_fingerprint(value[:, 1]))
        elif isinstance(value, np.ndarray):
            payload[name] = (value.shape, array_fingerprint(value.ravel()))
        elif name == "instrument_profile":
            payload[name] = value.to_dict()
        elif name in {"project_phases", "project_structures"}:
            payload[name] = [asdict(item) for item in value]
        else:
            payload[name] = value
    # File identities protect local/embedded structures without calculating lines.
    paths = list(inputs.embedded_paths.values())
    paths.extend(phase.source_path for phase in inputs.project_phases if phase.source_path)
    files = []
    for value in sorted(set(str(path) for path in paths)):
        path = Path(value)
        try:
            stat = path.stat()
            files.append((value, stat.st_mtime_ns, stat.st_size))
        except OSError:
            files.append((value, None, None))
    payload["files"] = files
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    identity = (
        id(window.project), getattr(pattern, "id", None), digest,
        getattr(window, "_candidate_search_request_token", 0),
        getattr(window, "_candidate_rank_token", 0),
        getattr(window, "_gain_preparation_revision", 0),
        tuple(sorted(window.element_states.items())),
    )
    inputs.context_key = identity
    return identity, inputs


def gain_job_identity(window) -> tuple:
    return capture_gain_job(window)[0]


def gain_job_watch_key(window) -> tuple:
    """Cancel promptly on common edits; the full identity still guards results.

    Do not read arrays, table rows or fitted profiles here. In-place edits of
    their contents are checked once the worker finishes, before applying it.
    """
    pattern = window._active_pattern()
    containers = tuple(
        (id(value), len(value))
        for value in (
            getattr(pattern, "processed_points", ()),
            getattr(pattern, "estimated_background_points", ()),
            getattr(pattern, "estimated_background_with_halo_points", ()),
        )
    )
    return (
        id(window.project), id(pattern), getattr(pattern, "id", None),
        getattr(pattern, "source_path", ""), getattr(pattern, "wavelength", None),
        getattr(pattern, "processed_label", ""),
        getattr(pattern, "processed_background_removed", False), containers,
        tuple(tuple(bounds) for bounds in getattr(pattern, "crop_ranges", ())),
        tuple(getattr(pattern, "linked_phase_ids", ())),
        getattr(window, "_candidate_search_request_token", 0),
        getattr(window, "_candidate_rank_token", 0),
        getattr(window, "_gain_preparation_revision", 0),
        tuple(window._candidate_key(candidate) for candidate in window.match_candidates),
        tuple(sorted(window.match_zero_shifts.items())),
        tuple(sorted(window.match_cell_scales.items())),
        tuple(sorted(window.element_states.items())), tuple(window.selected_element_order),
        getattr(window, "_scoring_source", "Auto"),
        bool(getattr(window, "normalize_observed_patterns", False)),
        getattr(window, "_last_match_profile_fwhm", 0.),
        getattr(window, "_last_match_profile_eta", 0.),
        bool(getattr(window, "_gain_overlap_locked", False)),
        window.inorganics_checkbox.isChecked() if window.inorganics_checkbox is not None else True,
        window.organics_checkbox.isChecked() if window.organics_checkbox is not None else True,
        json.dumps(getattr(pattern, "instrument_profile", {}), sort_keys=True),
        getattr(window, "_selected_instrument_profile_id", None),
        window.instrument_profile_library.list_profiles(),
    )


class GainJobController(QObject):
    drained = Signal()

    def __init__(self, window, *, task=run_gain_job_isolated, capture=capture_gain_job,
                 identity=gain_job_identity, monitor_identity=None):
        super().__init__(window)
        self.window = window
        self._task = task
        self._capture = capture
        self._identity = identity
        self._monitor_identity = monitor_identity or (
            gain_job_watch_key if identity is gain_job_identity else identity)
        self._handle = None
        self._pending = False
        self._closing = False
        self._serial = 0
        self._input_error = False
        self._cancel = Event()
        self._completed_identity = None
        self._completed_indexed_evidence = {}
        self._observed_peak_cache = None
        self._monitor = QTimer(self)
        self._monitor.setInterval(80)
        self._monitor.timeout.connect(self._check_inputs)

    @property
    def running(self):
        return self._handle is not None or self._pending

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def _enabled(self):
        queue = getattr(self.window, '_accepted_profile_queue', None)
        profile_available = True
        if queue is not None:
            pattern_id = getattr(self.window._active_pattern(), 'id', None)
            profile_available = (not queue.waiting_for(pattern_id) and pattern_id not in queue.failures)
        return (profile_available and getattr(self.window, "_search_mode", "search") != "peaks"
                and not self._closing and not self._input_error and bool(getattr(self.window, "_candidate_gain_auto_enabled", False))
                and bool(self.window.match_candidates))

    def request(self):
        self._input_error = False
        if not self._enabled():
            self.invalidate()
            return
        if (self._handle is not None and not self._cancel.is_set()
                and self._read_identity(monitor=True) == self._watch_key):
            return
        self._serial += 1
        if self._handle is not None:
            self._pending = True
            self._cancel.set()
            return
        self._start()

    def invalidate(self):
        self._serial += 1
        self._cancel.set()
        self._pending = False
        self._completed_identity = None
        self._completed_indexed_evidence = {}

    def cached_indexed_evidence(self, candidate):
        if self._completed_identity is None or not self._enabled():
            return None
        if self._completed_identity != self._read_identity():
            return None
        return self._completed_indexed_evidence.get(self.window._candidate_key(candidate))

    def _start(self):
        self._pending = False
        self._completed_identity = None
        self._completed_indexed_evidence = {}
        try:
            key, inputs = self._capture(self.window)
            watch_key = self._monitor_identity(self.window)
        except Exception as exc:
            self.window._set_candidate_status_state("error")
            self.window._gain_set_status("Gain preparation failed")
            QMessageBox.warning(self.window, "Gain preparation failed", str(exc))
            return
        self._key = key
        self._watch_key = watch_key
        if isinstance(inputs, GainJobInput) and self._observed_peak_cache is not None:
            inputs = replace(inputs, observed_peak_cache=self._observed_peak_cache)
        self._cancel = Event()
        cancel = self._cancel
        serial = self._serial
        task = self._task

        def calculate(progress):
            return task(inputs, progress=progress, cancelled=cancel.is_set)

        handle = BackgroundTaskHandle(calculate, self, accepts_progress=True, operation_name="gain.rank.background")
        self._handle = handle
        self._started_at = monotonic()
        self._progress_text = "Preparing Gain residual..."
        self._elapsed_second = -1
        self.window._candidate_gain_ranking_running = True
        self.window._set_candidate_status_state("busy")
        self.window._set_background_status("Preparing Gain residual...")
        self.window._gain_set_status("Preparing Gain residual...")
        handle.progress.connect(lambda text, value, maximum: self._progress(serial, key, text, value, maximum))
        handle.finished.connect(lambda result: self._finish(serial, key, result))
        handle.failed.connect(lambda message, details: self._fail(serial, key, message, details))
        handle.stopped.connect(self._stopped)
        self._monitor.start()
        handle.start()

    def _valid(self, serial, key, *, verify_inputs=False):
        return (self._enabled() and serial == self._serial and key == self._key
                and self._watch_key == self._read_identity(monitor=True)
                and not self._input_error
                and (not verify_inputs or key == self._read_identity())
                and not self._input_error)

    def _read_identity(self, *, monitor=False):
        try:
            return (self._monitor_identity if monitor else self._identity)(self.window)
        except Exception as exc:
            self._input_error = True
            self.invalidate()
            self._monitor.stop()
            self.window._set_background_status("Gain inputs unavailable")
            self.window._gain_set_status("Gain inputs unavailable")
            self.window._set_candidate_status_state("error")
            QMessageBox.warning(self.window, "Gain inputs unavailable", str(exc))
            return None

    def _check_inputs(self):
        if self._cancel.is_set():
            return
        if not self._enabled():
            self.invalidate()
        elif self._read_identity(monitor=True) != self._watch_key and not self._input_error:
            self._serial += 1
            self._pending = True
            self._cancel.set()
        elif not self._input_error:
            elapsed = int(monotonic() - self._started_at)
            if elapsed != self._elapsed_second:
                self._elapsed_second = elapsed
                text = f"{self._progress_text} | elapsed {elapsed}s"
                self.window._set_background_status(text)
                self.window._gain_set_status(text)

    def _progress(self, serial, key, text, value, maximum):
        if self._valid(serial, key):
            suffix = f" {value}/{maximum}" if maximum else ""
            self._progress_text = text + suffix
            self.window._set_background_status(text + suffix)
            self.window._gain_set_status(text + suffix)

    def _finish(self, serial, key, result):
        self._monitor.stop()
        if not self._valid(serial, key, verify_inputs=True):
            self._pending = self._enabled()
            return
        if result.cancelled:
            return
        self._observed_peak_cache = deepcopy(result.observed_peak_cache)
        window = self.window
        selected = window.candidate_table.selected_row_values() or {}
        selected_key = (selected.get("Source", ""), selected.get("Entry", ""))
        window._candidate_hidden_match_by_key = result.hidden_matches
        window._last_gain_debug = result.debug
        window._set_candidate_rows(result.rows, skip_rank=True)
        window.candidate_table.set_joint_gain_diagnostics(result.evidence.get('_gain_joint_by_key', {}))
        row = window.candidate_table._row_for_candidate_key(selected_key)
        if row >= 0:
            window.candidate_table.setCurrentCell(row, 0)
        window.candidate_table.ensure_visible_selection()
        window._gain_set_status(result.status)
        window._set_background_status(result.status or "Gain complete")
        window._set_candidate_status_state("complete")
        self._completed_indexed_evidence = dict(result.indexed_evidence)
        self._completed_identity = self._read_identity()

    def _fail(self, serial, key, message, details):
        self._monitor.stop()
        if self._valid(serial, key, verify_inputs=True):
            self.window._set_background_status("Gain failed")
            self.window._gain_set_status("Gain failed")
            self.window._set_candidate_status_state("error")
            QMessageBox.warning(self.window, "Gain search failed", message or details)
        else:
            self._pending = self._enabled()

    def _stopped(self):
        self._monitor.stop()
        self._handle = None
        self.window._candidate_gain_ranking_running = False
        if self._closing:
            self._pending = False
            self.drained.emit()
        elif self._pending and self._enabled():
            self._start()
        else:
            self._pending = False
        if hasattr(self.window, '_refresh_candidate_score_labels'):
            self.window._refresh_candidate_score_labels()

    def request_close(self) -> bool:
        self._closing = True
        self._observed_peak_cache = None
        self.invalidate()
        self._monitor.stop()
        return self._handle is None
