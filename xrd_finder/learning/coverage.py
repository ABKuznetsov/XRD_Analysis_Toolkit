"""Trace current menu commands to practical topics; regression-checked against Qt."""

MENU_TOPICS={
    'New project':'projects.files','Open project':'projects.files',
    'Save project':'projects.save','Save project as':'projects.save',
    'Import XRD / CIF':'projects.import','Restore original pattern':'processing.reset',
    'Sample ID':'projects.notes','Sample date/time':'projects.notes','Sample notes':'projects.notes',
    'Plot appearance':'appearance-export.plot','Show grid':'appearance-export.defaults',
    'Autoscale':'appearance-export.aspect','Reset zoom':'appearance-export.aspect',
    'Instrument profile':'instrument.saved','Wavelength':'instrument.radiation','Resolution':'instrument.resolution',
    'Insert/overlay':'projects.import','Crop XRD':'processing.crop',
    'Edit background':'processing.background','Recalculate background':'processing.background',
    'Subtract background':'processing.background','Smooth raw data':'processing.smoothing',
    'Zero shift':'processing.zero','Find peaks':'peaks.find','Mark selected peaks':'peaks.select',
    'Clear selected search peaks':'peaks.select','Fit a peak':'peaks.info','Peak area':'peaks.info',
    'Add peak':'peaks.manual','Delete peak':'peaks.manual','Peak information':'peaks.info',
    'Search by name/formula':'manual-search.formula','Search by formula':'manual-search.formula',
    'Search by elements':'manual-search.run','Peak search':'peaks.select',
    'Add selected to working set':'phases.accept','Add selected CIF to project':'phases.overlay',
    'Open entry card':'phases.preview','Candidate list':'phases.candidates',
    'Project phases':'projects.cif','Materials Project':'databases.services',
    'User phase library':'library.import','Database settings':'databases.sources',
    'Calibrate pattern':'processing.zero','Export candidate list':'appearance-export.csv',
    'Create secure macOS installer':'databases.security','Create secure Windows installer':'databases.security',
    'Export settings':'appearance-export.settings','Import settings':'appearance-export.settings',
    'Learn Finder':'appearance-export.planned','Quick reference':'appearance-export.planned',
    'Security and offline use':'databases.security','Open example project':'projects.files',
    'Manual':'appearance-export.planned','About XRD Phase Finder':'appearance-export.planned',
}


def menu_topic(text):
    if '(planned)' in text or '(in development)' in text:return 'appearance-export.planned'
    if text.startswith('Network mode:'):return 'databases.offline'
    return MENU_TOPICS.get(text.replace('&','').replace('…','').removesuffix('...').strip())
