from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QTableWidgetItem

from xrd_finder.io.cif_loader import create_phase_from_cif


class PhaseFinderCandidateStructureActionsMixin:
    def _phase_legend_label(self, candidate: dict[str, str]) -> str:
        phase = self._candidate_phase_name(candidate) or candidate.get("Entry", "") or "phase"
        source = self._candidate_source(candidate)
        entry = candidate.get("Entry", "")
        if source and entry:
            return f"{phase} {source}#{entry}"
        if entry:
            return f"{phase} #{entry}"
        return phase

    def _selected_candidate_row(self) -> dict[str, str] | None:
        return self.candidate_table.selected_row_values()

    def _candidate_row_values(self, row: int) -> dict[str, str]:
        return self.candidate_table.row_values(row)

    def _candidate_rows(self) -> list[dict[str, str]]:
        rows = []
        for candidate in self.candidate_table.all_row_values():
            if candidate.get("Entry") and self._candidate_source(candidate) in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"}:
                rows.append(candidate)
        return rows

    def _preview_candidate_row(self, row: int) -> None:
        self._candidate_preview_token = int(getattr(self, "_candidate_preview_token", 0)) + 1
        preview_token = self._candidate_preview_token
        if hasattr(self, "_clear_transient_candidate_preview"):
            self._clear_transient_candidate_preview()
        candidate = self._candidate_row_values(row)
        if self._candidate_source(candidate) == "RRUFF" and candidate.get("Entry"):
            self._preview_rruff_reference(candidate, show_errors=False, preview_token=preview_token)
            return
        if self._candidate_source(candidate) == "PDF2" and candidate.get("Entry"):
            self._preview_pdf2_reference(candidate, show_errors=False, preview_token=preview_token)
            return
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"} or not candidate.get("Entry"):
            return
        self._with_candidate_cif_ready(
            candidate,
            "Preview structure",
            lambda ready_candidate: self._calculate_candidate_overlay(ready_candidate, show_errors=False, preview_token=preview_token),
        )

    def _candidate_source(self, candidate: dict[str, str]) -> str:
        return candidate.get("Source", "") or candidate.get("Qual.", "")

    def _candidate_phase_name(self, candidate: dict[str, str]) -> str:
        return candidate.get("Phase", "") or candidate.get("Candidate phase", "")

    def _candidate_cif_path(self, candidate: dict[str, str]) -> Path:
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if source in {"USER", "CCDC"} and entry_id:
            cached_path = self.local_phase_cache.cif_path(source, entry_id)
            if cached_path is not None:
                return cached_path
            if source == "USER":
                project_path = self._candidate_local_cif_path(candidate)
                if project_path is not None:
                    return project_path
            raise ValueError("CIF is not in the user phase library. Save or import it first.")
        if source == "COD" and entry_id:
            cached_path = self.local_phase_cache.cif_path("COD", entry_id)
            if cached_path is not None:
                return cached_path
            entry = self._candidate_to_cod_entry(candidate)
            return self.local_phase_cache.download_cod_entry(entry, self.cod_online)
        if source == "MP" and entry_id:
            cached_path = self.local_phase_cache.cif_path("MP", entry_id)
            if cached_path is not None:
                return cached_path
            target_dir = self.local_phase_cache.root / "materials_project_cif"
            cif_path = self.materials_project.download_cif(entry_id, target_dir)
            self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=entry_id)
            return cif_path
        if source == "AFLOW" and entry_id:
            cached_path = self.local_phase_cache.cif_path("AFLOW", entry_id)
            if cached_path is not None:
                return cached_path
            target_dir = self.local_phase_cache.root / "aflow_cif"
            cif_path = self.aflow.download_cif(entry_id, target_dir, url_hint=candidate.get("Notes", ""))
            self.local_phase_cache.index_cif(cif_path, source="AFLOW", entry_id=entry_id)
            return cif_path
        if source == "OQMD" and entry_id:
            cached_path = self.local_phase_cache.cif_path("OQMD", entry_id)
            if cached_path is not None:
                return cached_path
            target_dir = self.local_phase_cache.root / "oqmd_cif"
            cif_path = self.oqmd.download_cif(entry_id, target_dir, url_hint=candidate.get("Notes", ""), formula_hint=candidate.get("Formula", ""))
            self.local_phase_cache.index_cif(cif_path, source="OQMD", entry_id=entry_id)
            return cif_path
        raise ValueError("Select a saved COD, CCDC, USER, Materials Project, AFLOW, or OQMD row with an entry id.")

    def _candidate_needs_remote_cif(self, candidate: dict[str, str]) -> bool:
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        return bool(entry_id and source in {"COD", "MP", "AFLOW", "OQMD"} and self.local_phase_cache.cif_path(source, entry_id) is None)

    def _with_candidate_cif_ready(self, candidate: dict[str, str], title: str, on_ready) -> None:
        if not self._candidate_needs_remote_cif(candidate):
            on_ready(candidate)
            return
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")

        self._run_background_task(
            title,
            f"Downloading {source} structure {entry_id}...",
            lambda: self.candidate_search_service.download_with_priority(
                (source, entry_id),
                lambda: self._candidate_cif_path(candidate),
            ),
            lambda _path: (self._refresh_database_rows(), on_ready(candidate)),
            lambda message, _details: QMessageBox.warning(self, f"{title} failed", message),
        )

    def _candidate_local_cif_path(self, candidate: dict[str, str]) -> Path | None:
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if not entry_id:
            return None
        if source == "USER":
            cached_path = self.local_phase_cache.cif_path("USER", entry_id)
            if cached_path is not None:
                return cached_path
            phase = next((item for item in self.project.phases if item.id == entry_id), None)
            if phase is not None and phase.source_path:
                path = Path(phase.source_path)
                if path.exists():
                    return path
            for phase in self.project.phases:
                if Path(phase.source_path or "").stem == entry_id:
                    path = Path(phase.source_path)
                    if path.exists():
                        return path
            return None
        if source in {"COD", "CCDC", "MP", "AFLOW", "OQMD"}:
            return self.local_phase_cache.cif_path(source, entry_id)
        return None

    def _add_selected_cif_to_project(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Add CIF", "Select a structure source row first.")
            return

        def add_ready(ready_candidate) -> None:
            try:
                phase, structure = self._add_candidate_to_project(ready_candidate)
                self.tree.set_project(self.project)
                self.project_changed.emit()
                if structure is not None:
                    self._calculate_structure_overlay(structure)
                QMessageBox.information(self, "Add CIF", f"Added {phase.name} to project.")
            except Exception as exc:
                QMessageBox.warning(self, "Add CIF failed", str(exc))

        self._with_candidate_cif_ready(candidate, "Add CIF", add_ready)

    def _calculate_selected_cif_overlay(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Calculate pattern", "Select a structure source row first.")
            return
        if self._candidate_source(candidate) == "RRUFF":
            self._preview_rruff_reference(candidate, show_errors=True)
            return
        if self._candidate_source(candidate) == "PDF2":
            self._preview_pdf2_reference(candidate, show_errors=True)
            return
        self._with_candidate_cif_ready(
            candidate,
            "Calculate pattern",
            lambda ready_candidate: self._calculate_candidate_overlay(ready_candidate, show_errors=True),
        )

    def _download_selected_candidate_to_cache(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Download CIF", "Select a COD or Materials Project row first.")
            return
        source = self._candidate_source(candidate)
        if source in {"USER", "CCDC"}:
            QMessageBox.information(self, "Download CIF", "This CIF is already in the user phase library.")
            return
        if source not in {"COD", "MP"} or not candidate.get("Entry"):
            QMessageBox.information(self, "Download CIF", "Only COD online or Materials Project rows can be saved to the user phase library.")
            return
        saved_id = candidate.get("Entry", "")

        def success(path) -> None:
            row = self.candidate_table.currentRow()
            if row >= 0:
                self.candidate_table.setItem(row, 0, QTableWidgetItem(source))
            self._refresh_database_rows()
            QMessageBox.information(self, "Download CIF", f"Saved {saved_id}:\n{path}")

        self._run_background_task(
            "Download CIF",
            f"Downloading {source} structure {saved_id}...",
            lambda: self.candidate_search_service.download_with_priority(
                (source, saved_id),
                lambda: self._candidate_cif_path(candidate),
            ),
            success,
            lambda message, _details: QMessageBox.warning(self, "Download CIF failed", message),
        )

    def _candidate_to_cod_entry(self, candidate: dict[str, str]) -> object:
        from xrd_finder.services.cod_online_service import CodEntry

        return CodEntry(
            cod_id=candidate.get("Entry", ""),
            formula=candidate.get("Formula", ""),
            name=self._candidate_phase_name(candidate),
            spacegroup="",
            source=candidate.get("Notes", ""),
        )

    def _candidate_key(self, candidate: dict[str, str]) -> str:
        return f"{self._candidate_source(candidate)}:{candidate.get('Entry', '')}"

    def _candidate_has_structure(self, candidate: dict[str, str] | None) -> bool:
        if not candidate:
            return False
        return self._candidate_source(candidate) in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"} and bool(candidate.get("Entry"))

    def _add_candidate_to_project(self, candidate: dict[str, str]):
        cif_path = self._candidate_cif_path(candidate)
        source_path = str(cif_path)
        for phase in self.project.phases:
            if phase.source_path == source_path:
                structure = next((item for item in self.project.structures if item.id == phase.structure_id), None)
                return phase, structure
        phase, structure = create_phase_from_cif(cif_path)
        phase_name = self._candidate_phase_name(candidate)
        if phase_name:
            phase.name = phase_name
            structure.name = phase_name
        if not phase.formula and candidate.get("Formula"):
            phase.formula = candidate["Formula"]
            structure.formula = candidate["Formula"]
        self.project.phases.append(phase)
        self.project.structures.append(structure)
        self.project.touch()
        return phase, structure
