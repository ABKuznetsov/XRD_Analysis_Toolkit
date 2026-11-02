"""Compact two-click search settings anchored to Identify phases."""
from __future__ import annotations

from dataclasses import replace
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLayout, QToolButton, QVBoxLayout, QWidget,
)

from xrd_finder.instrument.models import InstrumentIdentity, ResolutionProfile
from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.services.search_inventory import SearchInventory, search_inventory
from xrd_finder.services.le_bail import le_bail_available
from xrd_finder.ui.theme import theme_colors


HELP = {
    'available': 'Local structure cards matching the current Elements filters. '
        'If a phase is missing or the count is 0, use Search → Search by formula (formula, name or ID). '
        'Downloaded CIFs are cached for later auto search. External reference-pattern providers are not counted here.',
    'profile': 'Choose a saved instrument profile. The last choice is remembered. '
        'Use Add profile… to create, import or calibrate a profile in Instrument settings.',
    'widths': 'Account for instrument peak broadening using the measurement calibration. '
        'A wrong profile can worsen matching. Off uses basic widths and keeps the measurement radiation and geometry.',
    'lebail': 'After phases are accepted, adjust their cells, peak shapes and reflection intensities '
        'with up to 3 cycles and 2 seconds. Every accepted phase needs a CIF. '
        'This is not a full refinement. Quant is unavailable for an applied Le Bail result. '
        'Phase-wise passes keep other cells/profiles fixed; intensities are always fitted jointly. '
        'A joint pass adjusts all accepted phases. At the time limit the best completed improvement is retained; '
        'otherwise the ordinary structural fit is kept. '
        'Requires CrIStMa 0.1.0b14.',
}


