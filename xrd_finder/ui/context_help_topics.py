"""Resolve live Finder controls to explanations without executing their actions."""
from dataclasses import dataclass
import re
from PySide6.QtWidgets import (QWidget,QAbstractButton,QAbstractItemView,QAbstractSpinBox,
                              QComboBox,QLineEdit,QSlider,QTabBar,QFormLayout,QLabel,QMenu)
from xrd_finder.learning.catalog import STEPS
from xrd_finder.learning.coverage import menu_topic


@dataclass(frozen=True)
class HelpArticle:
    title: str
    what: str
    why: str
    how: str
    topic: str


def _article(topic,title=None,what=None,how=None):
    step=STEPS[topic]
    definitions={
        'projects.files':'A project stores measurements, structures and their interpretation together.',
        'projects.import':'Add measured angle/intensity data or a CIF crystal structure to the current project.',
        'projects.save':'Save your measurements, interpretation and display settings as an XPFF project.',
        'tree.active':'The tree organises series, measurements and structures. Active and checked are different states.',
        'manual-search.elements':'Chemical restrictions used to retrieve reference cards; these are not measured elemental amounts.',
        'manual-search.gate':'Allow or exclude elements not selected individually in the periodic table.',
        'manual-search.run':'Retrieve candidate cards using chemical restrictions and enabled reference sources.',
        'auto-search.setup':'Automatic comparison of the active measurement against prepared local reference cards.',
        'auto-search.match':'Match scores how well a reference describes the experimental diffraction pattern. It is not a probability.',
        'auto-search.gain':'Gain estimates the additional evidence a candidate contributes after the phases already selected.',
        'auto-search.status':'Inactive means no calculation is enabled; No score means no available result. Neither means a measured zero.',
        'phases.candidates':'Possible reference matches. A candidate is not yet an accepted component of your sample.',
        'phases.edit':'Phases accepted for the active measurement, rather than all possible database candidates.',
        'phases.quant':'Structural mass-fraction estimates and fit indicators are different quantities. Missing estimates are not zero.',
        'databases.sources':'Configure which local collections and online services can provide reference structures.',
        'databases.credentials':'Source access settings, including a personal API key when the service requires it.',
        'library.empty':'The number of prepared local reference cards available under the current chemical restrictions.',
        'processing.original':'Reversible preparation of the active measurement: smoothing, background, range and angle correction.',
        'processing.smoothing':'Reduce experimental noise while trying to preserve peak shape and position.',
        'processing.background':'Estimate the non-peak baseline and inspect it before subtracting it.',
        'processing.crop':'Choose which angular intervals participate in the working measurement.',
        'processing.zero':'A common correction of the angular scale; display correction and calibration have separate roles.',
        'processing.reset':'Recover the original measurement after an unsuitable processing choice.',
        'instrument.saved':'A reusable description of your diffractometer, radiation, geometry and resolution.',
        'instrument.resolution':'Instrumental peak width: a constant FWHM or angle-dependent TCH profile parameters.',
        'instrument.calibration':'Estimate instrumental broadening from a measured coarse-grained standard and its CIF.',
        'instrument.lebail':'Limited profile improvement of accepted CIF phases; it is not a full structural refinement.',
        'multi.all':'Choose One active measurement or All selected measurements checked in the project tree.',
        'multi.normalize':'Normalise curve heights and separate measurements vertically for comparison.',
        'appearance-export.aspect':'Fit the plot to its available area or choose a fixed aspect ratio; zoom and pan control its view.',
        'appearance-export.layout':'Unlock panel resizing, adjust panel proportions and UI scale, then lock to save the layout.',
        'appearance-export.plot':'Set the visible curves, axes, grid, markers, labels and legends.',
        'appearance-export.image':'Export the displayed figure as an image or an editable vector graphic.',
    }
    return HelpArticle(title or step.title,what or definitions.get(topic,step.expected),step.purpose,
                       how or step.instruction,topic)


