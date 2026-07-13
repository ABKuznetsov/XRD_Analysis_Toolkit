from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QTableWidgetItem

from xrd_finder.core.structure import CellParameters
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
        self._pending_candidate_row = row
        self._candidate_activation_timer.start()

    def _activate_pending_candidate_row(self) -> None:
        row = self._pending_candidate_row
        self._pending_candidate_row = -1
        self._on_candidate_row_activated(row)

    def _on_candidate_row_activated(self, row: int) -> None:
        candidate = self._candidate_row_values(row)
        if not candidate:
            return
        self._enrich_candidate_with_structure_info(candidate)
        self._update_candidate_gain(candidate)
        self._refresh_candidate_table_row(row, candidate)
        self.candidate_table.set_iic(row, candidate.get("I/Ic*", ""))
        self._update_compound_card(candidate)
        self._preview_candidate_row(row)

    def _update_candidate_gain(self, candidate: dict[str, str]) -> None:
        if not self.match_candidates:
            candidate.pop("Gain (%)", None)
            return
        context = self._candidate_gain_context()
        if context is None:
            return
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
        gain = self._candidate_row_integral_gain(row, context)
        candidate["Gain (%)"] = f"{gain:.1f}%" if gain < 10.0 else f"{gain:.0f}%"

    def _update_compound_card(self, candidate: dict[str, str] | None) -> None:
        if self.compound_card is not None:
            self._update_compound_card_sample()
            self.compound_card.set_candidate(candidate)

    def _update_compound_card_sample(self) -> None:
        if self.compound_card is not None and hasattr(self.compound_card, "set_sample"):
            self.compound_card.set_sample(
                self._active_pattern(),
                self._compound_card_phase_rows(),
            )

    def _compound_card_phase_rows(self) -> list[list[str]]:
        pattern = self._active_pattern()
        if pattern is None:
            return []
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

    def _compound_card_cell_values(self, cell) -> list[str]:
        return [
            self._compound_card_number(getattr(cell, "a", None), precision=5),
            self._compound_card_number(getattr(cell, "b", None), precision=5),
            self._compound_card_number(getattr(cell, "c", None), precision=5),
            self._compound_card_number(getattr(cell, "alpha", None), precision=4),
            self._compound_card_number(getattr(cell, "beta", None), precision=4),
            self._compound_card_number(getattr(cell, "gamma", None), precision=4),
            self._compound_card_number(getattr(cell, "volume", None), precision=5),
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
            quantity = float(self.match_quantities.get(key, 0.0) or 0.0)
            iic = float(self.match_iic.get(key, 0.0) or 0.0)
            cell_scale = float(self.match_cell_scales.get(key, 0.0) or 0.0)
            metrics[phase_id] = {
                "quantity": f"{quantity:.1f}" if quantity else "",
                "iic": f"{iic:.3g}" if iic > 0 else "",
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
        if self._candidate_source(candidate) == "PDF2" and candidate.get("Entry"):
            self._enrich_candidate_with_pdf2_info(candidate)
            return
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"} or not candidate.get("Entry"):
            return
        if self._enrich_candidate_from_local_cache(candidate):
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
        iic = self._estimate_structure_corundum_iic(structure)
        if iic > 0:
            candidate["I/Ic*"] = f"{iic:.3g}"
        probability = self._structure_peak_probability(structure)
        if probability > 0:
            candidate["Match (%)"] = f"{probability:.0f}%"

    def _enrich_candidate_from_local_cache(self, candidate: dict[str, str]) -> bool:
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
        if entry.name:
            candidate["Phase"] = entry.name
        if entry.formula:
            candidate["Formula"] = self.candidate_search_service.display_formula(entry.formula)
        if entry.spacegroup:
            candidate["Space group"] = entry.spacegroup
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
        diffraction_rows = self._cached_diffraction_rows_for_candidate(candidate)
        if diffraction_rows:
            candidate["_DiffractionRows"] = diffraction_rows
        if entry.source_text and not candidate.get("Notes"):
            candidate["Notes"] = entry.source_text
        if entry.iic and float(entry.iic) > 0:
            candidate["I/Ic*"] = f"{float(entry.iic):.3g}"
        probability = self._candidate_peak_probability_from_cache(candidate)
        if probability > 0:
            candidate["Match (%)"] = f"{probability:.0f}%"
        return True

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

    def _pdf2_peaks_for_candidate(self, candidate: dict[str, str]):
        wavelength = self._active_wavelength()
        peaks = []
        for peak in self.match_pdf2.diffraction_peaks(candidate.get("Entry", "")):
            ratio = wavelength / (2.0 * peak.d_spacing)
            if ratio <= 0.0 or ratio > 1.0:
                continue
            two_theta = math.degrees(2.0 * math.asin(ratio))
            peaks.append(
                SimpleNamespace(
                    two_theta=two_theta,
                    reference_two_theta=two_theta,
                    d_spacing=peak.d_spacing,
                    intensity=peak.intensity,
                    h=peak.h,
                    k=peak.k,
                    l=peak.l,
                )
            )
        return peaks

    def _cached_diffraction_rows_for_candidate(self, candidate: dict[str, str]) -> list[list[str]]:
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if not source or not entry_id:
            return []
        try:
            rows = self.local_phase_cache.diffraction_rows(source, entry_id)
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
        for header, value in {
            "Formula": candidate.get("Formula", ""),
            "Phase": candidate.get("Phase", ""),
            "Sp. gr.": candidate.get("Space group", ""),
            "Match (%)": candidate.get("Match (%)", ""),
            "Gain (%)": candidate.get("Gain (%)", ""),
            "I/Ic": candidate.get("I/Ic*", "") or candidate.get("I/Ic", ""),
        }.items():
            column = -1
            for index in range(self.candidate_table.columnCount()):
                header_item = self.candidate_table.horizontalHeaderItem(index)
                if header_item is not None and header_item.text() == header:
                    column = index
                    break
            if column >= 0 and value:
                self.candidate_table.setItem(row, column, QTableWidgetItem(value))

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
