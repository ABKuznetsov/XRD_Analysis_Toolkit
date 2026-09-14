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


def _add_owner_action(menu, text: str, owner: QWidget, method_name: str):
    method = getattr(owner, method_name, None)
    action = menu.addAction(text)
    if callable(method):
        action.triggered.connect(lambda _checked=False, method=method: method())
    else:
        action.setEnabled(False)
    return action


def build_phase_finder_menu_bar(owner: QWidget) -> QMenuBar:
    menu_bar = QMenuBar(owner)

    file_menu = menu_bar.addMenu("File")
    _add_owner_action(file_menu, "New project", owner, "_new_project")
    _add_owner_action(file_menu, "Open project...", owner, "_load_project")
    _add_owner_action(file_menu, "Save project", owner, "_save_project")
    _add_owner_action(file_menu, "Save project as...", owner, "_save_project_as")
    file_menu.addSeparator()
    _add_owner_action(file_menu, "Import XRD / CIF...", owner, "_import_scientific_files")
    file_menu.addSeparator()
    _add_owner_action(file_menu, "Restore original pattern", owner, "_reset_observed_preprocessing")

    edit_menu = menu_bar.addMenu("Edit")
    edit_menu.addAction("Sample ID...")
    edit_menu.addAction("Sample date/time...")

    view_menu = menu_bar.addMenu("View")
    _add_owner_action(view_menu, "Plot appearance...", owner, "_show_plot_view_settings_window")
    view_menu.addAction("Show grid")
    view_menu.addAction("Autoscale")
    view_menu.addAction("Reset zoom")

    instrument_menu = menu_bar.addMenu("Instrument")
    instrument_menu.addAction(
        "Instrument profile...",
        lambda _checked=False: owner._open_instrument_profile_editor(),
    )
    instrument_menu.addAction(
        "Wavelength...",
        lambda _checked=False: owner._open_instrument_profile_editor("radiation"),
    )
    instrument_menu.addAction(
        "Resolution...",
        lambda _checked=False: owner._open_instrument_profile_editor("resolution"),
    )

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
    _add_owner_action(database_menu, "Database settings", owner, "_show_database_settings_window")

    tools_menu = menu_bar.addMenu("Tools")
    tools_menu.addAction("Calibrate pattern")
    tools_menu.addAction("Export candidate list")

    help_menu = menu_bar.addMenu("Help")
    help_menu.addAction("Phase Finder help")
    help_menu.addAction(
        "Open diagnostic logs folder",
        lambda _checked=False: _open_diagnostic_logs(owner),
    )

    # PySide can release Python-created menus before the native menu bar is
    # installed on the window. Keep explicit references for the bar lifetime.
    menu_bar._owned_menus = [
        file_menu,
        edit_menu,
        view_menu,
        pattern_menu,
        instrument_menu,
        automatic_menu,
        peak_search_menu,
        profile_menu,
        peaks_menu,
        search_menu,
        entries_menu,
        database_menu,
        tools_menu,
        help_menu,
    ]

    return menu_bar
