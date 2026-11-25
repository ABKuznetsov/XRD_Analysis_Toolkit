from __future__ import annotations
from xrd_finder.services.source_registry import is_structure_source

import math
import hashlib
import json
import re
import shutil
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import Qt

from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QTableWidgetItem

from xrd_finder.core.structure import CellParameters
from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.ui.candidate_enrichment import (
    crystal_system_from_cell,
    enrich_candidate_from_pdf2_details,
    enrich_candidate_from_structure,
    format_cell,
    has_complete_cell,
)


class PhaseFinderCandidateInfoActionsMixin:
    def _queue_candidate_row_activation(self, row: int) -> None:
        self._candidate_preview_token = int(getattr(self, '_candidate_preview_token', 0)) + 1
        self._pending_candidate_row = row
        self._candidate_activation_timer.start()

    def _activate_pending_candidate_row(self) -> None:
        if getattr(self, '_preparation_close_confirmed', False):
            return
        # Loading or manual sorting may have moved the selected card since the click.
        row = self.candidate_table.currentRow()
        self._pending_candidate_row = -1
        self._on_candidate_row_activated(row)

    def _on_candidate_row_activated(self, row: int) -> None:
        candidate = self._candidate_row_values(row)
        if not candidate:
            return
        self._enrich_candidate_with_structure_info(candidate)
        if self.match_candidates:
            candidate["Match (%)"] = ""
        self._refresh_candidate_table_row(row, candidate)
        self.candidate_table.set_iic(row, candidate.get("I/Ic*", ""))
        self._update_compound_card(candidate)
        self._preview_candidate_row(row)

    def _update_candidate_gain(self, candidate: dict[str, str]) -> None:
        probability_data = self._probability_observed_data() if hasattr(self, "_probability_observed_data") else None
        if probability_data is None:
            candidate.pop("Gain (%)", None)
            return
        _observed_x, _corrected, observed_records = probability_data
        gain_records = observed_records
        gain_context = None
        if self.match_candidates:
            gain_context = self._candidate_gain_context()
            if gain_context is None:
                candidate.pop("Gain (%)", None)
                return
            gain_context["gain_stage"] = "combined"
            try:
                gain_records = [
                    *self._gain_stage_records(gain_context, "direct", limit=80),
                    *self._gain_stage_records(gain_context, "overlap", limit=80),
                ]
            except Exception:
                gain_records = []
        row = [
            candidate.get("Source", ""),
            candidate.get("Entry", ""),
            candidate.get("Formula", ""),
            candidate.get("Phase", ""),
            candidate.get("Space group", ""),
            candidate.get("Match (%)", ""),
            "",
            candidate.get("I/Ic*", "") or candidate.get("I/Ic", ""),
        ]
        selected_keys = {self._candidate_key(item) for item in (self.match_candidates or [])}
        if self._candidate_key(candidate) in selected_keys:
            gain = 0.0
        elif gain_context is not None:
            gain = self._candidate_row_integral_gain(row, gain_context)
        else:
            gain = (
                self._candidate_row_peak_probability_from_records(
                    row,
                    gain_records,
                    allow_cif_fallback=False,
                    use_cache=True,
                )
                if gain_records
                else 0.0
            )
        if gain_context is not None:
            gain = self._candidate_reportable_gain(candidate, gain, gain_context)
        if gain > 0:
            candidate["Gain (%)"] = ((f"{gain:.3g}%" if gain < .1 else f"{gain:.1f}%")
                                      if gain < 10.0 else f"{gain:.0f}%")
        else:
            candidate.pop("Gain (%)", None)

    def _update_compound_card(self, candidate: dict[str, str] | None) -> None:
        if self.compound_card is not None:
            if candidate is not None:
                self._backfill_candidate_space_group(candidate)
            self._update_compound_card_sample()
            self.compound_card.set_candidate(candidate)

    def _update_compound_card_sample(self) -> None:
        if self.compound_card is not None and hasattr(self.compound_card, "set_sample"):
            self.compound_card.set_sample(
                self._active_pattern(),
                self._compound_card_phase_rows(),
            )
            from PySide6.QtCore import QSignalBlocker
            pattern = self._active_pattern()
            state = self.profile_states.get(pattern.id, {}) if pattern is not None else {}
            with QSignalBlocker(self.compound_card.le_bail_iterations):
                self.compound_card.le_bail_iterations.setValue(int(state.get('le_bail_iterations', 20)))
            running = pattern is not None and getattr(self, '_sample_le_bail_running_pattern', None) == pattern.id
            self.compound_card.cell_fit_button.setText('Cancel Le Bail refinement' if running else 'Refine cell and profile (Le Bail)')
            self.compound_card.le_bail_iterations.setEnabled(not running)
            self.compound_card.reference_reset_button.setEnabled(not running and self.compound_card.fractions_button.isEnabled())
            status = getattr(self.compound_card, 'sample_status', None)
            if status is not None:
                status.setText(getattr(self, '_sample_card_status', ''))

    def _compound_card_phase_rows(self) -> list[list[str]]:
        self._sample_card_status = ''
        pattern = self._active_pattern()
        if pattern is None:
            return []
        candidates = self._profile_candidates_for_pattern(pattern)
        if candidates:
            result, _ = self._finder_result_for_pattern(pattern, candidates, cache_only=True)
            fitted = {item.entry_id: item for item in result.candidates} if result is not None else {}
            overrides = self._sample_cell_structure_overrides(pattern, candidates)
            if result is None:
                self._sample_card_status = 'No current calculated profile. Recalculate phase fractions to update the result.'
            elif result.quantification_error:
                self._sample_card_status = 'Phase fractions unavailable: ' + result.quantification_error
            attempt = self.profile_states.get(pattern.id, {}).get('le_bail_attempt', {})
            if attempt:
                self._sample_card_status = attempt.get('message', '') + '\n' + self._sample_card_status
            rows = []
            for candidate in candidates:
                key = self._candidate_key(candidate)
                self._backfill_candidate_space_group(candidate)
                structure = self.match_structures.get(key) if pattern.id == self.active_profile_pattern_id else None
                if structure is None:
                    structure = self._saved_candidate_structure(candidate, pattern.id)
                item = fitted.get(key)
                cell = getattr(item, 'estimated_cell', None)
                if cell:
                    cell = CellParameters(**{name: cell.get(name) for name in CellParameters.__dataclass_fields__})
                else:
                    cell = getattr(overrides.get(key) or structure, 'cell', None)
                quantity = getattr(item, 'quantity_percent', None)
                rows.append([self._phase_legend_label(candidate), candidate.get('Formula') or getattr(structure, 'formula', ''),
                    candidate.get('Space group', ''), *self._compound_card_cell_values(cell),
                    f'{quantity:.1f}' if quantity is not None and math.isfinite(quantity) else '—',
                    candidate.get('I/Ic*', ''),
                    self._compound_card_number(getattr(item, 'cell_scale', None), precision=5),
                    self._compound_card_number(getattr(item, 'fwhm', None), precision=4),
                    self._compound_card_number(getattr(item, 'profile_eta', None), precision=3)])
            return rows
        linked_phase_ids = getattr(pattern, "linked_phase_ids", [])
        if not isinstance(linked_phase_ids, list) or not linked_phase_ids:
            return []
        phase_by_id = {phase.id: phase for phase in self.project.phases}
        structure_by_id = {structure.id: structure for structure in self.project.structures}
        metric_by_phase_id = self._compound_card_phase_metrics_by_id()
        rows: list[list[str]] = []
        for phase_id in linked_phase_ids:
            phase = phase_by_id.get(phase_id)
            if phase is None:
                continue
            structure = structure_by_id.get(phase.structure_id or "")
            cell = getattr(structure, "cell", None)
            cell_values = self._compound_card_cell_values(cell)
            metrics = metric_by_phase_id.get(phase.id, {})
            rows.append(
                [
                    phase.name or getattr(structure, "name", "") or phase.id,
                    phase.formula or getattr(structure, "formula", ""),
                    phase.space_group or getattr(structure, "space_group", ""),
                    *cell_values,
                    metrics.get("quantity", ""),
                    metrics.get("iic", ""),
                    metrics.get("cell_scale", ""),
                    metrics.get("fwhm", ""),
                    metrics.get("eta", ""),
                ]
            )
        return rows

    def _backfill_candidate_space_group(self, candidate):
        if candidate.get('Space group') not in (None, '', '?', '.'):
            return
        value = candidate.get('Sp. gr.')
        if value in (None, '', '?', '.'):
            key = self._candidate_key(candidate)
            structure = self.match_structures.get(key)
            if structure is None:
                structure = self._saved_candidate_structure(candidate)
            value = getattr(structure, 'space_group', '') or getattr(structure, 'space_group_number', '')
        if value:
            candidate['Space group'] = str(value)

    def _sample_cell_structure_overrides(self, pattern, candidates):
        from xrd_finder.finder.cell_parameter_estimator import FastCellParameterEstimator
        from xrd_finder.io.finder_result_cache import cif_content_signature
        saved = self.profile_states.get(pattern.id, {}).get('sample_cell_overrides', {})
        overrides = {}
        for candidate in candidates:
            key = self._candidate_key(candidate)
            record = saved.get(key)
            if not isinstance(record, dict):
                continue
            path = self._candidate_local_cif_path(candidate)
            if not record.get('cif_sha256') or record['cif_sha256'] != cif_content_signature(path):
                continue
            try:
                cell = CellParameters(**record['cell'])
            except (KeyError, TypeError):
                continue
            if not FastCellParameterEstimator._valid_cell(cell):
                continue
            source = self.match_structures.get(key) if pattern.id == self.active_profile_pattern_id else None
            if source is None:
                source = self._saved_candidate_structure(candidate, pattern.id)
            if source is None and path is not None:
                try:
                    _phase, source = create_phase_from_cif(path)
                except Exception:
                    continue
            if source is not None:
                overrides[key] = deepcopy(source)
                overrides[key].cell = cell
        return overrides

    def _fit_accepted_sample_cells(self, pattern, candidates, *, show_messages, recalculate, latest_only):
        from xrd_finder.io.finder_result_cache import cif_content_signature
        result, _ = self._finder_result_for_pattern(pattern, candidates, cache_only=True)
        if result is None or result.position_refinement.get('requires_confirmation') or result.position_refinement.get('position_rejected'):
            if show_messages:
                QMessageBox.information(self, 'Cell fit', 'Calculate and accept the current phase alignment before fitting the unit cell.')
            return False
        chosen = candidates[-1:] if latest_only else candidates
        overrides = self._sample_cell_structure_overrides(pattern, chosen)
        phase_structures = []
        for candidate in chosen:
            key = self._candidate_key(candidate)
            structure = overrides.get(key) or self.match_structures.get(key) or self._saved_candidate_structure(candidate, pattern.id)
            if structure is None:
                path = self._candidate_local_cif_path(candidate)
                if path is not None:
                    try:
                        _phase, structure = create_phase_from_cif(path)
                        self.match_structures[key] = structure
                    except Exception:
                        pass
            if structure is not None:
                phase_structures.append((key, self._phase_legend_label(candidate), deepcopy(structure)))
        if not phase_structures:
            if show_messages:
                QMessageBox.information(self, 'Cell fit', 'The accepted phases have no local CIF structures for indexed-cell refinement.')
            return False
        wavelength = self._active_wavelength()
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            matches = self._active_indexed_peak_matches(pattern, phase_structures, wavelength=wavelength, finder_result=result)
            results = self.refinement_service.fit_indexed_cells(phase_structures, wavelength=wavelength, indexed_peak_matches=matches)
        except Exception as exc:
            if show_messages:
                QMessageBox.warning(self, 'Cell fit', str(exc))
            return False
        finally:
            self.unsetCursor()
        successful = [item for item in results if item.success]
        if successful:
            saved = self.profile_states.setdefault(pattern.id, {}).setdefault('sample_cell_overrides', {})
            candidate_by_key = {self._candidate_key(candidate): candidate for candidate in candidates}
            for item in successful:
                path = self._candidate_local_cif_path(candidate_by_key[item.phase_id])
                saved[item.phase_id] = dict(cell=asdict(item.refined_cell), matched_peaks=item.matched_peaks,
                    rms_delta_two_theta=item.rms_delta_two_theta, cif_sha256=cif_content_signature(path))
                self.project.refinements.append(dict(method='indexed_cell', pattern_id=pattern.id,
                    candidate_key=item.phase_id, phase_name=item.phase_name, matched_peaks=item.matched_peaks,
                    rms_delta_two_theta=item.rms_delta_two_theta, cell=asdict(item.refined_cell)))
            self._save_active_profile_state()
            self._invalidate_match_profile_cache(pattern.id)
            self.project.touch()
            self.project_changed.emit()
            if recalculate:
                self._recalculate_match_profile(auto_zoom=False, active_only=True)
            self._update_compound_card_sample()
        if show_messages:
            summary = [f'{item.phase_name}: {item.matched_peaks} indexed peaks, RMS {item.rms_delta_two_theta:.4g} deg\n'
                       f'{self._cell_change_text(item.initial_cell, item.refined_cell)}' if item.success
                       else f'{item.phase_name}: {item.message or "not enough independent indexed peaks"}' for item in results]
            QMessageBox.information(self, 'Cell fit', '\n'.join(summary[:8]))
        return bool(successful)

    def _recalculate_sample_fractions(self):
        pattern = self._active_pattern()
        candidates = self._profile_candidates_for_pattern(pattern) if pattern is not None else []
        if not candidates:
            return
        if self._le_bail_enabled_for_pattern(pattern):
            result, _ = self._finder_result_for_pattern(pattern, candidates, cache_only=True)
            if result is None or not self._adopt_sample_le_bail_cells(pattern, candidates, result):
                QMessageBox.information(self, 'Phase fractions', 'Complete a valid cell refinement before calculating separate structural phase fractions.')
                return
            self._set_pattern_le_bail(pattern, False)
        self._save_active_profile_state()
        self._invalidate_match_profile_cache(pattern.id)
        self._recalculate_match_profile(auto_zoom=False, active_only=True)

    def _compound_card_cell_values(self, cell) -> list[str]:
        return [
            self._compound_card_number(getattr(cell, "a", None), precision=8),
            self._compound_card_number(getattr(cell, "b", None), precision=8),
            self._compound_card_number(getattr(cell, "c", None), precision=8),
            self._compound_card_number(getattr(cell, "alpha", None), precision=6),
            self._compound_card_number(getattr(cell, "beta", None), precision=6),
            self._compound_card_number(getattr(cell, "gamma", None), precision=6),
            self._compound_card_number(getattr(cell, "volume", None), precision=8),
        ]

    def _compound_card_number(self, value, *, precision: int) -> str:
        if value is None:
            return ""
        try:
            return f"{float(value):.{precision}g}"
        except Exception:
            return str(value)

    def _compound_card_phase_metrics_by_id(self) -> dict[str, dict[str, str]]:
        metrics: dict[str, dict[str, str]] = {}
        phase_by_source_path = {
            self._compound_card_path_key(phase.source_path): phase.id
            for phase in self.project.phases
            if self._compound_card_path_key(getattr(phase, "source_path", ""))
        }
        phase_by_name_formula = {
            (str(phase.name or "").casefold(), str(phase.formula or "").casefold()): phase.id
            for phase in self.project.phases
        }
        for candidate in self.match_candidates:
            key = self._candidate_key(candidate)
            phase_id = ""
            if self._candidate_source(candidate) == "USER" and candidate.get("Entry"):
                phase_id = candidate.get("Entry", "")
            if not phase_id:
                structure = self.match_structures.get(key)
                source_path = str(getattr(structure, "source_path", "") or "")
                if source_path:
                    phase_id = phase_by_source_path.get(self._compound_card_path_key(source_path), "")
            if not phase_id:
                phase_id = phase_by_name_formula.get(
                    (
                        self._candidate_phase_name(candidate).casefold(),
                        str(candidate.get("Formula", "") or "").casefold(),
                    ),
                    "",
                )
            if not phase_id:
                continue
            quantity = self.match_quantities.get(key)
            iic = float(self.match_iic.get(key, 0.0) or 0.0) if str(candidate.get("Source", "")).upper()=="PDF2" else 0.0
            cell_scale = float(self.match_cell_scales.get(key, 0.0) or 0.0)
            metrics[phase_id] = {
                "quantity": f"{quantity:.1f}" if quantity is not None else "—",
                "iic": candidate.get("I/Ic*", "") if iic > 0 else "",
                "cell_scale": f"{cell_scale:.5g}" if cell_scale else "",
                "fwhm": self._compound_card_number(getattr(self, "_last_match_profile_fwhm", None), precision=4),
                "eta": self._compound_card_number(getattr(self, "_last_match_profile_eta", None), precision=3),
            }
        return metrics

    def _compound_card_path_key(self, path: str) -> str:
        if not path:
            return ""
        try:
            return str(Path(path).resolve()).lower()
        except Exception:
            return str(path).lower()

    def _enrich_candidate_with_structure_info(self, candidate: dict[str, str]) -> None:
        self._backfill_candidate_space_group(candidate)
        if self._candidate_source(candidate) != "PDF2":
            candidate.pop("I/Ic*", None)
            candidate.pop("I/Ic", None)
        if self._candidate_source(candidate) == "PDF2" and candidate.get("Entry"):
            self._enrich_candidate_with_pdf2_info(candidate)
            return
        if not is_structure_source(self._candidate_source(candidate)) or not candidate.get("Entry"):
            return
        if self._enrich_candidate_from_local_cache(candidate):
            return
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if (
            source != "USER"
            and entry_id
            and self.local_phase_cache.cif_path(source, entry_id) is not None
            and getattr(self, "_candidate_preparation_is_busy", lambda: False)()
        ):
            # The CIF exists because the preparation worker is indexing it.  Do
            # not parse or calculate it again synchronously from a table click.
            return
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
        except Exception:
            return
        cached_rows = self._cached_diffraction_rows_for_candidate(candidate)
        enrich_candidate_from_structure(
            candidate,
            structure,
            self.candidate_search_service.display_formula,
            lambda item: cached_rows or self._diffraction_rows_for_structure(item),
        )
        if not self.match_candidates:
            probability = self._structure_peak_probability(structure)
            if probability > 0:
                candidate["Match (%)"] = f"{probability:.0f}%"

    def _enrich_candidate_from_local_cache(self, candidate: dict[str, str]) -> bool:
        if self._candidate_embedded_cif_path(candidate) is not None:
            return False
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        entry = self.local_phase_cache.get(source, entry_id) if source and entry_id else None
        if entry is None:
            return False
        has_derived_data = bool(
            entry.peaks_json
            or entry.atoms_json
            or entry.iic
            or all(value is not None for value in (entry.a, entry.b, entry.c, entry.alpha, entry.beta, entry.gamma))
        )
        if not has_derived_data:
            return False
        if entry.name or source == 'MP' and entry.formula:
            candidate["Phase"] = self.candidate_search_service.phase_display_name(source, entry.formula, entry.name)
        if entry.formula:
            candidate["Formula"] = self.candidate_search_service.display_formula(entry.formula)
        if entry.spacegroup:
            candidate["Space group"] = entry.spacegroup
        candidate["I/Ic*"] = self.candidate_search_service.display_iic(entry.iic, entry.derived_version, entry.iic_method)
        candidate["_IicMethod"] = entry.iic_method
        cell = CellParameters(
            a=entry.a,
            b=entry.b,
            c=entry.c,
            alpha=entry.alpha,
            beta=entry.beta,
            gamma=entry.gamma,
            volume=entry.volume,
        )
        if has_complete_cell(cell):
            candidate["Cell"] = format_cell(cell)
            candidate["Crystal system"] = crystal_system_from_cell(cell)
        atom_rows = self._cached_atom_rows(entry.atoms_json)
        if atom_rows:
            candidate["_AtomRows"] = atom_rows
            atom_lines = []
            for atom in atom_rows[:48]:
                occupancy = f", occ={atom[5]}" if len(atom) > 5 and atom[5] else ""
                atom_lines.append(f"{atom[0]} {atom[1]} ({atom[2]}, {atom[3]}, {atom[4]}{occupancy})")
            suffix = "" if len(atom_rows) <= 48 else f"\n... +{len(atom_rows) - 48} atoms"
            candidate["Atoms"] = "\n".join(atom_lines) + suffix
        diffraction_rows = self._cached_diffraction_rows_for_candidate(candidate, entry=entry)
        if diffraction_rows:
            candidate["_DiffractionRows"] = diffraction_rows
        if entry.source_text and not candidate.get("Notes"):
            candidate["Notes"] = entry.source_text
        if not self.match_candidates:
            probability = self._candidate_peak_probability_from_cache(candidate)
            if probability > 0:
                candidate["Match (%)"] = f"{probability:.0f}%"
        return True

    def _apply_cached_iic(self, candidate, entry=None, *, lookup_cache: bool = True) -> bool:
        if candidate.get("_IicProvenance") == "reference":
            return False
        if entry is None and lookup_cache:
            key = self._candidate_source(candidate), candidate.get("Entry", "")
            entry = self.local_phase_cache.iic_entries((key,)).get(key)
        if entry is None:
            # A portable project can retain a current, traceable snapshot even
            # when its original database card is not present on this computer.
            method = candidate.get("_IicMethod", "")
            if self.local_phase_cache.calculated_iic.current(method):
                record = json.loads(method)
                text = self.candidate_search_service.display_iic(record.get("value"), method=method)
            else:
                text, method = "", ""
        else:
            method = entry.iic_method
            text = self.candidate_search_service.display_iic(entry.iic, entry.derived_version, method)
        embedded = self._candidate_embedded_cif_path(candidate)
        if embedded is not None and text:
            try:
                same_structure = (json.loads(method).get("structure") ==
                                  hashlib.sha256(embedded.read_bytes()).hexdigest())
            except (OSError, ValueError):
                same_structure = False
            if not same_structure:
                text, method = "", ""
        changed = candidate.get("I/Ic*", "") != text or candidate.get("_IicMethod", "") != method
        candidate["I/Ic*"] = text
        candidate["_IicMethod"] = method
        self.match_iic[self._candidate_key(candidate)] = float(text[1:]) if text.startswith("~") else 0.
        return changed

    def _cached_atom_rows(self, atoms_json: str) -> list[list[str]]:
        if not atoms_json:
            return []
        try:
            atoms = json.loads(atoms_json)
        except Exception:
            return []
        rows = []
        for atom in atoms[:96]:
            try:
                b_value = atom.get("biso")
                if b_value is None:
                    b_value = atom.get("uiso")
                rows.append(
                    [
                        str(atom.get("label") or atom.get("element") or ""),
                        str(atom.get("element") or ""),
                        self._format_cached_number(atom.get("x")),
                        self._format_cached_number(atom.get("y")),
                        self._format_cached_number(atom.get("z")),
                        self._format_cached_number(atom.get("occupancy")),
                        self._format_cached_number(b_value),
                    ]
                )
            except Exception:
                continue
        return rows

    def _format_cached_number(self, value) -> str:
        if value is None:
            return ""
        try:
            return f"{float(value):.4g}"
        except Exception:
            return str(value)

    def _candidate_peak_probability_from_cache(self, candidate: dict[str, str]) -> float:
        # A click may arrive while background observation preparation is still
        # running. The table's Match job supplies the value when it completes.
        if getattr(self, '_observed_probability_cache', None) is None:
            return 0.0
        probability_data = self._probability_observed_data()
        if probability_data is None:
            return 0.0
        _observed_x, _corrected, observed_records = probability_data
        if not observed_records:
            return 0.0
        row = [
            candidate.get("Source", ""),
            candidate.get("Entry", ""),
            candidate.get("Formula", ""),
            candidate.get("Phase", ""),
        ]
        return self._candidate_row_peak_probability_from_records(row, observed_records, allow_cif_fallback=False)

    def _crystal_system_from_cell(self, cell: CellParameters) -> str:
        return crystal_system_from_cell(cell)

    def _enrich_candidate_with_pdf2_info(self, candidate: dict[str, str]) -> None:
        details = self.match_pdf2.card_details(candidate.get("Entry", ""))
        peaks = self._pdf2_peaks_for_candidate(candidate)
        enrich_candidate_from_pdf2_details(candidate, details, peaks)


    def _cached_diffraction_rows_for_candidate(self, candidate: dict[str, str], *, entry=None) -> list[list[str]]:
        if self._candidate_embedded_cif_path(candidate) is not None:
            return []
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if not source or not entry_id:
            return []
        try:
            instrument = self._instrument_profile_for_pattern(self._active_pattern())
            rows = self.local_phase_cache.diffraction_rows(source, entry_id,
                wavelength=float(instrument.radiation.components[0].wavelength_angstrom),
                instrument_profile=instrument, entry=entry)
        except Exception:
            return []
        return rows

    def _diffraction_rows_for_structure(self, structure) -> list[list[str]]:
        try:
            peaks = self.calculated_pattern_service.calculate_sticks(
                structure,
                wavelength=self._active_wavelength(),
                two_theta_min=5.0,
                two_theta_max=120.0,
                intensity_min=0.5,
            )
        except Exception:
            return []
        peaks = sorted(peaks, key=lambda peak: peak.two_theta)[:60]
        return [
            [
                f"{peak.d:.4f}",
                f"{peak.two_theta:.3f}",
                f"{peak.intensity:.1f}",
                str(peak.h),
                str(peak.k),
                str(peak.l),
                str(peak.multiplicity),
            ]
            for peak in peaks
        ]

    def _refresh_candidate_table_row(self, row: int, candidate: dict[str, str]) -> None:
        if row < 0 or row >= self.candidate_table.rowCount():
            return
        values = {
            "Formula": candidate.get("Formula", ""),
            "Phase": candidate.get("Phase", ""),
            "Sp. gr.": candidate.get("Space group", ""),
            "Match (%)": "" if self.match_candidates else candidate.get("Match (%)", ""),
            "Gain (%)": candidate.get("Gain (%)", ""),
            "I/Ic": candidate.get("I/Ic*", "") or candidate.get("I/Ic", ""),
        }
        for header, value in values.items():
            column = -1
            for index in range(self.candidate_table.columnCount()):
                header_item = self.candidate_table.horizontalHeaderItem(index)
                if header_item is not None and header_item.text() == header:
                    column = index
                    break
            if column >= 0 and (value or header == "Match (%)"):
                item = self.candidate_table.item(row, column)
                if item is None:
                    self.candidate_table.setItem(row, column, QTableWidgetItem(value))
                else:
                    item.setText(self.candidate_table._score_display_text(column, value))
        self.candidate_table._schedule_user_sort()

    def _show_candidate_context_menu(self, global_point) -> None:
        candidate = self._selected_candidate_row()
        has_structure = self._candidate_has_structure(candidate)
        menu = QMenu(self)
        menu.addAction("Add to working set", self._add_selected_candidate_to_match_list)
        calculate_action = menu.addAction("Calculate pattern overlay", self._calculate_selected_cif_overlay)
        export_action = menu.addAction("Export candidate CIF...", self._export_candidate_table_cif)
        for action in (calculate_action, export_action):
            action.setEnabled(has_structure)
            if not has_structure:
                action.setToolTip("This candidate is a reference pattern; no CIF structure is available.")
        menu.exec(global_point)

    def _export_candidate_table_cif(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Export CIF", "Select a candidate row first.")
            return
        self._export_candidate_cif(candidate)

    def _export_match_table_cif(self) -> None:
        row = self.match_table.currentRow()
        if row < 0 or row >= len(self.match_candidates):
            QMessageBox.information(self, "Export CIF", "Select a phase row first.")
            return
        self._export_candidate_cif(self.match_candidates[row])

    def _export_candidate_cif(self, candidate: dict[str, str]) -> None:
        try:
            source = self._candidate_cif_path(candidate)
        except Exception as exc:
            QMessageBox.warning(self, "Export CIF", str(exc))
            return
        default_name = f"{self._candidate_phase_name(candidate) or candidate.get('Entry') or 'phase'}.cif"
        default_name = re.sub(r"[^A-Za-z0-9._-]+", "_", default_name).strip("_") or "phase.cif"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export CIF",
            str(Path(self._last_directory()) / default_name),
            "CIF structure (*.cif)",
        )
        if not path:
            return
        self._remember_directory(path)
        if not path.lower().endswith(".cif"):
            path += ".cif"
        try:
            shutil.copy2(source, path)
        except Exception as exc:
            QMessageBox.warning(self, "Export CIF", str(exc))
