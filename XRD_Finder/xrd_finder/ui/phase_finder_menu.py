from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenuBar, QMessageBox, QWidget

from xrd_finder.services.cache_paths import default_diagnostic_log_root


def _open_diagnostic_logs(owner: QWidget) -> None:
    log_root = default_diagnostic_log_root()
    log_root.mkdir(parents=True, exist_ok=True)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_root))):
        QMessageBox.warning(
            owner,
            "Diagnostic logs",
            f"Could not open the folder.\n\n{log_root}",
        )


def build_phase_finder_menu_bar(owner: QWidget) -> QMenuBar:
    menu_bar = QMenuBar()

    file_menu = menu_bar.addMenu("File")
    file_menu.addAction("Insert/overlay...")
    file_menu.addAction("Restore original pattern")

    edit_menu = menu_bar.addMenu("Edit")
    edit_menu.addAction("Sample ID...")
    edit_menu.addAction("Sample date/time...")

    view_menu = menu_bar.addMenu("View")
    view_menu.addAction("Show grid")
    view_menu.addAction("Autoscale")
    view_menu.addAction("Reset zoom")

    pattern_menu = menu_bar.addMenu("Pattern")
    pattern_menu.addAction("Insert/overlay...")

    automatic_menu = pattern_menu.addMenu("Automatic")
    automatic_menu.addAction("Increase resolution...")
    automatic_menu.addAction("Strip K-Alpha2")
    automatic_menu.addAction("Edit background")
    automatic_menu.addAction("Recalculate background")
    automatic_menu.addAction("Subtract background")
    automatic_menu.addAction("Smooth raw data")
    automatic_menu.addSeparator()
    automatic_menu.addAction("Correct zero-point error")
    automatic_menu.addAction("Correct specimen-displacement")

    peak_search_menu = pattern_menu.addMenu("Peak searching")
    peak_search_menu.addAction("Find peaks")
    peak_search_menu.addAction("Mark selected peaks")
    peak_search_menu.addAction("Clear peak list")

    profile_menu = pattern_menu.addMenu("Profile fitting")
    profile_menu.addAction("Fit selected peaks")
    profile_menu.addAction("Calculate profile integrals...")

    pattern_menu.addSeparator()
    pattern_menu.addAction("Resolution...")
    pattern_menu.addAction("Wavelength...")

    peaks_menu = menu_bar.addMenu("Peaks")
    peaks_menu.addAction("Add peak")
    peaks_menu.addAction("Delete peak")
    peaks_menu.addAction("Peak list")

    search_menu = menu_bar.addMenu("Search")
    search_menu.addAction("Search by name/formula", owner._search_pdf2_text)
    search_menu.addAction("Search by peaks", owner._search_pdf2_candidates)
    search_menu.addAction("Search by formula")
    search_menu.addAction("Search by elements")

    entries_menu = menu_bar.addMenu("Entries")
    entries_menu.addAction("Add selected to working set", owner._add_selected_candidate_to_match_list)
    entries_menu.addAction("Add selected CIF to project", owner._add_selected_cif_to_project)
    entries_menu.addAction("Open entry card")
    entries_menu.addAction("Candidate list")

    database_menu = menu_bar.addMenu("Database")
    database_menu.addAction("Project phases")
    database_menu.addAction("Materials Project")
    database_menu.addAction("User phase library")
    database_menu.addAction("Database settings", owner._show_database_settings_tab)

    tools_menu = menu_bar.addMenu("Tools")
    tools_menu.addAction("Calibrate pattern")
    tools_menu.addAction("Export candidate list")

    help_menu = menu_bar.addMenu("Help")
    help_menu.addAction("Phase Finder help")
    help_menu.addAction("More XRD tools…", owner._open_toolkit_catalog)
    help_menu.addAction(
        "Open diagnostic logs folder",
        lambda _checked=False: _open_diagnostic_logs(owner),
    )

    return menu_bar
