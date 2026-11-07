"""Locate existing controls without applying scientific or destructive actions."""
import weakref
from PySide6.QtCore import QObject,QEvent,QPoint,Qt
from PySide6.QtWidgets import QFrame,QScrollArea,QToolButton,QWidget
from shiboken6 import isValid
from xrd_finder.learning.catalog import short_prompt


def _visible(widget):
    return isinstance(widget,QWidget) and isValid(widget) and widget.isVisible()


def context_prompt(window,step):
    if step.id=='manual-search.gate':
        selected=window.selected_element_order
        if window.exclude_all_other_elements:
            return 'Other elements are excluded. Keep this for known chemistry; click Allow others only if unknown elements may be present.'
        if not selected:
            return 'No elements selected. Leave others allowed until you select a known set; Exclude others now would exclude everything.'
        return 'Other elements are allowed. If your selected set is complete, click Exclude others; otherwise keep them allowed.'
    if step.id in {'auto-search.setup','library.empty'} and _visible(getattr(window,'_auto_search_setup_popup',None)):
        return 'Search setup is already open. Review the local card count, then continue to profile settings. Press Identify phases only when ready.'
    return short_prompt(step)


def reveal_overview_target(window,key):
    """Point at capabilities without opening dialogs, menus or processing previews."""
    bar=window.finder_top_toolbar
    special={'database-button':bar.database_button,'instrument-button':bar.instrument_button,
             'plot-button':bar.view_button,'auto-button':bar.auto_search_button,'menu':window.menu_bar}
    if key in special:
        target=special[key]
        return (target if target.isVisible() else bar.more_button),''
    if key=='processing':
        window._show_menu_panel(window.finder_action_bar)
        return window.finder_action_bar,''
    return reveal_target(window,key)


def step_complete(window,check):
    """Observe a goal, not numerical identification correctness."""
    if check is None:return False
    w=window
    if check=='has_pattern':return w._active_pattern() is not None
    if check=='saved_project':return bool(w.project.root_path and __import__('pathlib').Path(w.project.root_path).is_file())
    if check=='has_series':return bool(w.project.series)
    if check=='database_open':return _visible(getattr(w,'_database_settings_dialog',None))
    if check=='library_ready':return w.local_phase_cache.peak_indexed_count()>0
    if check=='has_element_filter':return bool(w.element_states)
    if check=='has_candidates':return any(row.get('Source') and row.get('Entry') for row in w.candidate_table.ranking_row_values())
    if check=='candidate_selected':
        row=w.candidate_table.selected_row_values() or {}
        return bool(row.get('Source') and row.get('Entry'))
    if check=='has_accepted':return bool(w.match_candidates)
    if check=='match_ready':return not getattr(w,'_auto_search_in_progress',False) and any(
        str(row.get('Match (%)','')).strip() not in {'','Inactive','No score'}
        for row in w.candidate_table.ranking_row_values())
    if check=='gain_ready':
        controller=getattr(w,'gain_job_controller',None)
        return bool(w.match_candidates and controller is not None and not controller.running
                    and controller._completed_identity is not None)
    if check=='auto_setup_open':return _visible(getattr(w,'_auto_search_setup_popup',None))
    if check=='instrument_open':return _visible(getattr(w,'_instrument_profile_dialog',None))
    if check=='plot_settings_open':return _visible(getattr(w,'_plot_view_settings_dialog',None))
    if check=='single_pattern_mode':return not w.show_all_selected_patterns and w._active_pattern() is not None
    if check=='multiple_patterns':return w.show_all_selected_patterns and len(w.tree.checked_pattern_ids())>1
    if check=='selected_peaks':return bool(w._manual_search_peaks.get(getattr(w._active_pattern(),'id',None),[]))
    if check=='peak_card_open':return _visible(getattr(w,'_peak_info_dialog',None))
    keys={'background_panel_open':'background','smoothing_panel_open':'smooth','crop_panel_open':'xrd_crop'}
    if check in keys:
        return getattr(w,'_preprocessing_panel_key',None)==keys[check] and _visible(getattr(w,'_preprocessing_panel',None))
    return False


def _menu(window,title):
    menu=next((menu for menu in window.menu_bar._owned_menus if menu.title().replace('&','')==title),None)
    if menu is None:return None
    menu.popup(window.mapToGlobal(QPoint(20,window.finder_top_toolbar.height()+12)))
    return menu


