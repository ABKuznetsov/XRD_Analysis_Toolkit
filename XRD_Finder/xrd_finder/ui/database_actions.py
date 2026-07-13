from __future__ import annotations

import shutil
import threading
from pathlib import Path
from zipfile import ZipFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from xrd_finder.services.materials_project_service import MaterialsProjectService
from xrd_finder.services.network import open_url
from xrd_finder.services.rruff_service import RRUFF_POWDER_XY_PROCESSED_URL
from xrd_finder.ui.database_panel import DatabasePanelWidget
from xrd_finder.ui.database_state import (
    database_rows,
    database_summary_row,
    match_pdf2_status_row,
    source_states,
    user_phase_library_status_row,
)


class PhaseFinderDatabaseActionsMixin:
    def _database_tab(self) -> QWidget:
        mp_status = self.materials_project.status()
        ccdc_status = self.ccdc.status()
        self.database_panel = DatabasePanelWidget(
            database_rows(
                self._user_phase_library_status_row(),
                self.rruff.status_row(),
                self._match_pdf2_status_row(),
                ccdc_status,
                self.aflow.status().label,
                self.oqmd.status().label,
                mp_status,
                self.local_phase_cache.root,
            ),
            source_states(self.settings, self.match_pdf2),
            bool(self.settings.value("materials_project/enabled", False, type=bool)),
            self._materials_project_status_text(),
            self.materials_project.api_key,
        )
        self.database_panel.sourceToggled.connect(self._set_source_enabled)
        self.database_panel.materialsProjectToggled.connect(self._set_materials_project_enabled)
        self.database_panel.saveMaterialsProjectRequested.connect(self._save_materials_project_settings)
        self.database_panel.rebuildUserIndexRequested.connect(self._build_local_phase_cache_index)
        self.database_panel.rebuildLocalPeakIndexRequested.connect(self._rebuild_local_peak_index)
        self.database_panel.clearUserLibraryRequested.connect(self._clear_user_phase_library)
        self.database_panel.indexCodFolderRequested.connect(self._index_cod_cif_folder)
        self.database_panel.indexCodZipRequested.connect(self._index_cod_zip_archive)
        self.database_panel.downloadCodArchiveRequested.connect(self._download_cod_archive_from_url)
        self.database_panel.clearCodRequested.connect(self._clear_cod_cache)
        self.database_panel.updateRruffRequested.connect(self._update_rruff_database)
        self.database_panel.clearRruffRequested.connect(self._clear_rruff_database)
        self.database_panel.chooseMatchPdf2FolderRequested.connect(self._choose_match_pdf2_folder)
        self.database_panel.refreshMatchPdf2Requested.connect(self._refresh_match_pdf2_database)
        self.database_panel.clearMatchPdf2Requested.connect(self._clear_match_pdf2_database)
        self.database_panel.clearAflowRequested.connect(self._clear_aflow_cache)
        self.database_panel.clearOqmdRequested.connect(self._clear_oqmd_cache)
        self.database_panel.clearMaterialsProjectRequested.connect(self._clear_materials_project_cache)
        return self.database_panel

    def _show_database_settings_tab(self) -> None:
        for index in range(self.right_tabs.count()):
            if self.right_tabs.tabText(index) == "Databases":
                self.right_tabs.setCurrentIndex(index)
                return

    def _materials_project_status_text(self) -> str:
        status = self.materials_project.status()
        enabled = self.settings.value("materials_project/enabled", False, type=bool)
        enabled_text = "enabled" if enabled else "disabled"
        return f"Materials Project: {status.label}; search {enabled_text}."

    def _start_match_pdf2_preload(self) -> None:
        if not self.match_pdf2.is_configured():
            return
        if not self._source_enabled("sources/match_pdf2", True):
            return

        def preload() -> None:
            try:
                self.match_pdf2.refresh()
            except Exception:
                pass

        threading.Thread(target=preload, name="xrd-match-pdf2-preload", daemon=True).start()

    def _set_source_enabled(self, setting_key: str, checked: bool) -> None:
        self.settings.setValue(setting_key, checked)
        if self.database_panel is not None:
            self.database_panel.set_source_checked(setting_key, checked)
        if setting_key == "sources/match_pdf2" and checked:
            self._start_match_pdf2_preload()

    def _set_materials_project_enabled(self, checked: bool) -> None:
        self.settings.setValue("materials_project/enabled", checked)
        if self.database_panel is not None:
            self.database_panel.set_materials_project_status(self._materials_project_status_text())

    def _save_materials_project_settings(self) -> None:
        api_key = self.database_panel.api_key() if self.database_panel is not None else ""
        enabled = self.database_panel.materials_project_enabled() if self.database_panel is not None else False
        self.settings.setValue("materials_project/api_key", api_key)
        self.settings.setValue("materials_project/enabled", enabled)
        self.materials_project = MaterialsProjectService(api_key)
        self.candidate_search_service.materials_project = self.materials_project
        if self.database_panel is not None:
            self.database_panel.set_materials_project_status(self._materials_project_status_text())
        self._refresh_materials_project_database_row()

    def _refresh_materials_project_database_row(self) -> None:
        if self.database_panel is None:
            return
        status = self.materials_project.status()
        self.database_panel.update_row(
            "Materials Project",
            [
                "Materials Project",
                "Ready" if status.configured else "Not configured",
                status.label,
                "user API key",
            ],
        )

    def _refresh_database_rows(self) -> None:
        if self.database_panel is None:
            return
        replacements = {
            "User phase library": self._database_summary_row(self._user_phase_library_status_row()),
            "RRUFF powder": self._database_summary_row(self.rruff.status_row()),
            "PDF-2": self._match_pdf2_status_row(),
        }
        for source_name, values in replacements.items():
            self.database_panel.update_row(source_name, values)
        self._refresh_materials_project_database_row()

    def _user_phase_library_status_row(self) -> list[str]:
        return user_phase_library_status_row(self.local_phase_cache.status_row())

    def _database_summary_row(self, row: list[str]) -> list[str]:
        return database_summary_row(row)

    def _match_pdf2_status_row(self) -> list[str]:
        return match_pdf2_status_row(self.match_pdf2)

    def _build_local_phase_cache_index(self) -> None:
        def success(result) -> None:
            count = int(result or 0)
            self._refresh_database_rows()
            QMessageBox.information(self, "Build local index", f"Indexed {count} saved CIF files.")

        self._run_background_task(
            "Build local index",
            "Indexing saved CIF files...",
            self.local_phase_cache.build_index,
            success,
            lambda message, _details: QMessageBox.warning(self, "Build local index failed", message),
        )

    def _rebuild_local_peak_index(self) -> None:
        def success(result) -> None:
            count = int(result or 0)
            self._refresh_database_rows()
            QMessageBox.information(self, "Rebuild peak index", f"Indexed peaks for {count} local phases.")

        self._run_background_task(
            "Rebuild peak index",
            "Rebuilding local SQL peak index...",
            self.local_phase_cache.rebuild_peak_index,
            success,
            lambda message, _details: QMessageBox.warning(self, "Rebuild peak index failed", message),
        )

    def _confirm_clear_database(self, title: str, database_name: str) -> bool:
        response = QMessageBox.warning(
            self,
            title,
            f"This will permanently delete local data for {database_name}.\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

    def _clear_user_phase_library(self) -> None:
        if not self._confirm_clear_database("Clear user phase library", "the user phase library"):
            return
        try:
            self.local_phase_cache.clear_user_library()
            self.settings.setValue("sources/user_library", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/user_library", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear user phase library failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear user phase library", "User phase library cache was cleared.")

    def _index_cod_cif_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select COD CIF folder", str(Path.home()))
        if not folder:
            return

        def success(result) -> None:
            count = int(result or 0)
            self._refresh_database_rows()
            QMessageBox.information(self, "Index COD folder", f"Indexed {count} COD CIF files.")

        self._run_background_task(
            "Index COD folder",
            "Indexing COD CIF folder...",
            lambda: self.local_phase_cache.index_cif_folder(folder, source="COD"),
            success,
            lambda message, _details: QMessageBox.warning(self, "Index COD folder failed", message),
        )

    def _index_cod_zip_archive(self) -> None:
        archive_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select COD ZIP archive",
            str(Path.home()),
            "ZIP archive (*.zip);;All files (*.*)",
        )
        if not archive_path:
            return
        archive = Path(archive_path)
        target_root = self.local_phase_cache.root / "cod_bulk_cif"

        def success(result) -> None:
            count = int(result or 0)
            self._refresh_database_rows()
            QMessageBox.information(self, "Index COD ZIP", f"Indexed {count} COD CIF files.")

        self._run_background_task(
            "Index COD ZIP",
            "Extracting and indexing COD CIF archive...",
            lambda: self._extract_and_index_cif_zip(archive, target_root, source="COD"),
            success,
            lambda message, _details: QMessageBox.warning(self, "Index COD ZIP failed", message),
        )

    def _download_cod_archive_from_url(self) -> None:
        url, ok = QInputDialog.getText(
            self,
            "Download COD archive",
            "COD ZIP archive URL:",
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        output_dir = self.local_phase_cache.root / "downloads"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / Path(url.rstrip("/")).name
        if output_path.suffix.lower() != ".zip":
            output_path = output_path.with_suffix(".zip")

        def task() -> Path:
            with open_url(url, timeout=300) as response:
                with output_path.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            return output_path

        self._run_background_task(
            "Download COD archive",
            "Downloading COD ZIP archive...",
            task,
            lambda path: QMessageBox.information(self, "Download COD archive", f"Saved archive:\n{path}"),
            lambda message, _details: QMessageBox.warning(self, "Download COD archive failed", message),
        )

    def _clear_cod_cache(self) -> None:
        if not self._confirm_clear_database("Clear COD local/bulk", "COD local/bulk"):
            return
        try:
            self.local_phase_cache.clear_cod_cache()
            self.settings.setValue("sources/cod_local", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/cod_local", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear COD local/bulk failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear COD local/bulk", "COD local cache was cleared.")

    def _extract_and_index_cif_zip(self, archive_path: Path, target_root: Path, source: str) -> int:
        target_root.mkdir(parents=True, exist_ok=True)
        count = 0
        with ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                if member_path.suffix.lower() != ".cif":
                    continue
                target_path = target_root / member_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source_handle, target_path.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)
                self.local_phase_cache.index_cif(target_path, source=source, entry_id=target_path.stem)
                count += 1
        return count

    def _update_rruff_database(self) -> None:
        def task() -> int:
            return self.rruff.update_powder_database(RRUFF_POWDER_XY_PROCESSED_URL, remove_archive=True)

        def success(result) -> None:
            count = int(result or 0)
            self.settings.setValue("sources/rruff", True)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/rruff", True)
            self._refresh_database_rows()
            QMessageBox.information(self, "Update RRUFF", f"Updated and indexed {count} RRUFF reference patterns.")

        self._run_background_task(
            "Update RRUFF",
            "Downloading and indexing RRUFF powder patterns...",
            task,
            success,
            lambda message, _details: QMessageBox.warning(self, "Update RRUFF failed", message),
        )

    def _clear_rruff_database(self) -> None:
        if not self._confirm_clear_database("Clear RRUFF", "RRUFF"):
            return
        try:
            self.rruff.clear()
            self.settings.setValue("sources/rruff", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/rruff", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear RRUFF failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear RRUFF", "RRUFF local data was cleared and disabled for search.")

    def _choose_match_pdf2_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select PDF-2 folder",
            str(self.match_pdf2.root if self.match_pdf2.root.exists() else Path.home()),
        )
        if not folder:
            return
        selected_root = Path(folder)
        if not (selected_root / "summary.dat").exists():
            QMessageBox.warning(
                self,
                "Select PDF-2 folder",
                "The selected folder does not contain summary.dat.\n\nSelect a PDF-2 folder that contains summary.dat.",
            )
            return
        self.match_pdf2.set_root(selected_root)
        self.settings.setValue("match_pdf2/root", str(selected_root))
        self.settings.setValue("sources/match_pdf2", True)
        if self.database_panel is not None:
            self.database_panel.set_source_checked("sources/match_pdf2", True)
        self._refresh_database_rows()
        self._start_match_pdf2_preload()
        QMessageBox.information(self, "Select PDF-2 folder", f"PDF-2 library selected:\n{selected_root}")

    def _refresh_match_pdf2_database(self) -> None:
        if not self.match_pdf2.is_configured():
            QMessageBox.warning(
                self,
                "Refresh PDF-2 failed",
                "PDF-2 is not configured. Choose the folder that contains summary.dat first.",
            )
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self.match_pdf2.refresh()
            self.settings.setValue("sources/match_pdf2", True)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/match_pdf2", True)
        except Exception as exc:
            QMessageBox.warning(self, "Refresh PDF-2 failed", str(exc))
            return
        finally:
            self.unsetCursor()
        self._refresh_database_rows()
        QMessageBox.information(self, "Refresh PDF-2", f"Loaded {count} PDF-2 cards.")

    def _clear_match_pdf2_database(self) -> None:
        response = QMessageBox.warning(
            self,
            "Clear PDF-2",
            "This will clear the loaded PDF-2 card cache and disable it for search.\n\n"
            "The installed Match files in Program Files will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self.match_pdf2.clear()
        self.settings.setValue("sources/match_pdf2", False)
        if self.database_panel is not None:
            self.database_panel.set_source_checked("sources/match_pdf2", False)
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear PDF-2", "PDF-2 was cleared from memory and disabled for search.")

    def _clear_aflow_cache(self) -> None:
        if not self._confirm_clear_database("Clear AFLOW", "AFLOW cached structures"):
            return
        try:
            self.local_phase_cache.clear_aflow_cache()
            self.settings.setValue("sources/aflow", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/aflow", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear AFLOW failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear AFLOW", "AFLOW local cache was cleared and disabled for search.")

    def _clear_oqmd_cache(self) -> None:
        if not self._confirm_clear_database("Clear OQMD", "OQMD cached structures"):
            return
        try:
            self.local_phase_cache.clear_oqmd_cache()
            self.settings.setValue("sources/oqmd", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/oqmd", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear OQMD failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear OQMD", "OQMD local cache was cleared and disabled for search.")

    def _clear_materials_project_cache(self) -> None:
        if not self._confirm_clear_database("Clear Materials Project", "Materials Project cached structures"):
            return
        try:
            self.local_phase_cache.clear_materials_project_cache()
            self.settings.setValue("materials_project/enabled", False)
            if self.database_panel is not None:
                self.database_panel.set_materials_project_checked(False)
                self.database_panel.set_materials_project_status(self._materials_project_status_text())
        except Exception as exc:
            QMessageBox.warning(self, "Clear Materials Project failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear Materials Project", "Materials Project local cache was cleared.")