def _label(widget):
    """Read descriptions only; never inspect user-entered text or credentials."""
    name=widget.accessibleName()
    if name:return name
    if isinstance(widget,(QAbstractButton,QLabel)):return widget.text().replace('&','')
    parent=widget.parentWidget()
    while parent is not None:
        for form in parent.findChildren(QFormLayout):
            label=form.labelForField(widget)
            if isinstance(label,QLabel):return label.text().replace('&','').rstrip(':')
        parent=parent.parentWidget()
    if isinstance(widget,QLineEdit):return widget.placeholderText()
    return ''


def resolve_help(window,widget,global_pos=None):
    """Nearest specific control wins over its enclosing panel."""
    bar=window.finder_top_toolbar;controls=window.finder_plot_control_bar
    direct={}
    def add(owner,attributes):
        for name,topic in attributes.items():
            obj=getattr(owner,name,None)
            if isinstance(obj,QWidget):direct[obj]=topic
    add(bar,{'new_button':'projects.files','open_button':'projects.files','save_button':'projects.save',
        'import_button':'projects.import','auto_search_button':'auto-search.setup','peak_search_button':'peaks.select',
        'reset_data_button':'processing.reset','reset_view_button':'appearance-export.aspect',
        'database_button':'databases.sources','view_button':'appearance-export.plot','instrument_button':'instrument.saved',
        'layout_button':'appearance-export.layout','help_button':'appearance-export.planned','more_button':'appearance-export.layout'})
    add(controls,{'pattern_display_mode':'multi.all','plot_aspect_mode':'appearance-export.aspect',
        'normalize_patterns_checkbox':'multi.normalize','pattern_offset_slider':'multi.normalize',
        'correct_zero_checkbox':'processing.zero','cursor_position_status_label':'appearance-export.plot'})
    add(window,{'tree':'tree.active','project_controls':'tree.series','candidate_table':'phases.candidates',
        'match_table':'phases.edit','match_plot':'appearance-export.plot','compound_card':'phases.preview',
        'background_status_label':'auto-search.status','database_panel':'databases.sources',
        'plot_settings_panel':'appearance-export.plot','composition_panel':'manual-search.run',
        'finder_action_bar':'processing.original'})
    add(window.element_table,{'mode_button':'manual-search.gate'})
    add(window.composition_panel,{'search_button':'manual-search.run','reset_button':'manual-search.elements',
        'rank_by_probability_checkbox':'auto-search.match','inorganics_checkbox':'manual-search.run',
        'organics_checkbox':'manual-search.run','structural_data_checkbox':'manual-search.run',
        'reference_patterns_checkbox':'manual-search.run','ccdc_doi_input':'manual-search.formula'})
    add(getattr(window,'database_panel',None),{'materials_project_api_key_input':'databases.credentials'})
    add(window.finder_action_bar,{'smooth_button':'processing.smoothing','background_button':'processing.background',
        'crop_button':'processing.crop','zero_shift_value':'processing.zero','zero_shift_section':'processing.zero',
        'instrument_profile_combo':'instrument.saved','instrument_profile_edit_button':'instrument.saved',
        'peak_search_tolerance':'peaks.select'})
    for key,topic in (('_auto_search_setup_popup','auto-search.setup'),('_instrument_profile_dialog','instrument.saved'),
                       ('_database_settings_dialog','databases.sources'),('_plot_view_settings_dialog','appearance-export.plot'),
                       ('_manual_calibration_dialog','processing.zero'),('_peak_info_dialog','peaks.info')):
        add(window,{key:topic})
    popup=getattr(window,'_auto_search_setup_popup',None)
    add(popup,{'le_bail':'instrument.lebail','profile_combo':'auto-search.profile',
               'profile_enhancement':'auto-search.profile','available':'library.empty'})
    dialog=getattr(window,'_instrument_profile_dialog',None)
    editor=getattr(dialog,'editor',None)
    if editor is not None:
        for name,obj in vars(editor).items():
            if isinstance(obj,QWidget):
                topic=('instrument.resolution' if name.startswith(('tch_','constant_fwhm','resolution')) else
                       'instrument.calibration' if name=='calibrate_profile_button' else
                       'instrument.radiation' if name.startswith(('radiation','component_','tube_','filter_','monochromator')) else
                       'instrument.geometry' if name in {'geometry','apply_lp','polarization_fraction','goniometer_radius'} else
                       'instrument.saved')
                direct[obj]=topic
    prep=getattr(window,'_preprocessing_panel',None)
    if prep is not None:direct[prep]={'smooth':'processing.smoothing','background':'processing.background',
                                     'xrd_crop':'processing.crop'}.get(getattr(window,'_preprocessing_panel_key',''),'processing.original')
    chain=[];current=widget
    while isinstance(current,QWidget):chain.append(current);current=current.parentWidget()
    element_buttons=window.element_table._buttons
    for target in chain:
        if type(target).__name__=='PlotExportDialog':direct[target]='appearance-export.image'
        symbol=next((s for s,b in element_buttons.items() if b is target),None)
        if symbol:
            state=window.element_states.get(symbol,'optional')
            return target,_article('manual-search.elements',f'{symbol} — {state.title()} element',
                f'Chemical search restriction for {symbol}; it does not change the measured composition.',
                STEPS['manual-search.elements'].instruction+' '+STEPS['manual-search.gate'].instruction)
        if isinstance(target,QMenu) and global_pos is not None:
            action=target.actionAt(target.mapFromGlobal(global_pos))
            if action is not None:
                source=next((b for b,a in bar._overflow_actions.items() if a is action),None)
                if source is not None:return source,resolve_help(window,source)[1]
                topic=menu_topic(action.text())
                if topic:return target,_article(topic,action.text().replace('&',''))
        if isinstance(target,QTabBar):
            index=target.tabAt(target.mapFromGlobal(global_pos)) if global_pos is not None else target.currentIndex()
            title=target.tabText(index) if index>=0 else 'Tabs'
            topic={'Elements':'manual-search.elements','Processing':'processing.original',
                   'Phase details':'phases.preview','Resolution':'instrument.resolution',
                   'Radiation':'instrument.radiation'}.get(title)
            if topic:return target,_article(topic,title)
        if target in direct:
            topic=direct[target]
            # A child control in a settings form has a useful label/tooltip of its own.
            child=next((c for c in chain if isinstance(c,(QAbstractButton,QAbstractSpinBox,QComboBox,QLineEdit,QSlider))),None)
            title=_label(target) or STEPS[topic].title
            tip='' if target in bar._buttons else target.toolTip()
            if target is getattr(bar,'help_button',None):
                return target,HelpArticle('Context help','Click-to-explain mode for Finder controls.',
                    'Learn a control without running its command.',
                    'Turn Help on, point at a control and click. Purple means Help is active. '
                    'Press Esc or Help again to return to normal use. '
                    'Open Help → Learn Finder in the top menu for tutorials and guided practice.',topic)
            if child is not None and target not in bar._buttons and child is not target:
                title=_label(child) or title;tip=child.toolTip() or tip;target=child
            if target in (window.candidate_table,window.match_table) and global_pos is not None:
                table=target
                header=table.horizontalHeader() if isinstance(table,QAbstractItemView) else None
                if header is not None:
                    column=header.logicalIndexAt(header.mapFromGlobal(global_pos).x())
                    if column>=0:
                        item=table.horizontalHeaderItem(column)
                        text=item.text() if item is not None else ''
                        if 'Match' in text:topic='auto-search.match';title=text
                        elif 'Gain' in text:topic='auto-search.gain';title=text
                        elif any(key in text for key in ('wt.','I/Ic','Fit /')):topic='phases.quant';title=text
            return target,_article(topic,title,how=(tip+'\n\n'+STEPS[topic].instruction) if tip else None)
    # A newly opened settings dialog can still explain its labelled controls.
    target=next((c for c in chain if isinstance(c,(QAbstractButton,QAbstractSpinBox,QComboBox,QLineEdit,QSlider))),widget)
    title=_label(target) or 'Finder control'
    tip=re.sub('<[^>]*>','',target.toolTip()).strip()
    return target,HelpArticle(title,tip or 'A control in the current Finder panel.',
        'Configure the current operation before applying it.',
        (tip+' ' if tip else '')+'Turn off Help to use this control. For a guided workflow, open Help → Learn Finder.',
        'appearance-export.planned')