def reveal_target(window,key):
    """Return (live widget, explanation). File choosers/Apply/search never fire."""
    w=window;bar=w.finder_top_toolbar;controls=w.finder_plot_control_bar
    direct={'files':bar,'import':bar.import_button,'save':bar.save_button,
        'tree':w.tree,'series':w.project_controls,'order':w.project_controls,
        'candidates':w.candidate_table,'gain':w.candidate_table,'selected':w.match_table,
        'status':w.background_status_label,'peak-search':bar.peak_search_button,'auto-run':bar.auto_search_button,
        'patterns':controls.pattern_display_mode,'normalize':controls.normalize_patterns_checkbox,
        'aspect':controls.plot_aspect_mode,'layout':w._layout_state.pin_button,
        'reset-processing':bar.reset_data_button,'plot':w.match_plot}
    if key in direct:
        widget=direct[key]
        if key=='save' and not widget.isEnabled():
            return _menu(w,'File'),'Use Save project as for the first project save.'
        if not widget.isVisible() and widget in getattr(bar,'_overflow_actions',{}):
            menu=bar.more_button.menu();bar._sync_overflow_actions()
            menu.popup(bar.more_button.mapToGlobal(QPoint(0,bar.more_button.height())))
            return menu,'This control is available in the toolbar More menu at this width.'
        return widget,''
    menus={'sample-menu':'Edit','search-menu':'Search','tools-menu':'Tools',
           'pattern-menu':'Pattern','peaks-menu':'Peaks','help-menu':'Help','calibration-menu':'Tools'}
    if key in menus:return _menu(w,menus[key]),'Use the command named in Where in this menu.'
    if key in {'elements','element-gate','database-search'}:
        w._show_menu_panel(w.composition_panel)
        if key=='element-gate':return w.element_table.mode_button,'The button names the next action, not the current state.'
        return (w.element_table if key=='elements' else w.composition_panel.search_button),''
    if key in {'databases','database-paths','database-api'}:
        w._show_database_settings_window()
        target={'databases':w.database_panel,'database-paths':w.database_panel.database_table,
                'database-api':w.database_panel.materials_project_api_key_input}[key]
        return target,'Review settings; Show me does not enable sources or save credentials.'
    if key=='user-library':
        w._show_user_phase_library_window()
        return w._user_phase_library_dialog,'Use Import data for individual CIFs; library Import/Export transfers a JSON library bundle.'
    if key in {'auto-setup','auto-profile','auto-lebail'}:
        if w._active_pattern() is None:
            return bar.import_button,'Import or select a measurement first; search setup needs an active XRD.'
        popup=getattr(w,'_auto_search_setup_popup',None)
        if key=='auto-setup':
            return (popup if _visible(popup) else bar.auto_search_settings_button),'Use the down arrow for settings. The main Identify phases button starts the search.'
        from xrd_finder.ui.auto_search_setup import AutoSearchSetupPopup
        if popup is None or not isValid(popup):popup=w._auto_search_setup_popup=AutoSearchSetupPopup(w)
        if not popup.isVisible():popup.open()
        return (popup.le_bail if key=='auto-lebail' else popup.profile_combo),'Setup only. Press Identify phases yourself when you are ready.'
    if key in {'processing','background','smoothing','crop'}:
        w._show_menu_panel(w.finder_action_bar)
        if key=='processing':return w.finder_action_bar,''
        pattern=w._active_pattern()
        if pattern is None or getattr(pattern,'input_kind','')=='peak_list':
            return None,'Select a measured XRD measurement or open the training demo before this step.'
        button={'background':w.finder_action_bar.background_button,
                'smoothing':w.finder_action_bar.smooth_button,'crop':w.finder_action_bar.crop_button}[key]
        return button,'Open this section yourself to preview. Apply commits; Cancel restores; Reset reverses that processing step.'
    if key.startswith('instrument'):
        section={'instrument':'identity','instrument-radiation':'radiation',
                 'instrument-resolution':'resolution','instrument-geometry':'geometry'}[key]
        dialog=getattr(w,'_instrument_profile_dialog',None)
        if not _visible(dialog):w._open_instrument_profile_editor(section)
        else:
            from xrd_finder.ui.instrument_profile_dialog import SECTION_INDEX
            dialog.tabs.setCurrentIndex(SECTION_INDEX[section]);dialog.raise_()
        return w._instrument_profile_dialog,'Nothing is applied until you use the instrument dialog controls.'
    if key=='plot-settings':
        w._show_plot_view_settings_window()
        return w._plot_view_settings_dialog,''
    if key=='candidate-card':
        row=w.candidate_table.selected_row_values() or {}
        if not row.get('Source'):return w.candidate_table,'Select a candidate row first to inspect its card.'
        w._show_candidate_entry_card()
        return w.compound_card,''
    return None,'This control is not available in the current context. Read Where or open the demo.'


