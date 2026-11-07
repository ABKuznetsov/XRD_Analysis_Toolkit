from __future__ import annotations

from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog

import shutil
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

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
        self.database_panel.manageUserLibraryRequested.connect(self._show_user_phase_library_window)
        self.database_panel.rebuildUserIndexRequested.connect(self._build_local_phase_cache_index)
        self.database_panel.rebuildLocalPeakIndexRequested.connect(self._rebuild_local_peak_index)
        self.database_panel.auditLocalCompositionRequested.connect(self._audit_local_phase_cache_composition)
        self.database_panel.clearUserLibraryRequested.connect(self._clear_user_phase_library)
        self.database_panel.indexCodFolderRequested.connect(self._index_cod_cif_folder)
        self.database_panel.indexCodZipRequested.connect(self._index_cod_zip_archive)
        self.database_panel.downloadCodArchiveRequested.connect(self._download_cod_archive_from_url)
        self.database_panel.prepareCodInorganicRequested.connect(self._prepare_cod_inorganic_library)
        self.database_panel.prepareCoreMofRequested.connect(self._prepare_core_mof_library)
        self.database_panel.manageConnectionsRequested.connect(self._show_library_connections)
        self.database_panel.readyLibrariesRequested.connect(self._show_ready_libraries)
        self.database_panel.readyLibraryRequested.connect(self._show_ready_library)
        self.database_panel.ccdcAccountRequested.connect(lambda:self._open_ccdc_portal(login=True))
        self.database_panel.ccdcPortalRequested.connect(self._open_ccdc_portal)
        self.database_panel.exportPreparedLibraryRequested.connect(lambda:self._transfer_prepared_library(False))
        self.database_panel.importPreparedLibraryRequested.connect(lambda:self._transfer_prepared_library(True))
        self.database_panel.optimizeLibraryStorageRequested.connect(self._optimize_library_storage)
        self.database_panel.exportCodRequested.connect(lambda: self._export_phase_cache_sources(["COD"], "COD local/bulk", "xrd_cod_cache.json"))
        self.database_panel.importCodRequested.connect(lambda: self._import_phase_cache_sources(["COD"], "COD local/bulk"))
        self.database_panel.clearCodRequested.connect(self._clear_cod_cache)
        self.database_panel.updateRruffRequested.connect(self._update_rruff_database)
        self.database_panel.clearRruffRequested.connect(self._clear_rruff_database)
        self.database_panel.chooseMatchPdf2FolderRequested.connect(self._choose_match_pdf2_folder)
        self.database_panel.refreshMatchPdf2Requested.connect(self._refresh_match_pdf2_database)
        self.database_panel.clearMatchPdf2Requested.connect(self._clear_match_pdf2_database)
        self.database_panel.exportMaterialsProjectRequested.connect(lambda: self._export_phase_cache_sources(["MP"], "Materials Project", "xrd_materials_project_cache.json"))
        self.database_panel.importMaterialsProjectRequested.connect(lambda: self._import_phase_cache_sources(["MP"], "Materials Project"))
        self.database_panel.clearAflowRequested.connect(self._clear_aflow_cache)
        self.database_panel.clearOqmdRequested.connect(self._clear_oqmd_cache)
        self.database_panel.clearMaterialsProjectRequested.connect(self._clear_materials_project_cache)
        self._refresh_database_rows()
        return self.database_panel

    def _show_database_settings_tab(self) -> None:
        self._show_database_settings_window()

    def _show_database_settings_window(self) -> None:
        dialog = getattr(self, "_database_settings_dialog", None)
        if dialog is None:
            dialog = ScreenBoundDialog(self)
            dialog.setWindowTitle("Database settings")
            dialog.setMinimumSize(760, 620)
            dialog.resize(820, 720)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(8, 8, 8, 8)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(self._database_tab())
            layout.addWidget(scroll)
            self._database_settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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
            "CoRE MOF SI": ["CoRE MOF SI", "Ready" if self.local_phase_cache.source_count('COREMOF') else "Not downloaded",
                f"{self.local_phase_cache.source_count('COREMOF'):,} prepared CIF structures · CoRE MOF SI 2024", "https://zenodo.org/records/15055758"],
        }
        for source_name, values in replacements.items():
            self.database_panel.update_row(source_name, values)
        self._refresh_connected_library_rows()
        self._refresh_materials_project_database_row()

    def _refresh_connected_library_rows(self):
        """Read only source counts/settings; never download or recalculate here."""
        if getattr(self, 'database_panel', None) is None:
            return
        from xrd_finder.services.curated_libraries import PRESETS
        from xrd_finder.services.library_connections import load_connections
        from xrd_finder.services.source_registry import saved_custom_sources
        connections = {c.source: c for c in load_connections(self.settings)}
        known = {p.source: (p.name, p.record_url) for p in PRESETS.values()}
        known['LIB_4F4D44420001'] = ('OMDB', 'https://omdb.mathub.io/dataset')
        sources = dict(known)
        sources.update({source: (c.name, '') for source, c in connections.items() if source not in known})
        for source in saved_custom_sources(self.local_phase_cache):
            sources.setdefault(source, (source, ''))
        rows = []
        for source, (name, url) in sources.items():
            count = self.local_phase_cache.source_count(source)
            connection = connections.get(source)
            state = ('Ready' if count else 'Connected' if connection else
                     'CIF import' if name == 'OMDB' else 'Not downloaded')
            enabled = ' · search disabled' if connection and not connection.enabled else ''
            rows.append([name, state,
                f'{count:,} prepared CIF structures{enabled}' if count else
                ('Configured connection' + enabled if connection else
                 'Download on website, then import CIFs' if name == 'OMDB' else 'Download or import CIF archive'), url])
        self.database_panel.sync_connected_rows(rows)

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
            self._refresh_user_phase_library_window()
            QMessageBox.information(self, "Build local index", f"Indexed {count} saved CIF files.\nRun search again to refresh displayed candidates.")

        self._run_background_task(
            "Build local index",
            "Indexing saved CIF files...",
            lambda progress: self.local_phase_cache.build_index(progress=progress,
                cancelled=lambda: getattr(self, "_preparation_close_confirmed", False)),
            success,
            lambda message, _details: QMessageBox.warning(self, "Build local index failed", message),
            with_progress=True,
        )

    def _show_user_phase_library_window(self) -> None:
        dialog = getattr(self, "_user_phase_library_dialog", None)
        if dialog is None:
            dialog = ScreenBoundDialog(self)
            dialog.setWindowTitle("User phase library")
            dialog.setMinimumWidth(480)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(10)
            self._user_phase_library_count_label = QLabel()
            self._user_phase_library_location_label = QLabel()
            self._user_phase_library_location_label.setWordWrap(True)
            layout.addWidget(self._user_phase_library_count_label)
            layout.addWidget(self._user_phase_library_location_label)

            row = QHBoxLayout()
            import_button = QPushButton("Import...")
            export_button = QPushButton("Export...")
            update_button = QPushButton("Update index")
            clear_button = QPushButton("Clear")
            close_button = QPushButton("Close")
            import_button.clicked.connect(self._import_user_phase_library)
            export_button.clicked.connect(self._export_user_phase_library)
            update_button.clicked.connect(self._build_local_phase_cache_index)
            clear_button.clicked.connect(self._clear_user_phase_library)
            close_button.clicked.connect(dialog.close)
            for button in (import_button, export_button, update_button, clear_button):
                row.addWidget(button)
            row.addStretch(1)
            row.addWidget(close_button)
            layout.addLayout(row)
            self._user_phase_library_dialog = dialog
        self._refresh_user_phase_library_window()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _refresh_user_phase_library_window(self) -> None:
        count_label = getattr(self, "_user_phase_library_count_label", None)
        location_label = getattr(self, "_user_phase_library_location_label", None)
        if count_label is not None:
            count = self.local_phase_cache.source_count("USER")
            count_label.setText(f"User phase library contains {count} phase(s).")
        if location_label is not None:
            location_label.setText(f"Storage: {self.local_phase_cache.root / 'user_cif'}")

    def _export_user_phase_library(self) -> None:
        default_path = Path.home() / "Desktop" / "xrd_user_phase_library.json"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export user phase library",
            str(default_path),
            "XRD user phase library (*.json);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        self._export_phase_json_background(path,['USER'],library_name='user_phase_library')

    def _import_user_phase_library(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import user phase library",
            str(Path.home()),
            "XRD user phase library (*.json);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        self._import_phase_json_background(path,['USER'])

    def _export_phase_cache_sources(self, sources: list[str], title: str, default_filename: str) -> None:
        default_path = Path.home() / "Desktop" / default_filename
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            f"Export {title}",
            str(default_path),
            "XRD phase cache (*.json);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        self._export_phase_json_background(path,sources)

    def _export_phase_json_background(self,path,sources, *, library_name='phase_library'):
        from xrd_finder.ui.prepared_library_transfer import PreparedLibraryTransfer
        controller = getattr(self,'_prepared_library_transfer',None)
        if controller is None:
            controller = self._prepared_library_transfer = PreparedLibraryTransfer(self)
        controller.start(False,json_path=path,json_sources=sources,json_library=library_name)

    def _import_phase_cache_sources(self, sources: list[str], title: str) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            f"Import {title}",
            str(Path.home()),
            "XRD phase cache (*.json);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        self._import_phase_json_background(path,sources)

    def _import_phase_json_background(self,path,sources):
        from xrd_finder.ui.prepared_library_transfer import PreparedLibraryTransfer
        controller = getattr(self,'_prepared_library_transfer',None)
        if controller is None:
            controller = self._prepared_library_transfer = PreparedLibraryTransfer(self)
        controller.start(True,json_path=path,json_sources=sources)

    def _audit_local_phase_cache_composition(self) -> None:
        def success(reports):
            needs=sum(report.needs_reindex for report in reports)
            warnings=sum(bool(report.warning) for report in reports)
            unavailable=sum(report.status=='unavailable' for report in reports)
            details='\n'.join(f'{report.source} {report.entry_id}: {report.warning}'
                for report in [item for item in reports if item.warning][:5])
            message=(f'Checked {len(reports)} saved CIFs: {needs} need reindex, '
                     f'{warnings} have warnings, {unavailable} could not be checked.\n'
                     'This check did not change the database.\n'
                     'Use Recalculate CIF patterns to rebuild old records, then run search again.')
            if details:
                message+='\n\n'+details
            QMessageBox.information(self,'CIF composition check',message)
        self._run_background_task('CIF composition check','Checking saved CIF compositions...',
            lambda progress:self.local_phase_cache.audit_compositions(progress=progress),success,
            lambda message,details:QMessageBox.warning(self,'CIF composition check failed',message or details),
            with_progress=True,show_progress_dialog=True)

    def _rebuild_local_peak_index(self) -> None:
        def success(result) -> None:
            count = int(result or 0)
            self._refresh_database_rows()
            QMessageBox.information(
                self,
                "Recalculate CIF patterns",
                f"Recalculated and indexed {count} saved CIF files.\nRun search again to refresh displayed candidates.",
            )

        self._run_background_task(
            "Recalculate CIF patterns",
            "Recalculating saved CIF patterns with CrIStMa...",
            lambda progress: self.local_phase_cache.build_index(progress=progress, force=True,
                cancelled=lambda: getattr(self, "_preparation_close_confirmed", False)),
            success,
            lambda message, _details: QMessageBox.warning(
                self,
                "Recalculate CIF patterns failed",
                message,
            ),
            with_progress=True,
            show_progress_dialog=True,
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
        self._refresh_user_phase_library_window()
        QMessageBox.information(self, "Clear user phase library", "User phase library cache was cleared.")

    def _index_cod_cif_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select COD CIF folder", str(Path.home()))
        if not folder:
            return

        self._show_cod_local_preparation(folder)

    def _index_cod_zip_archive(self) -> None:
        archive_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select COD ZIP archive",
            str(Path.home()),
            "ZIP archive (*.zip);;All files (*.*)",
        )
        if not archive_path:
            return
        self._show_cod_local_preparation(Path(archive_path), archive=True)

    def _show_cod_local_preparation(self, path, *, archive=False) -> None:
        from xrd_finder.ui.cod_inorganic_dialog import CodInorganicController
        controller = getattr(self, '_cod_inorganic_controller', None)
        if controller is None:
            controller = self._cod_inorganic_controller = CodInorganicController(self)
        controller.show(path, archive=archive)

    def _transfer_prepared_library(self, importing: bool) -> None:
        from xrd_finder.ui.prepared_library_transfer import PreparedLibraryTransfer
        controller = getattr(self,'_prepared_library_transfer',None)
        if controller is None:
            controller = self._prepared_library_transfer = PreparedLibraryTransfer(self)
        controller.start(importing)

    def _optimize_library_storage(self):
        from xrd_finder.ui.library_storage_migration import LibraryStorageMigration
        controller = getattr(self,'_library_storage_migration',None)
        if controller is None:
            controller = self._library_storage_migration = LibraryStorageMigration(self)
        controller.start()

    def _prepare_cod_inorganic_library(self) -> None:
        from xrd_finder.ui.cod_inorganic_dialog import CodInorganicController
        controller = getattr(self, '_cod_inorganic_controller', None)
        if controller is None:
            controller = self._cod_inorganic_controller = CodInorganicController(self)
        controller.show()

    def _prepare_core_mof_library(self, archive_path=None) -> None:
        from xrd_finder.ui.cod_inorganic_dialog import CodInorganicController
        controller = getattr(self, '_cod_inorganic_controller', None)
        if controller is None:
            controller = self._cod_inorganic_controller = CodInorganicController(self)
        controller.show(local_path=archive_path,archive=archive_path is not None,dataset='COREMOF')

    def _show_ready_libraries(self) -> None:
        from xrd_finder.ui.ready_libraries import ReadyLibrariesDialog
        dialog=getattr(self,'_ready_libraries_dialog',None)
        if dialog is None:
            dialog=self._ready_libraries_dialog=ReadyLibrariesDialog(self)
        dialog.show();dialog.raise_();dialog.activateWindow()

    def _show_ready_library(self, key):
        self._show_ready_libraries()
        dialog = self._ready_libraries_dialog
        index = dialog.source.findData(key)
        if index >= 0:
            dialog.source.setCurrentIndex(index)

    def _show_library_connections(self) -> None:
        from xrd_finder.ui.library_connections import LibraryConnectionsDialog
        dialog = getattr(self, '_library_connections_dialog', None)
        if dialog is None:
            dialog = self._library_connections_dialog = LibraryConnectionsDialog(self)
        else:
            dialog.refresh()
        dialog.show();dialog.raise_();dialog.activateWindow()

    def _refresh_custom_source_names(self):
        from xrd_finder.services.library_connections import load_connections
        table = getattr(self, 'candidate_table', None)
        if table is not None:
            table.set_source_names({c.source:c.name for c in load_connections(self.settings)})
        self._refresh_connected_library_rows()

    def _prepare_library_connection(self, connection):
        from xrd_finder.ui.cod_inorganic_dialog import CodInorganicController
        controller = getattr(self, '_cod_inorganic_controller', None)
        if controller is None:
            controller = self._cod_inorganic_controller = CodInorganicController(self)
        controller.show(connection=connection)

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
