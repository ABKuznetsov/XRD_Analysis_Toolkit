from __future__ import annotations

from PySide6.QtWidgets import QMenuBar, QMessageBox, QWidget


IN_DEVELOPMENT_TEXT = "Function in development"


def _show_in_development(owner: QWidget, feature: str) -> None:
    QMessageBox.information(
        owner,
        "Function in development",
        f"{feature} is in development.",
    )


def _add_owner_action(menu, text: str, owner: QWidget, method_name: str):
    method = getattr(owner, method_name, None)
    action = menu.addAction(text)
    if callable(method):
        action.triggered.connect(lambda _checked=False, method=method: method())
    else:
        action.setEnabled(False)
        action.setToolTip(IN_DEVELOPMENT_TEXT)
        action.setStatusTip(IN_DEVELOPMENT_TEXT)
    return action


def _add_development_action(menu, text: str, owner: QWidget):
    action = menu.addAction(f"{text}  (in development)")
    action.setToolTip(IN_DEVELOPMENT_TEXT)
    action.setStatusTip(IN_DEVELOPMENT_TEXT)
    action.setWhatsThis(IN_DEVELOPMENT_TEXT)
    action.triggered.connect(
        lambda _checked=False, feature=text: _show_in_development(owner, feature)
    )
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
    _add_development_action(edit_menu, "Sample ID...", owner)
    _add_development_action(edit_menu, "Sample date/time...", owner)

    view_menu = menu_bar.addMenu("View")
    _add_owner_action(view_menu, "Plot appearance...", owner, "_show_plot_view_settings_window")
    _add_development_action(view_menu, "Show grid", owner)
    _add_development_action(view_menu, "Autoscale", owner)
    _add_development_action(view_menu, "Reset zoom", owner)

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
    _add_development_action(pattern_menu, "Insert/overlay...", owner)

    automatic_menu = pattern_menu.addMenu("Automatic")
    _add_development_action(automatic_menu, "Increase resolution...", owner)
    _add_development_action(automatic_menu, "Strip K-Alpha2", owner)
    _add_development_action(automatic_menu, "Edit background", owner)
    _add_development_action(automatic_menu, "Recalculate background", owner)
    _add_owner_action(automatic_menu, "Subtract background", owner, "_subtract_active_background_plot")
    _add_owner_action(automatic_menu, "Smooth raw data", owner, "_smooth_active_pattern_plot")
    automatic_menu.addSeparator()
    _add_development_action(automatic_menu, "Correct zero-point error", owner)
    _add_development_action(automatic_menu, "Correct specimen-displacement", owner)

    peak_search_menu = pattern_menu.addMenu("Peak searching")
    _add_development_action(peak_search_menu, "Find peaks", owner)
    _add_development_action(peak_search_menu, "Mark selected peaks", owner)
    _add_development_action(peak_search_menu, "Clear peak list", owner)

    profile_menu = pattern_menu.addMenu("Profile fitting")
    _add_development_action(profile_menu, "Fit selected peaks", owner)
    _add_development_action(profile_menu, "Calculate profile integrals...", owner)

    peaks_menu = menu_bar.addMenu("Peaks")
    _add_development_action(peaks_menu, "Add peak", owner)
    _add_development_action(peaks_menu, "Delete peak", owner)
    _add_development_action(peaks_menu, "Peak list", owner)

    search_menu = menu_bar.addMenu("Search")
    search_menu.addAction("Search by name/formula", owner._search_pdf2_text)
    search_menu.addAction("Search by peaks", owner._search_pdf2_candidates)
    _add_development_action(search_menu, "Search by formula", owner)
    _add_development_action(search_menu, "Search by elements", owner)

    entries_menu = menu_bar.addMenu("Entries")
    entries_menu.addAction("Add selected to working set", owner._add_selected_candidate_to_match_list)
    entries_menu.addAction("Add selected CIF to project", owner._add_selected_cif_to_project)
    _add_development_action(entries_menu, "Open entry card", owner)
    _add_development_action(entries_menu, "Candidate list", owner)

    database_menu = menu_bar.addMenu("Database")
    _add_development_action(database_menu, "Project phases", owner)
    _add_development_action(database_menu, "Materials Project", owner)
    _add_owner_action(database_menu, "User phase library...", owner, "_show_user_phase_library_window")
    _add_owner_action(database_menu, "Database settings", owner, "_show_database_settings_window")

    tools_menu = menu_bar.addMenu("Tools")
    _add_development_action(tools_menu, "Calibrate pattern", owner)
    _add_development_action(tools_menu, "Export candidate list", owner)
    tools_menu.addSeparator()
    _add_owner_action(tools_menu, "Export settings...", owner, "_export_user_settings")
    _add_owner_action(tools_menu, "Import settings...", owner, "_import_user_settings")

    help_menu = menu_bar.addMenu("Help")
    _add_owner_action(help_menu, "Phase Finder help", owner, "_show_quick_help")
    _add_owner_action(help_menu, "Open example project", owner, "_open_example_project")
    _add_development_action(help_menu, "Manual", owner)
    _add_owner_action(help_menu, "About XRD Phase Finder", owner, "_show_about_dialog")

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
