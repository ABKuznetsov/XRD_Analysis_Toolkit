from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.instrument.models import (
    DetectorProfile,
    GeometryProfile,
    InstrumentIdentity,
    InstrumentProfile,
    RadiationComponentProfile,
    RadiationProfile,
    ResolutionProfile,
)
from xrd_finder.instrument.radiation_catalog import (
    available_tube_targets,
    radiation_profile_from_tube,
)


SECTION_INDEX = {
    "identity": 0,
    "radiation": 1,
    "geometry": 2,
    "detector": 3,
    "resolution": 4,
}


def _number(value: float = 0.0, *, minimum: float = -1_000_000.0, maximum: float = 1_000_000.0) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(7)
    control.setValue(float(value))
    return control


class InstrumentProfileEditor(QWidget):
    def __init__(self, profile: InstrumentProfile | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile_id = ""
        self.tabs = QTabWidget()
        self._build_identity_tab()
        self._build_radiation_tab()
        self._build_geometry_tab()
        self._build_detector_tab()
        self._build_resolution_tab()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        self.set_instrument_profile(profile or InstrumentProfile.default_cu_kalpha())

    def _add_form_tab(self, title: str) -> QFormLayout:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.tabs.addTab(page, title)
        return form

    def _build_identity_tab(self) -> None:
        form = self._add_form_tab("Instrument")
        self.profile_name = QLineEdit()
        self.manufacturer = QLineEdit()
        self.instrument_model = QLineEdit()
        self.serial_number = QLineEdit()
        self.laboratory = QLineEdit()
        self.calibration_date = QLineEdit()
        self.calibration_date.setPlaceholderText("YYYY-MM-DD")
        self.comment = QLineEdit()
        form.addRow("Profile name", self.profile_name)
        form.addRow("Manufacturer", self.manufacturer)
        form.addRow("Model", self.instrument_model)
        form.addRow("Serial number", self.serial_number)
        form.addRow("Laboratory", self.laboratory)
        form.addRow("Calibration date", self.calibration_date)
        form.addRow("Comment", self.comment)

    def _build_radiation_tab(self) -> None:
        form = self._add_form_tab("Radiation")
        self.radiation_target = QComboBox()
        self.radiation_target.setEditable(True)
        self.radiation_target.addItems([*available_tube_targets(), "Custom"])
        self.radiation_mode = QComboBox()
        self.radiation_mode.addItem("K-alpha doublet", "kalpha_doublet")
        self.radiation_mode.addItem("K-alpha1 only", "kalpha1_only")
        self.radiation_mode.addItem("Synchrotron / custom monochromatic", "custom_monochromatic")
        self.component_1_label = QLineEdit()
        self.component_1_wavelength = _number(1.54056, minimum=0.01, maximum=10.0)
        self.component_1_weight = _number(2.0, minimum=0.000001, maximum=1000.0)
        self.component_2_label = QLineEdit()
        self.component_2_wavelength = _number(1.54439, minimum=0.01, maximum=10.0)
        self.component_2_weight = _number(1.0, minimum=0.000001, maximum=1000.0)
        self.tube_voltage = _number(0.0, minimum=0.0, maximum=1000.0)
        self.tube_voltage.setSpecialValueText("Not set")
        self.tube_current = _number(0.0, minimum=0.0, maximum=10000.0)
        self.tube_current.setSpecialValueText("Not set")
        self.filter_material = QLineEdit()
        self.monochromator = QLineEdit()
        form.addRow("Tube target", self.radiation_target)
        form.addRow("Radiation mode", self.radiation_mode)
        form.addRow("Component 1", self.component_1_label)
        form.addRow("Wavelength 1 [A]", self.component_1_wavelength)
        form.addRow("Weight 1", self.component_1_weight)
        form.addRow("Component 2", self.component_2_label)
        form.addRow("Wavelength 2 [A]", self.component_2_wavelength)
        form.addRow("Weight 2", self.component_2_weight)
        form.addRow("Tube voltage [kV]", self.tube_voltage)
        form.addRow("Tube current [mA]", self.tube_current)
        form.addRow("Filter", self.filter_material)
        form.addRow("Monochromator", self.monochromator)
        self.radiation_target.currentTextChanged.connect(self._apply_selected_tube_preset)
        self.radiation_mode.currentIndexChanged.connect(self._radiation_mode_changed)

    def _build_geometry_tab(self) -> None:
        form = self._add_form_tab("Geometry")
        self.geometry = QComboBox()
        self.geometry.addItem("Bragg-Brentano", "bragg_brentano")
        self.geometry.addItem("Debye-Scherrer", "debye_scherrer")
        self.geometry.addItem("Parallel beam", "parallel_beam")
        self.geometry.addItem("Custom", "custom")
        self.apply_lp = QCheckBox("Apply Lorentz-polarization correction")
        self.polarization_fraction = _number(0.5, minimum=0.0, maximum=1.0)
        self.goniometer_radius = _number(0.0, minimum=0.0, maximum=10000.0)
        self.goniometer_radius.setSpecialValueText("Not set")
        self.divergence_slit = QLineEdit()
        self.receiving_slit = QLineEdit()
        self.soller_slit = QLineEdit()
        form.addRow("Geometry", self.geometry)
        form.addRow("Corrections", self.apply_lp)
        form.addRow("Polarization fraction", self.polarization_fraction)
        form.addRow("Goniometer radius [mm]", self.goniometer_radius)
        form.addRow("Divergence slit", self.divergence_slit)
        form.addRow("Receiving slit", self.receiving_slit)
        form.addRow("Soller slit", self.soller_slit)

    def _build_detector_tab(self) -> None:
        form = self._add_form_tab("Detector")
        self.detector_manufacturer = QLineEdit()
        self.detector_model = QLineEdit()
        self.detector_type = QLineEdit()
        self.detector_mode = QLineEdit()
        form.addRow("Manufacturer", self.detector_manufacturer)
        form.addRow("Model", self.detector_model)
        form.addRow("Detector type", self.detector_type)
        form.addRow("Operating mode", self.detector_mode)

    def _build_resolution_tab(self) -> None:
        form = self._add_form_tab("Resolution")
        self.resolution_model = QComboBox()
        self.resolution_model.addItem("Constant FWHM", "constant_fwhm")
        self.resolution_model.addItem("TCH pseudo-Voigt", "tch")
        self.constant_fwhm = _number(0.12, minimum=0.000001, maximum=20.0)
        self.tch_u = _number()
        self.tch_v = _number()
        self.tch_w = _number(1.44)
        self.tch_x = _number()
        self.tch_y = _number()
        form.addRow("Profile model", self.resolution_model)
        form.addRow("Constant FWHM [deg]", self.constant_fwhm)
        form.addRow("U", self.tch_u)
        form.addRow("V", self.tch_v)
        form.addRow("W", self.tch_w)
        form.addRow("X", self.tch_x)
        form.addRow("Y", self.tch_y)
        self.resolution_model.currentIndexChanged.connect(self._sync_resolution_fields)

    def set_section(self, section: str) -> None:
        self.tabs.setCurrentIndex(SECTION_INDEX.get(section, 0))

    def set_instrument_profile(self, profile: InstrumentProfile) -> None:
        self._profile_id = profile.profile_id
        identity = profile.identity
        self.profile_name.setText(identity.name)
        self.manufacturer.setText(identity.manufacturer)
        self.instrument_model.setText(identity.model)
        self.serial_number.setText(identity.serial_number)
        self.laboratory.setText(identity.laboratory)
        self.calibration_date.setText(identity.calibration_date)
        self.comment.setText(identity.comment)

        radiation = profile.radiation
        target_signals = self.radiation_target.blockSignals(True)
        mode_signals = self.radiation_mode.blockSignals(True)
        try:
            self.radiation_target.setCurrentText(radiation.target)
            self.radiation_mode.setCurrentIndex(max(0, self.radiation_mode.findData(radiation.mode)))
        finally:
            self.radiation_target.blockSignals(target_signals)
            self.radiation_mode.blockSignals(mode_signals)
        components = radiation.components
        first = components[0]
        second = components[1] if len(components) > 1 else first
        self.component_1_label.setText(first.label)
        self.component_1_wavelength.setValue(first.wavelength_angstrom)
        self.component_1_weight.setValue(first.weight)
        self.component_2_label.setText(second.label if len(components) > 1 else "")
        self.component_2_wavelength.setValue(second.wavelength_angstrom)
        self.component_2_weight.setValue(second.weight)
        self.tube_voltage.setValue(radiation.tube_voltage_kv or 0.0)
        self.tube_current.setValue(radiation.tube_current_ma or 0.0)
        self.filter_material.setText(radiation.filter_material)
        self.monochromator.setText(radiation.monochromator)

        geometry = profile.geometry
        index = self.geometry.findData(geometry.geometry)
        if index < 0:
            self.geometry.addItem(geometry.geometry, geometry.geometry)
            index = self.geometry.count() - 1
        self.geometry.setCurrentIndex(index)
        self.apply_lp.setChecked(geometry.apply_lorentz_polarization)
        self.polarization_fraction.setValue(geometry.polarization_fraction)
        self.goniometer_radius.setValue(geometry.goniometer_radius_mm or 0.0)
        self.divergence_slit.setText(geometry.divergence_slit)
        self.receiving_slit.setText(geometry.receiving_slit)
        self.soller_slit.setText(geometry.soller_slit)

        detector = profile.detector
        self.detector_manufacturer.setText(detector.manufacturer)
        self.detector_model.setText(detector.model)
        self.detector_type.setText(detector.detector_type)
        self.detector_mode.setText(detector.operating_mode)

        resolution = profile.resolution
        self.resolution_model.setCurrentIndex(max(0, self.resolution_model.findData(resolution.model)))
        self.constant_fwhm.setValue(resolution.constant_fwhm_deg)
        self.tch_u.setValue(resolution.u)
        self.tch_v.setValue(resolution.v)
        self.tch_w.setValue(resolution.w)
        self.tch_x.setValue(resolution.x)
        self.tch_y.setValue(resolution.y)
        self._sync_radiation_fields()
        self._sync_resolution_fields()

    def instrument_profile(self) -> InstrumentProfile:
        mode = str(self.radiation_mode.currentData())
        components = [
            RadiationComponentProfile(
                self.component_1_label.text().strip() or "Primary",
                self.component_1_wavelength.value(),
                self.component_1_weight.value(),
            )
        ]
        if mode == "kalpha_doublet":
            components.append(
                RadiationComponentProfile(
                    self.component_2_label.text().strip() or "Secondary",
                    self.component_2_wavelength.value(),
                    self.component_2_weight.value(),
                )
            )
        return InstrumentProfile(
            profile_id=self._profile_id,
            identity=InstrumentIdentity(
                name=self.profile_name.text().strip(),
                manufacturer=self.manufacturer.text().strip(),
                model=self.instrument_model.text().strip(),
                serial_number=self.serial_number.text().strip(),
                laboratory=self.laboratory.text().strip(),
                calibration_date=self.calibration_date.text().strip(),
                comment=self.comment.text().strip(),
            ),
            radiation=RadiationProfile(
                target=self.radiation_target.currentText().strip() or "Custom",
                mode=mode,
                components=tuple(components),
                tube_voltage_kv=self.tube_voltage.value() or None,
                tube_current_ma=self.tube_current.value() or None,
                filter_material=self.filter_material.text().strip(),
                monochromator=self.monochromator.text().strip(),
            ),
            geometry=GeometryProfile(
                geometry=str(self.geometry.currentData()),
                apply_lorentz_polarization=self.apply_lp.isChecked(),
                polarization_fraction=self.polarization_fraction.value(),
                goniometer_radius_mm=self.goniometer_radius.value() or None,
                divergence_slit=self.divergence_slit.text().strip(),
                receiving_slit=self.receiving_slit.text().strip(),
                soller_slit=self.soller_slit.text().strip(),
            ),
            detector=DetectorProfile(
                manufacturer=self.detector_manufacturer.text().strip(),
                model=self.detector_model.text().strip(),
                detector_type=self.detector_type.text().strip(),
                operating_mode=self.detector_mode.text().strip(),
            ),
            resolution=ResolutionProfile(
                model=str(self.resolution_model.currentData()),
                constant_fwhm_deg=self.constant_fwhm.value(),
                u=self.tch_u.value(),
                v=self.tch_v.value(),
                w=self.tch_w.value(),
                x=self.tch_x.value(),
                y=self.tch_y.value(),
            ),
        )

    def _sync_radiation_fields(self) -> None:
        doublet = self.radiation_mode.currentData() == "kalpha_doublet"
        for control in (self.component_2_label, self.component_2_wavelength, self.component_2_weight):
            control.setEnabled(doublet)

    def _apply_selected_tube_preset(self, _text: str) -> None:
        target = self.radiation_target.currentText().strip()
        if target == "Custom":
            mode_signals = self.radiation_mode.blockSignals(True)
            try:
                self.radiation_mode.setCurrentIndex(
                    self.radiation_mode.findData("custom_monochromatic")
                )
            finally:
                self.radiation_mode.blockSignals(mode_signals)
            self._sync_radiation_fields()
            return
        if target not in available_tube_targets():
            return
        mode_signals = self.radiation_mode.blockSignals(True)
        try:
            self.radiation_mode.setCurrentIndex(
                self.radiation_mode.findData("kalpha_doublet")
            )
        finally:
            self.radiation_mode.blockSignals(mode_signals)
        self._fill_tube_components(target)
        self._sync_radiation_fields()

    def _fill_tube_components(self, target: str) -> None:
        preset = radiation_profile_from_tube(target)
        first, second = preset.components
        self.component_1_label.setText(first.label)
        self.component_1_wavelength.setValue(first.wavelength_angstrom)
        self.component_1_weight.setValue(first.weight)
        self.component_2_label.setText(second.label)
        self.component_2_wavelength.setValue(second.wavelength_angstrom)
        self.component_2_weight.setValue(second.weight)

    def _radiation_mode_changed(self, _index: int) -> None:
        if self.radiation_mode.currentData() == "custom_monochromatic":
            target_signals = self.radiation_target.blockSignals(True)
            try:
                self.radiation_target.setCurrentText("Custom")
            finally:
                self.radiation_target.blockSignals(target_signals)
        elif (
            self.radiation_mode.currentData() == "kalpha_doublet"
            and self.radiation_target.currentText().strip() in available_tube_targets()
        ):
            self._fill_tube_components(self.radiation_target.currentText().strip())
        self._sync_radiation_fields()

    def _sync_resolution_fields(self) -> None:
        constant = self.resolution_model.currentData() == "constant_fwhm"
        self.constant_fwhm.setEnabled(constant)
        for control in (self.tch_u, self.tch_v, self.tch_w, self.tch_x, self.tch_y):
            control.setEnabled(not constant)


class InstrumentProfileDialog(QDialog):
    saveAsRequested = Signal(object)
    updateRequested = Signal(object)
    deleteRequested = Signal(str)
    applyActiveRequested = Signal(object)
    applySelectedRequested = Signal(object)

    def __init__(
        self,
        profile: InstrumentProfile,
        *,
        profiles: Iterable[InstrumentProfile] = (),
        packaged_profile_ids: Iterable[str] = (),
        section: str = "identity",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Instrument profile")
        self.setMinimumSize(640, 560)
        self._profiles: dict[str, InstrumentProfile] = {}
        self._packaged_profile_ids = frozenset(packaged_profile_ids)
        self._selected_profile_key = ""
        self.profile_selector = QComboBox()
        self.profile_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.profile_selector.setMinimumContentsLength(28)
        self.new_profile_button = QPushButton("New")
        self.save_profile_button = QPushButton("Save")
        self.delete_button = QPushButton("Delete")
        self.editor = InstrumentProfileEditor(profile)
        self.editor.set_section(section)
        note = QLabel(
            "Laboratory tube spectra and synchrotron radiation are provided by CrIStMa. "
            "The complete instrument profile is stored in the project."
        )
        note.setWordWrap(True)
        apply_active = QPushButton("Apply to active")
        apply_selected = QPushButton("Apply to selected")
        self.save_profile_button.clicked.connect(self._save_selected_profile)
        self.delete_button.clicked.connect(self._delete_selected_profile)
        apply_active.clicked.connect(lambda: self._emit_profile(self.applyActiveRequested))
        apply_selected.clicked.connect(lambda: self._emit_profile(self.applySelectedRequested))
        self.profile_selector.currentIndexChanged.connect(self._select_saved_profile)
        self.new_profile_button.clicked.connect(self._new_profile)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Saved profile"))
        selector_row.addWidget(self.profile_selector, 1)
        selector_row.addWidget(self.new_profile_button)
        selector_row.addWidget(self.save_profile_button)
        selector_row.addWidget(self.delete_button)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(apply_active)
        actions.addWidget(apply_selected)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        close_buttons.clicked.connect(self.close)
        actions.addWidget(close_buttons)
        layout = QVBoxLayout(self)
        layout.addLayout(selector_row)
        layout.addWidget(self.editor, 1)
        layout.addWidget(note)
        layout.addLayout(actions)
        self.set_profiles(profiles, current_profile=profile)

    def set_profiles(
        self,
        profiles: Iterable[InstrumentProfile],
        *,
        current_profile: InstrumentProfile,
    ) -> None:
        saved_profiles = tuple(profiles)
        self._profiles = {profile.profile_id: profile for profile in saved_profiles}
        matching = self._profiles.get(current_profile.profile_id)
        current_key = current_profile.profile_id
        current_label = current_profile.identity.name
        if matching != current_profile:
            current_key = f"__current__:{current_profile.profile_id}"
            current_label = f"Current project profile - {current_profile.identity.name}"
            self._profiles[current_key] = current_profile

        blocked = self.profile_selector.blockSignals(True)
        try:
            self.profile_selector.clear()
            if current_key.startswith("__current__:"):
                self.profile_selector.addItem(current_label, current_key)
            for saved in saved_profiles:
                self.profile_selector.addItem(saved.identity.name, saved.profile_id)
            index = self.profile_selector.findData(current_key)
            self.profile_selector.setCurrentIndex(max(0, index))
        finally:
            self.profile_selector.blockSignals(blocked)
        self._selected_profile_key = current_key
        self.editor.set_instrument_profile(current_profile)
        self._sync_profile_actions()

    def _select_saved_profile(self, index: int) -> None:
        key = str(self.profile_selector.itemData(index) or "")
        profile = self._profiles.get(key)
        if profile is None:
            return
        self._selected_profile_key = key
        self.editor.set_instrument_profile(profile)
        self._sync_profile_actions()

    def _new_profile(self) -> None:
        draft = InstrumentProfile(
            identity=InstrumentIdentity(name="New instrument profile"),
        )
        key = f"__new__:{draft.profile_id}"
        self._profiles[key] = draft
        blocked = self.profile_selector.blockSignals(True)
        try:
            self.profile_selector.insertItem(0, "New profile (unsaved)", key)
            self.profile_selector.setCurrentIndex(0)
        finally:
            self.profile_selector.blockSignals(blocked)
        self._selected_profile_key = key
        self.editor.set_instrument_profile(draft)
        self._sync_profile_actions()

    def _sync_profile_actions(self) -> None:
        profile_id = self.editor.instrument_profile().profile_id
        is_saved = self._selected_profile_key == profile_id and profile_id in self._profiles
        editable = is_saved and profile_id not in self._packaged_profile_ids
        self.save_profile_button.setEnabled(True)
        self.delete_button.setEnabled(editable)

    def _save_selected_profile(self) -> None:
        profile_id = self.editor._profile_id
        saved_user_profile = (
            self._selected_profile_key == profile_id
            and profile_id in self._profiles
            and profile_id not in self._packaged_profile_ids
        )
        signal = self.updateRequested if saved_user_profile else self.saveAsRequested
        self._emit_profile(signal)

    def _delete_selected_profile(self) -> None:
        if not self.delete_button.isEnabled():
            return
        self.deleteRequested.emit(self.editor.instrument_profile().profile_id)

    def _emit_profile(self, signal: Signal) -> None:
        try:
            profile = self.editor.instrument_profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Instrument profile", str(exc))
            return
        signal.emit(profile)
