from __future__ import annotations

from PySide6.QtGui import QKeySequence
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
    owner.save_project_action = _add_owner_action(file_menu, "Save project", owner, "_save_project")
    owner.save_project_action.setShortcut(QKeySequence.StandardKey.Save)
    owner.save_project_as_action = _add_owner_action(file_menu, "Save project as...", owner, "_save_project_as")
    owner.save_project_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
    file_menu.addSeparator()
    _add_owner_action(file_menu, "Import XRD / CIF...", owner, "_import_scientific_files")
    file_menu.addSeparator()
    _add_owner_action(file_menu, "Restore original pattern", owner, "_reset_observed_preprocessing")

    edit_menu = menu_bar.addMenu("Edit")
    _add_owner_action(edit_menu, "Sample ID...", owner, "_edit_sample_id")
    _add_owner_action(edit_menu, "Sample date/time...", owner, "_edit_sample_datetime")
    _add_owner_action(edit_menu, "Sample notes...", owner, "_edit_sample_notes")

    view_menu = menu_bar.addMenu("View")
    _add_owner_action(view_menu, "Plot appearance...", owner, "_show_plot_view_settings_window")
    owner.show_grid_action = _add_owner_action(view_menu, "Show grid", owner, "_toggle_menu_grid")
    owner.show_grid_action.setCheckable(True)
    owner.show_grid_action.setChecked(True)
    _add_owner_action(view_menu, "Autoscale", owner, "_reset_match_plot_view")
    _add_owner_action(view_menu, "Reset zoom", owner, "_reset_match_plot_view")

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
    _add_owner_action(pattern_menu, "Insert/overlay...", owner, "_import_scientific_files")
    _add_owner_action(pattern_menu, "Crop XRD...", owner, "_open_crop_from_menu")

    automatic_menu = pattern_menu.addMenu("Automatic")
    _add_development_action(automatic_menu, "Increase resolution...", owner)
    _add_development_action(automatic_menu, "Strip K-Alpha2", owner)
    _add_owner_action(automatic_menu, "Edit background", owner, "_open_background_from_menu")
    _add_owner_action(automatic_menu, "Recalculate background", owner, "_open_background_from_menu")
    _add_owner_action(automatic_menu, "Subtract background", owner, "_open_background_from_menu")
    _add_owner_action(automatic_menu, "Smooth raw data", owner, "_open_smoothing_from_menu")
    automatic_menu.addSeparator()
    _add_owner_action(automatic_menu, "Zero shift...", owner, "_open_zero_shift_from_menu")
    _add_development_action(automatic_menu, "Correct specimen-displacement", owner)

    peak_search_menu = pattern_menu.addMenu("Peak searching")
    owner.find_peaks_action = _add_owner_action(peak_search_menu, "Find peaks", owner, "_find_peaks_from_menu")
    owner.find_peaks_action.setToolTip("Find observed peaks and add them to Peak search selection. Esc cancels detection.")
    _add_owner_action(peak_search_menu, "Mark selected peaks", owner, "_mark_search_peaks_from_menu")
    _add_owner_action(peak_search_menu, "Clear selected search peaks", owner, "_clear_selected_search_peaks_from_menu")

    profile_menu = pattern_menu.addMenu("Profile fitting")
    _add_owner_action(profile_menu, "Fit a peak...", owner, "_inspect_peak_from_menu")
    _add_owner_action(profile_menu, "Peak area...", owner, "_inspect_peak_from_menu")

    peaks_menu = menu_bar.addMenu("Peaks")
    owner.add_peak_action = _add_owner_action(peaks_menu, "Add peak", owner, "_toggle_manual_peak_input")
    owner.add_peak_action.setCheckable(True)
    owner.delete_peak_action = _add_owner_action(peaks_menu, "Delete peak", owner, "_toggle_manual_peak_delete")
    owner.delete_peak_action.setCheckable(True)
    owner.delete_peak_action.setToolTip('Delete a manually entered peak. Measured profile samples are kept.')
    owner.peak_information_action = _add_owner_action(peaks_menu, "Peak information...", owner, "_toggle_peak_information")
    owner.peak_information_action.setCheckable(True)

    search_menu = menu_bar.addMenu("Search")
    search_menu.addAction("Search by name/formula", owner._search_pdf2_text)
    _add_owner_action(search_menu, "Peak search", owner, "_begin_peak_search")
    _add_owner_action(search_menu, "Search by formula", owner, "_search_formula_from_menu")
    _add_owner_action(search_menu, "Search by elements", owner, "_search_elements_from_menu")

    entries_menu = menu_bar.addMenu("Entries")
    entries_menu.addAction("Add selected to working set", owner._add_selected_candidate_to_match_list)
    entries_menu.addAction("Add selected CIF to project", owner._add_selected_cif_to_project)
    _add_owner_action(entries_menu, "Open entry card", owner, "_show_candidate_entry_card")
    _add_owner_action(entries_menu, "Candidate list", owner, "_focus_candidate_list")

    database_menu = menu_bar.addMenu("Database")
    _add_owner_action(database_menu, "Project phases", owner, "_show_project_phases_from_menu")
    _add_owner_action(database_menu, "Materials Project", owner, "_open_materials_project_from_menu")
    _add_owner_action(database_menu, "User phase library...", owner, "_show_user_phase_library_window")
    _add_owner_action(database_menu, "Database settings", owner, "_show_database_settings_window")

    tools_menu = menu_bar.addMenu("Tools")
    _add_owner_action(tools_menu, "Calibrate pattern...", owner, "_open_manual_angle_calibration")
    _add_owner_action(tools_menu, "Export candidate list...", owner, "_export_candidate_list")
    tools_menu.addSeparator()
    _add_owner_action(tools_menu, "Create secure macOS installer...", owner, "_create_secure_macos_installer")
    _add_owner_action(tools_menu, "Create secure Windows installer...", owner, "_create_secure_windows_installer")
    tools_menu.addSeparator()
    network_mode_action = _add_owner_action(tools_menu, "Network mode: Online", owner, "_toggle_network_mode")
    network_mode_action.setCheckable(True)
    owner.network_mode_action = network_mode_action
    if hasattr(owner, "_refresh_network_mode_action"):
        owner._refresh_network_mode_action()
    tools_menu.addSeparator()
    _add_owner_action(tools_menu, "Export settings...", owner, "_export_user_settings")
    _add_owner_action(tools_menu, "Import settings...", owner, "_import_user_settings")

    experimental_menu = menu_bar.addMenu("Experimental")
    experimental_menu.setToolTipsVisible(True)
    for title, description in (
        ("Facet Indexing", "Identify candidate surface orientations from observed reflection series."),
        ("Substrate Peak Suppression", "Mark substrate reflections and reduce their displayed intensity."),
        ("Texture Suppression", "Adjust the displayed intensity of selected harmonic HKL series."),
    ):
        action = experimental_menu.addAction(f"{title}  (planned)")
        action.setEnabled(False)
        action.setToolTip(f"{description}\nPlanned for 1.7.x; not implemented yet.")
        action.setStatusTip("Planned experimental tool; not implemented yet.")

    help_menu = menu_bar.addMenu("Help")
    _add_owner_action(help_menu, "Phase Finder help", owner, "_show_quick_help")
    _add_owner_action(help_menu, "Security and offline use", owner, "_show_security_info_dialog")
    _add_owner_action(help_menu, "Open example project", owner, "_open_example_project")
    _add_owner_action(help_menu, "Manual", owner, "_show_manual_from_menu")
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
        experimental_menu,
        help_menu,
    ]

    return menu_bar