class AutoSearchSetupPopup(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName('autoSearchSetup')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.help_buttons = []
        self._help_popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._help_popup.setObjectName('searchHelpPopup')
        self._help_text = QLabel()
        self._help_text.setWordWrap(True)
        self._help_text.setTextFormat(Qt.TextFormat.PlainText)
        help_layout = QVBoxLayout(self._help_popup)
        help_layout.setContentsMargins(12, 12, 12, 12)
        help_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        help_layout.addWidget(self._help_text)
        self._help_popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._help_popup.setAutoFillBackground(True)
        self._help_popup.setWindowOpacity(1.0)
        self._generation = 0
        self._cancel = Event()
        self._inventory = None
        self._inventory_error = False
        self._pending_start = False
        self._closed = True
        self._placing = False
        self._place_timer = QTimer(self)
        self._place_timer.setSingleShot(True)
        self._place_timer.timeout.connect(self._place)
        self._button = window.finder_top_toolbar.auto_search_button
        self._button_text = self._button.text()
        self._button_tooltip = self._button.toolTip()
        self._button_minimum = self._button.minimumWidth()
        self._build()
        window._system_theme_observer.changed.connect(self._apply_style)
        self._apply_style()

    def _help(self, key):
        button = QToolButton()
        button.setText('?')
        button.setProperty('searchHelp', True)
        button.setAccessibleName('Help: '+key)
        button.setToolTip(HELP[key])
        button.clicked.connect(lambda: self._show_help(button, key))
        self.help_buttons.append(button)
        return button

    def _show_help(self, button, key):
        label = self._help_popup
        self._help_text.setText(HELP[key])
        density = float(getattr(self.window, '_ui_density_factor', 1.))
        screen = button.screen().availableGeometry()
        self._help_text.setFixedWidth(min(round(380*density), screen.width()-16)-24)
        label.ensurePolished()
        label.layout().activate()
        label.adjustSize()
        anchor = button.mapToGlobal(QPoint(0, button.height()+4))
        x = max(screen.left()+8, min(anchor.x(), screen.right()-label.width()-8))
        y = anchor.y()
        if y+label.height() > screen.bottom()-8:
            y = button.mapToGlobal(QPoint(0, 0)).y()-label.height()-4
        label.move(x, max(screen.top()+8, y))
        label.show()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10,8,10,10)
        header = QHBoxLayout()
        title = QLabel('Identify phases')
        title.setProperty('uiRole','sectionTitle')
        header.addWidget(title,1)
        close = QToolButton()
        close.setText('×');close.setToolTip('Close search settings (Esc)')
        close.clicked.connect(self.hide)
        header.addWidget(close);outer.addLayout(header)
        self.body = QWidget()
        self.body.setObjectName('autoSearchSetupBody')
        outer.addWidget(self.body)
        body = QVBoxLayout(self.body)
        body.setContentsMargins(2,0,2,0);body.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel('Local cards available'),1)
        self.available = QLabel('…')
        self.count_labels = {'available':self.available}
        row.addWidget(self.available);row.addWidget(self._help('available'))
        body.addLayout(row)
        self.search_hint = QLabel('! Missing a phase? Use Search → Search by formula. '
            'Downloaded CIFs become available to auto search.')
        self.search_hint.setWordWrap(True); self.search_hint.setProperty('uiRole', 'attention')
        body.addWidget(self.search_hint)
        title = QLabel('Search enhancements')
        title.setProperty('uiRole','sectionTitle');body.addWidget(title)
        row = QHBoxLayout()
        self.profile_enhancement = QCheckBox('Use instrument profile')
        row.addWidget(self.profile_enhancement,1);row.addWidget(self._help('widths'))
        body.addLayout(row)
        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setAccessibleName('Saved instrument profile')
        self.profile_combo.setToolTip(HELP['profile'])
        self.profile_combo.setMinimumContentsLength(12)
        self.profile_combo.setMinimumWidth(0)
        self.profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.profile_combo,1)
        self.add_profile_button = QToolButton()
        self.add_profile_button.setText('Add profile…')
        self.add_profile_button.setToolTip('Open Instrument settings → Resolution to add, import or calibrate an instrument profile.')
        self.add_profile_button.clicked.connect(self._open_profile_settings)
        row.addWidget(self.add_profile_button);row.addWidget(self._help('profile'))
        body.addLayout(row)
        row = QHBoxLayout()
        self.le_bail = QCheckBox('Le Bail')
        self.le_bail.setEnabled(False);self.le_bail.setChecked(False)
        self.le_bail.setToolTip(HELP['lebail'])
        row.addWidget(self.le_bail,1);row.addWidget(self._help('lebail'))
        body.addLayout(row)
        self.le_bail_note = QLabel('! Up to 3 cycles / 2 s; not a full refinement. Quant unavailable when applied.')
        self.le_bail_note.setWordWrap(True); self.le_bail_note.setProperty('uiRole', 'attention')
        body.addWidget(self.le_bail_note)
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.status,1)
        self.retry = QToolButton();self.retry.setText('Retry');self.retry.setToolTip('Retry reading the reference library')
        self.retry.clicked.connect(self._refresh_inventory);self.retry.hide()
        row.addWidget(self.retry);body.addLayout(row)
        hint = QLabel('Click Run search again to start.')
        hint.setProperty('uiRole','muted');hint.setWordWrap(True);body.addWidget(hint)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.profile_enhancement.toggled.connect(self._enhancement_changed)
        self.le_bail.toggled.connect(self._le_bail_changed)

    def _filter_key(self):
        w = self.window
        return (id(w.project),getattr(w._active_pattern(),'id',None),
                tuple(w._local_cache_sources()),tuple(w.selected_element_order),tuple(w._excluded_elements()),
                w.inorganics_checkbox.isChecked(),w.organics_checkbox.isChecked(),
                w._structural_data_enabled(),w._reference_patterns_enabled(),
                w._match_pdf2_enabled(),w._source_enabled('sources/rruff',False))

    def open(self):
        self._closed=False;self._pending_start=False;self._inventory=None;self._inventory_error=False
        self.pattern_id=self.window._active_pattern().id
        self.project_id=id(self.window.project)
        profile=self.window._active_instrument_profile()
        profiles=list(self.window.instrument_profile_library.list_profiles())
        project_only=not any(item.calculation_key()==profile.calculation_key() for item in profiles)
        if project_only:profiles.insert(0,profile)
        preferred=str(self.window.settings.value('auto_search/last_profile_id',''))
        self.profile_combo.blockSignals(True);self.profile_combo.clear()
        selected=next((i for i,item in enumerate(profiles) if item.calculation_key()==profile.calculation_key()),0)
        for index,item in enumerate(profiles):
            name=item.identity.name or item.profile_id
            self.profile_combo.addItem(('Project profile — ' if project_only and index==0 else '')+name,item)
            if preferred and item.profile_id==preferred:selected=index
        self.profile_combo.setCurrentIndex(selected);self.profile_combo.blockSignals(False)
        self.profile_enhancement.blockSignals(True)
        self.profile_enhancement.setChecked(self.window.settings.value('auto_search/use_profile_widths',True,type=bool))
        self.profile_enhancement.blockSignals(False)
        self.profile_combo.setEnabled(self.profile_enhancement.isChecked())
        self.le_bail.blockSignals(True)
        available = le_bail_available()
        self.le_bail.setEnabled(available)
        self.le_bail.setText('Le Bail' if available else 'Le Bail — unavailable')
        state = self.window.profile_states.get(self.pattern_id, {})
        preference = state.get('le_bail_enabled',
            self.window.settings.value('auto_search/le_bail', False, type=bool))
        self.le_bail.setChecked(bool(available and preference))
        self.le_bail.blockSignals(False)
        self._button_minimum=self._button.minimumWidth()
        self._button.setMinimumWidth(max(self._button.width(),self._button_minimum))
        self._button.setText('Run search');self._button.setAccessibleName('Run search');self._button.setChecked(True)
        self._button.setToolTip('Run search with these settings')
        self.show();self.raise_();self._place()
        QApplication.instance().installEventFilter(self)
        self._refresh_inventory()

    def _remember_profile_choice(self):
        profile=self.profile_combo.currentData()
        saved=self.window.instrument_profile_library.get(profile.profile_id)
        key=(profile.profile_id if saved is not None and saved.calculation_key()==profile.calculation_key()
             else 'project:'+profile.calculation_key())
        self.window.settings.setValue('auto_search/last_profile_id',key)

    def _profile_changed(self,*_args):
        self._pending_start=False
        if not self._closed:self._button.setText('Run search')
        if self.profile_combo.currentData() is not None:self._remember_profile_choice()

    def _open_profile_settings(self):
        template = self.profile_combo.currentData()
        self.hide()
        self.window._open_instrument_profile_editor('resolution')
        if template is not None:
            draft = replace(template, profile_id=f'instrument-{uuid4()}',
                identity=InstrumentIdentity(name='New instrument profile'))
            dialog = self.window._instrument_profile_dialog
            dialog._set_new_profile_draft(draft)
            dialog.editor.set_section('resolution')

    def _enhancement_changed(self,checked):
        self._pending_start=False
        if not self._closed:self._button.setText('Run search')
        self.window.settings.setValue('auto_search/use_profile_widths',bool(checked))
        self.profile_combo.setEnabled(bool(checked))

    def _le_bail_changed(self, *_args):
        self._pending_start=False
        if not self._closed:self._button.setText('Run search')

    def effective_profile(self):
        profile=self.profile_combo.currentData()
        return profile if self.profile_enhancement.isChecked() else replace(
            self.window._active_instrument_profile(),resolution=ResolutionProfile())

    def _refresh_inventory(self):
        if self._closed:return
        self._generation+=1;generation=self._generation
        self._cancel.set();cancel=self._cancel=Event()
        self._inventory=None;self._inventory_error=False;self.retry.hide()
        self._inventory_filter_key=self._filter_key()
        w=self.window
        inputs=dict(sources=list(w._local_cache_sources()),required_elements=list(w.selected_element_order),
                    excluded_elements=list(w._excluded_elements()),allow_inorganic=w.inorganics_checkbox.isChecked(),
                    allow_organic=w.organics_checkbox.isChecked(),cancelled=cancel.is_set)
        cache=LocalPhaseCache.read_only(w.local_phase_cache.root)
        self._external_references=bool(w._reference_patterns_enabled() and
            (w._match_pdf2_enabled() or w._source_enabled('sources/rruff',False)))
        self.status.setProperty('uiRole', 'muted'); self.status.setStyleSheet('')
        self.available.setText('…');self.status.setText('Checking references…');self.status.show()
        def current():
            return not self._closed and generation==self._generation and self.project_id==id(w.project)
        def done(inventory):
            if not current():return
            if self._inventory_filter_key!=self._filter_key():self._refresh_inventory();return
            self._inventory=inventory
            available=(inventory.eligible_ready+inventory.eligible_preparation) if w._structural_data_enabled() else 0
            self.available.setText(f'{available:,}')
            self.status.setText('! No matching local references. Check Elements filters.'
                if not (available or self._external_references) else '')
            self.status.setProperty('uiRole', 'attention')
            self.status.setStyleSheet('font-weight:600;')
            self.status.setVisible(bool(self.status.text()))
            self._place_timer.start(0)
            if self._pending_start:self.start_search()
        def failed(message,details):
            if not current():return
            self._pending_start=False;self.available.setText('Unavailable');self.retry.show()
            if not w._structural_data_enabled() and self._external_references:
                self._inventory=SearchInventory();self._inventory_error=False
                self.status.setText('Local count unavailable. Enabled reference patterns can still be searched.')
            else:
                self._inventory_error=True;self.status.setText('Could not check references. Retry or open Manage databases.')
            self.status.setToolTip(message or details);self.status.show();self._button.setText('Run search')
            self._place_timer.start(0)
        w._run_background_task('Search setup','Checking available reference data…',
            lambda:search_inventory(cache,**inputs),done,failed,operation_name='search.setup.inventory')

    def start_search(self):
        if self._closed:return
        w=self.window;pattern=w._active_pattern()
        if pattern is None or pattern.id!=self.pattern_id or id(w.project)!=self.project_id:
            self.hide();return
        if self._inventory_filter_key!=self._filter_key():self._refresh_inventory()
        if self._inventory_error:return
        if self._inventory is None:
            self._pending_start=True;self._button.setText('Starting…');return
        self._pending_start=False
        available=w._structural_data_enabled() and (self._inventory.eligible_ready+self._inventory.eligible_preparation)
        if not (available or self._external_references):self._button.setText('Run search');return
        profile=self.effective_profile()
        if profile.calculation_key()!=w._active_instrument_profile().calculation_key():
            if not w._apply_instrument_profile(profile,selected=False,refresh=False):return
        le_bail = bool(self.le_bail.isEnabled() and self.le_bail.isChecked() and le_bail_available())
        w._set_pattern_le_bail(pattern, le_bail)
        w.settings.setValue('auto_search/le_bail', le_bail)
        self._remember_profile_choice();self.hide();w._start_auto_search()

    def _apply_style(self,*_args):
        c=theme_colors(widget=self.window)
        self._help_popup.setStyleSheet(
            f"QFrame#searchHelpPopup {{ background-color:{c['panel']}; "
            f"border:1px solid {c['cell_border']}; }}"
            f"QFrame#searchHelpPopup QLabel {{ color:{c['text']}; background:transparent; border:0; padding:0; }}")
        self.setStyleSheet(
            f"QFrame#autoSearchSetup {{ background:{c['panel']}; border:1px solid {c['cell_border']}; border-radius:9px; }}"
            f"QWidget#autoSearchSetupBody {{ background:{c['panel']}; }}"
            f"QFrame#autoSearchSetup QToolButton[searchHelp=true] {{ background:{c['header']}; color:{c['text']}; "
            f"border:1px solid {c['border']}; border-radius:7px; padding:0px 4px; font-weight:600; }}")

    def _place(self):
        if self._closed or self._placing:return
        self._placing=True
        try:
            anchor=self._button.mapTo(self.window,QPoint(0,self._button.height()+4))
            density=float(getattr(self.window,'_ui_density_factor',1.))
            width=min(max(320,round(460*density)),self.window.width()-16)
            self.setFixedWidth(width);self.body.setMinimumWidth(0);self.body.layout().activate()
            self.layout().activate()
            height=self.sizeHint().height()
            x=max(8,min(anchor.x(),self.window.width()-width-8))
            y=max(4,min(anchor.y(),self.window.height()-height-8))
            self.setGeometry(x,y,width,height);self.raise_()
        finally:self._placing=False

    def hideEvent(self,event):
        self._help_popup.hide()
        self._closed=True;self._pending_start=False;self._generation+=1;self._cancel.set();self._place_timer.stop()
        QApplication.instance().removeEventFilter(self)
        self._button.setText(self._button_text);self._button.setAccessibleName(self._button_text)
        self._button.setToolTip(self._button_tooltip);self._button.setMinimumWidth(self._button_minimum)
        self.window.finder_top_toolbar.set_search_mode(self.window._search_mode)
        super().hideEvent(event)

    def eventFilter(self,watched,event):
        if self._closed:return False
        if watched in (self.window,self._button) and event.type() in (QEvent.Type.Resize,QEvent.Type.Move):self._place_timer.start(0)
        if QApplication.activeModalWidget() is not None:return False
        if event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Escape:self.hide();return True
        if event.type()==QEvent.Type.MouseButtonPress and isinstance(watched,QWidget):
            in_button=self._button.rect().contains(self._button.mapFromGlobal(event.globalPosition().toPoint()))
            if self.window.isAncestorOf(watched) and not self.isAncestorOf(watched) and watched is not self and not in_button:self.hide()
        return False


def show_auto_search_setup(window):
    popup=getattr(window,'_auto_search_setup_popup',None)
    if popup is None:popup=window._auto_search_setup_popup=AutoSearchSetupPopup(window)
    if popup.isVisible():popup.start_search()
    else:popup.open()