class TargetHighlight(QObject):
    """Mouse-transparent border; never retain a deleted Qt control as a target."""
    def __init__(self,owner,*,on_help=None,on_clear=None,color='#00a88a',scroll_to_target=True):
        super().__init__(owner)
        self.frame=None;self.question=None;self._target=None;self._surface=None
        self.on_help=on_help;self.on_clear=on_clear
        self.color=color;self.scroll_to_target=scroll_to_target

    @property
    def active(self):return _visible(self.frame)

    def show(self,target):
        self.clear()
        if not isinstance(target,QWidget) or not isValid(target):return False
        parent=target.parentWidget()
        while parent is not None:
            if isinstance(parent,QScrollArea) and self.scroll_to_target:parent.ensureWidgetVisible(target);break
            parent=parent.parentWidget()
        if not target.isVisible():return False
        # Several Finder popups expose .window as their owner attribute.
        surface=QWidget.window(target)
        self._target=weakref.ref(target);self._surface=weakref.ref(surface)
        frame=self.frame=QFrame(surface)
        frame.setObjectName('learningTargetOutline')
        frame.setAttribute(Qt.WA_TransparentForMouseEvents,True)
        frame.setFocusPolicy(Qt.NoFocus)
        frame.setStyleSheet('QFrame#learningTargetOutline {background:transparent; border:3px solid '+self.color+'; border-radius:4px;}')
        question=self.question=QToolButton(surface)
        question.setText('?');question.setAccessibleName('Why this step?')
        question.setToolTip('Why this action? Click for an explanation.')
        question.setFixedSize(24,24);question.setStyleSheet(
            'QToolButton {background:#087f69;color:white;border:1px solid #00a88a;border-radius:12px;'
            'padding:0;font-weight:bold;font-size:14px;}')
        if self.on_help is not None:question.clicked.connect(self.on_help)
        else:question.hide()
        target.installEventFilter(self)
        if target is not surface:surface.installEventFilter(self)
        self._place()
        return self.active

    def _place(self):
        target=self._target() if self._target else None
        surface=self._surface() if self._surface else None
        if not _visible(target) or not _visible(surface):self.clear();return
        rect=target.rect();rect.moveTopLeft(target.mapTo(surface,QPoint(0,0)))
        rect=rect.adjusted(-2,-2,2,2).intersected(surface.rect())
        if not rect.isValid():self.clear();return
        if self.frame is not None and isValid(self.frame):
            self.frame.setGeometry(rect);self.frame.show();self.frame.raise_()
        if self.question is not None and isValid(self.question) and self.on_help is not None:
            side=self.question.width()
            x=max(2,min(rect.right()-side+2,surface.width()-side-2))
            y=rect.bottom()+4
            if y+side>surface.height()-2:y=max(2,rect.top()-side-4)
            self.question.move(x,y);self.question.show();self.question.raise_()

    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Hide,QEvent.Close,QEvent.DeferredDelete):self.clear()
        elif event.type() in (QEvent.Move,QEvent.Resize,QEvent.Show):self._place()
        return False

    def clear(self):
        for ref in (self._target,self._surface):
            widget=ref() if ref else None
            if widget is not None and isValid(widget):widget.removeEventFilter(self)
        self._target=None;self._surface=None
        if self.frame is not None and isValid(self.frame):self.frame.hide();self.frame.deleteLater()
        self.frame=None
        if self.question is not None and isValid(self.question):self.question.hide();self.question.deleteLater()
        self.question=None
        if self.on_clear is not None:self.on_clear()
