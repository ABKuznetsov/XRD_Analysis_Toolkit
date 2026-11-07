"""Authored lessons about the controls and scientific contracts Finder exposes."""
from dataclasses import dataclass,replace
import re


@dataclass(frozen=True)
class LearningStep:
    id: str
    title: str
    purpose: str
    where: str
    instruction: str
    expected: str
    troubleshooting: str
    target: str
    check: str | None = None
    keywords: str = ''


@dataclass(frozen=True)
class LearningChapter:
    id: str
    title: str
    summary: str
    steps: tuple[LearningStep, ...]


S = LearningStep
C = LearningChapter

CHAPTERS = (
 C('projects', '1 · Projects and files', 'Open measurements and structures, save your interpretation and record sample details.', (
  S('projects.files', 'Measurement, structure or project?',
    'Choose the right kind of file for the information you have.', 'File menu; New project, Open project, Import data',
    'An XRD measurement contains angle/intensity samples. A CIF describes a crystal structure. An XPFF project keeps measurements, interpretation and display settings together. New project starts an empty workspace; Open project loads XPFF; Import data adds XRD or CIF to the current project.',
    'You know which command adds data and which command opens a complete project.',
    'Opening a CIF alone does not provide an experimental measurement. Importing a measurement does not populate an identification database.', 'files', keywords='open load import xy txt dat csv xye cif xpff new project'),
  S('projects.import', 'Import an XRD measurement',
    'Bring experimental data into Finder.', 'Import data → select an XRD file',
    'Import an XY, TXT, DAT, CSV or XYE measurement. You can also drag supported files into the workspace. Select its measurement row in the tree. In the demo, two synthetic measurements are already loaded; inspect either one before proceeding.',
    'The tree contains a measurement and the graph displays its intensity versus 2θ.',
    'Check that columns contain angle and intensity, the decimal separator is understood and the angular range is sensible. The display is limited to 0–125°; data outside it are retained.', 'import', 'has_pattern'),
  S('projects.cif', 'Import a CIF structure',
    'Keep a structural reference with the project.', 'Import data → select a CIF; Project → Structures',
    'Import a CIF when you want its structure in the project tree. Project structures, search-library cards and phases accepted for a measurement are different objects. A tree CIF does not automatically mean that the phase is present in every measurement.',
    'A structure appears under Structures; its checkbox controls the corresponding project display.',
    'If the structure cannot be read, check the CIF diagnostics. A filename extension alone does not make a valid crystal structure.', 'tree', keywords='CIF structure project phases'),
  S('projects.save', 'Save a portable interpretation',
    'Retain your analysis so it can be reopened.', 'File → Save project / Save project as',
    'Use Save project as for the first save and choose an .xpff destination. Save keeps later changes there. The project includes measurements, required accepted CIFs, sample notes and compatible calculated results. A figure export is a picture and does not replace this project save.',
    'The title/project path refers to your chosen XPFF file. Reopening restores compatible interpretation results.',
    'When asked to save an example, choose your own copy. Modified data, profiles, structures or calculation versions may require preparing results again.', 'save', 'saved_project', keywords='portable export save as reopen'),
  S('projects.notes', 'Sample identity and synthesis notes',
    'Keep the preparation history with each measurement.', 'Edit → Sample ID / Sample date/time / Sample notes',
    'Select the desired measurement first. Enter its identifier, measurement date if known, and notes such as synthesis temperature, duration, grinding and atmosphere. Save the project after editing. These fields belong to the selected sample, not the whole series.',
    'The measurement retains its own sample information when the XPFF project is reopened.',
    'An unknown date may stay empty. Changing the active measurement before editing can put notes on the wrong sample.', 'sample-menu', keywords='synthesis notes preparation sample date identifier'),
 )),
 C('tree', '2 · Project tree and series', 'Understand active objects, visibility, groups and display order.', (
  S('tree.active', 'Active is different from visible',
    'Direct searches and edits at the intended measurement.', 'Project tree → measurement row',
    'Click a measurement row to make it active. Searches, preprocessing and Selected phases relate to that measurement. A checked row is selected for display; several checked curves can coexist while only one measurement is active.',
    'The active measurement and its selected-phase table agree with the row you chose.',
    'If a search seems to affect another sample, inspect the active row first. A checked group is not a separate combined experimental pattern.', 'tree', 'has_pattern', keywords='active visible checked checkbox'),
  S('tree.visibility', 'Checkboxes and double click',
    'Quickly choose what to display.', 'Checkboxes beside measurements and series',
    'Use checkboxes to include or hide measurements and groups. Double click a measurement to display it alone. Then switch Patterns to All selected if you want to compare the checked measurements together.',
    'Visibility changes without deleting measurements from the project.',
    'Unchecking a curve does not remove its data or accepted phases. Check Patterns mode if several checked samples still appear one at a time.', 'tree', keywords='double click checkbox hide show'),
  S('tree.series', 'Organise measurements into series',
    'Keep temperatures, compositions or repeats together.', 'Add series; project-tree right-click menu',
    'Add a series, give it a meaningful name and use the tree context menu to organise measurements and structures. Distinguish moving an object from copying a measurement to a series. Use the sample notes for detailed preparation information.',
    'Related measurements can be expanded, selected and compared as a group.',
    'A series organises data; it does not automatically perform a joint phase identification or turn all its samples into one measurement.', 'series', 'has_series', keywords='group folder temperature copy move'),
  S('tree.order', 'Rename and change display order',
    'Make a stack and its labels easy to read.', 'Tree right-click menu; Order → Up / Down',
    'Select a tree object and use Up or Down to change its order. Rename objects through the context menu. In a multi-pattern view, use names that distinguish temperature, composition or processing conditions.',
    'The display order and labels follow the saved project organisation.',
    'Renaming is not a change to the chemical identity of a CIF. Avoid deleting an object when you only intended to hide its curve.', 'order', keywords='rename order up down'),
 )),
 C('databases', '3 · Sources and database settings', 'Know where references come from and configure local, online and licensed sources.', (
  S('databases.sources', 'See the available reference sources',
    'Know which libraries Finder can actually use.', 'Manage databases',
    'Open Manage databases and inspect the source table. User library, COD local, COD online, RRUFF, PDF-2 and configured structure services have different roles. Enable only the sources you intend to use; a listed source is not the same as an installed reference collection.',
    'You can identify the enabled sources and distinguish Ready from Not configured.',
    'A large online catalogue does not mean its entire contents are already in your local automatic-search library.', 'databases', 'database_open', keywords='COD CSD CCDC AFLOW OQMD Materials Project RRUFF PDF-2'),
  S('databases.paths', 'Find where local databases are stored',
    'Inspect the actual storage location instead of guessing.', 'Manage databases → source Details and location tooltip',
    'Inspect a source row and its tooltip for the configured location. Local user-library data live in your user profile rather than beside the installed program. Folder-based sources such as PDF-2 have their own selected folder. Use the app controls to index/import/export references.',
    'You know the local cache location and the folder used by a configured source.',
    'Do not edit an open SQLite file as a normal spreadsheet. Copying a program folder does not necessarily copy the user libraries or their settings.', 'database-paths', keywords='location folder SQLite SQL cache storage path'),
  S('databases.credentials', 'Configure access and API keys',
    'Connect a source only when its access requirements are satisfied.', 'Manage databases → source options / Materials Project',
    'For Materials Project, enter your own API key and save its settings. Licensed services require their own installed software or access. For a local PDF-2 collection, select the appropriate folder and prepare its index. Source availability depends on the actual configuration.',
    'The source reports a usable configuration before you rely on it for searching.',
    'A checkbox cannot supply a missing licence, API key or local collection. Never put personal keys into a shared demo project or screenshot.', 'database-api', keywords='API key credentials licence licensed PDF-2 folder CSD'),
  S('databases.offline', 'Work online or offline',
    'Understand what remains possible without network access.', 'Tools → Network mode; Manage databases',
    'Offline mode uses prepared local references and prevents online retrieval. Online mode permits enabled remote services. The training demo always runs offline in its own temporary library; it does not copy your API keys, source settings or personal database.',
    'Local search can work offline after suitable references have been added.',
    'A connection error is not evidence that a phase is absent. Switching online does not automatically download all possible structures.', 'tools-menu', keywords='network offline secure online connection VPN'),
  S('databases.transfer', 'Transfer libraries and settings deliberately',
    'Move configuration without confusing it with a scientific project.', 'Manage databases → source Import / Export; Tools → Export settings',
    'Use a source-specific library export/import when moving cached references. Use Export settings / Import settings for configuration. Save XPFF for a sample interpretation. These operations carry different information; inspect the destination and selected contents before sharing.',
    'The recipient receives the intended references or settings rather than an unrelated folder.',
    'Settings and source licences are not interchangeable. Keep credentials and personal library contents out of files you intend to publish.', 'databases', keywords='backup export import settings library'),
 )),
 C('library', '4 · Build a useful local library', 'Populate the references auto search needs, and understand an empty result.', (
  S('library.empty', 'Why an empty database cannot identify a phase',
    'Understand the boundary of automatic identification.', 'Identify phases → Local cards available',
    'Open Identify phases once and inspect Local cards available. Auto search compares the measurement with prepared local reference cards. With an empty database, zero available cards means there is nothing to compare. Existing element filters and enabled sources can also reduce this count to zero.',
    'You can distinguish no available reference cards from a poor match to a measured pattern.',
    'If your empty database contains no reference for the target phase, repeatedly running auto search cannot discover that missing card. Add references or retrieve them manually first.', 'auto-setup', keywords='empty database zero 0 no results auto missing available cards'),
  S('library.import', 'Add your own CIF references',
    'Build a focused library for the materials you actually study.', 'Import data → CIF; Database → User phase library',
    'Import valid CIF files through Import data; Finder also registers successfully prepared imported structures in the user library. Inspect that library through Database → User phase library. Its Import/Export buttons transfer a library JSON bundle rather than an individual CIF. Wait for preparation before searching. The demo uses its own small NaCl/corundum library.',
    'Prepared local cards become available for suitable later searches without an online connection.',
    'A registered filename is not enough: an invalid CIF or an unresolved structure may be unavailable for calculation. Read the diagnostic rather than assuming a zero contribution.', 'import', 'library_ready', keywords='create database add CIF import reference index'),
  S('library.manual', 'Check and populate references for this sample',
    'Find a card that automatic local search cannot yet see.', 'Search → Search by name/formula or Search by formula',
    'Before auto search, review whether local cards cover this sample, even if the library is nonempty. Enable suitable sources and search by known formulas, names or IDs, or use Elements search. Inspect candidates and retrieve suitable CIFs; prepared downloads are kept for later auto search. Alternatively import your own CIF files. Continue after reviewing the references: no arbitrary card count proves completeness.',
    'You have deliberately reviewed or supplemented references for the current chemistry before Match.',
    'A library containing only one or two material families cannot identify arbitrary materials. Online lookup needs an enabled, configured and reachable source. In the offline demo use its bundled cards.', 'search-menu', keywords='download retrieve cache missing card manual formula coverage nonempty database'),
  S('library.bulk', 'Index a folder or archive selectively',
    'Prepare a larger collection without downloading everything.', 'Manage databases → COD local/bulk and index controls',
    'Use the existing folder or ZIP indexing controls for a collection you already have. Choose the relevant material families and allow preparation to finish. A practical library can contain tens of thousands of useful cards; you do not need the entire COD catalogue to begin.',
    'The prepared collection is reused for later requests.',
    'Large imports take time once. Cancelling or closing may leave remaining work for a later attempt; an incomplete preparation is not a scientific negative result.', 'databases', keywords='bulk folder ZIP index collection COD'),
  S('library.audit', 'Check reference integrity and reuse',
    'Understand saved calculations and composition diagnostics.', 'Manage databases → Check CIF composition / rebuild controls',
    'Use Check CIF composition when auditing older cards. Finder checks structural composition for its chemical search index and explains incompatible quantitative inputs. Prepared reflections and I/Ic are cached; obsolete I/Ic is refreshed in idle. Rebuilding indexes is a maintenance operation, not a required step before every search.',
    'Unchanged references are reused; genuine input/version changes can trigger preparation.',
    'Do not ignore a CIF-composition warning just because the phase name looks correct. A missing estimate must not be interpreted as a measured zero.', 'databases', keywords='audit integrity cache I/Ic composition rebuild'),
 )),
 C('manual-search', '5 · Manual chemical search', 'Use the periodic table, names and formulas to retrieve candidate cards.', (
  S('manual-search.elements', 'Required, Optional and Excluded elements',
    'Express chemical knowledge without accidentally excluding the answer.', 'Elements → periodic table',
    'Left click an element to require it (blue). Right click to exclude it (pink). Optional elements (green) may be present. Repeating the same mouse button clears that selection. For example, requiring Al and O will exclude a NaCl-only card; use only restrictions supported by your sample knowledge.',
    'The Chemical filter summary describes your intended restrictions.',
    'Required Optional Excluded are search restrictions, not measured composition. Overly strict restrictions can hide the correct phase or a contaminant.', 'elements', 'has_element_filter', keywords='required optional excluded periodic table left right click chemical'),
  S('manual-search.gate', 'Allow or exclude the remaining elements',
    'Control elements that you did not select individually.', 'Elements → Allow others / Exclude others',
    'After selecting the complete known element set, click Exclude others: the other elements turn pink and the button becomes Allow others. Leaving other elements green allows cards with additional elements. If the button already says Allow others, exclusion is active; do not click it again unless you want to reopen the filter. Leave others allowed when unknown dopants or contaminants are possible. With no selected elements, do not exclude everything.',
    'The filter allows the intended set of elements while retaining deliberately optional ones.',
    'A trace additive can matter. Requiring every mixture element in manual chemical retrieval can exclude simpler component phases; review subsets too. Auto search can examine component subsets.', 'element-gate', keywords='allow others exclude others gate dopant impurity'),
  S('manual-search.run', 'Search database with the chemical filters',
    'Retrieve possible cards independently of automatic phase identification.', 'Elements → Search database; Search → Search by elements',
    'Choose element states, select Inorganic/Organic and CIF structures/Profile only, then use Search database. Match is calculated in the background when a usable measurement is available. Click a candidate-table column heading to sort; click again to reverse the order. Add CIF folders, ZIP downloads or mapped JSON APIs under Manage databases → Add / manage database connections.',
    'The candidate table lists chemical-search results; a listed card is still only a possibility.',
    'Manual chemical retrieval and automatic XRD identification are different actions. Inactive is not a calculated score of zero.', 'database-search', 'has_candidates', keywords='manual table search database rank match inorganic organic'),
  S('manual-search.formula', 'Search by formula, name or database ID',
    'Retrieve a known compound even before its local library is populated.', 'Search → Search by name/formula / Search by formula',
    'Enter a formula, compound name or an identifier suitable for the selected source. Formula search uses enabled local and online sources; ordinary equivalent formula orders, groups and hydrates can be handled by the chemical parser. Review the actual structure card before accepting a name match.',
    'You can locate a reference and inspect its source, formula and structure.',
    'A formula may have several polymorphs or related cards. A text match by itself does not identify the measured structure.', 'search-menu', 'has_candidates', keywords='name formula ID grouped hydrate BaSiO3 Ca3(PO4)2'),
 )),
 C('auto-search', '6 · Automatic Match → Gain', 'Run the actual identification sequence and interpret its states.', (
  S('auto-search.setup', 'Open the compact search setup',
    'Check local availability before calculating.', 'Identify phases → settings arrow',
    'Select the measurement and click the down arrow inside Identify phases to open the compact settings panel. The main part of the button starts identification immediately. Review the local-card count and optional improvements. Existing chemical restrictions remain in the Elements tab instead of being duplicated here.',
    'The setup is open, anchored at the search button, with an understandable available-card count.',
    'Zero cards calls for checking your filters, sources and library. Use the main Identify phases button when you are ready. Refine search repeats identification with current filters; Finish auto search stops it and retains the results.', 'auto-setup', 'auto_setup_open', keywords='identify phases settings arrow local cards refine finish'),
  S('auto-search.profile', 'Choose an appropriate instrument profile',
    'Use relevant radiation and instrumental widths.', 'Search setup → Use instrument profile',
    'Choose an existing saved profile when it describes the measurement. Finder remembers the selection. Add profile opens instrument settings if you need to create one. A wrong broadening model can worsen the comparison; it is an optional improvement rather than a prerequisite for having reference cards.',
    'The intended profile is selected before starting identification.',
    'A saved profile for another diffractometer or wavelength is not interchangeable. The demo provides its own labelled synthetic Cu profile.', 'auto-profile', keywords='instrument profile enhancement remembered widths'),
  S('auto-search.match', 'Find and review the first phase',
    'Use Match to retrieve plausible primary phases.', 'Identify phases → Candidate list → Match score',
    'Run the search and wait for its completion status. Review the top candidates, their cards and reflection positions. Compare several plausible structures instead of accepting the first row automatically. Similar structural types may rank close together; your chemistry and scientific judgement still matter.',
    'Candidates receive calculated Match results or an explicit availability/error state.',
    'A high Match score is not a probability. A missing card, wrong filters, wrong instrument settings or poor peak data can each limit the result.', 'auto-run', 'match_ready', keywords='Match score primary first phase top 10 ranking'),
  S('auto-search.gain', 'Add a further phase with Gain',
    'Search for additional evidence after accepting a phase.', 'Candidate double click → Selected phases → Gain',
    'Accept the best-supported first phase. Once its calculation is ready, inspect Gain for possible additional phases. Check unexplained peaks, overlaps and candidate reflections before adding the next phase. Repeat while useful positive evidence remains; do not keep adding cards merely because the table contains them.',
    'Gain reflects the current accepted phase set and can change after a phase is added or removed.',
    'Gain is neither a mass fraction nor an identification probability. Overlapping/isostructural references can be ambiguous; extra phases require actual support.', 'gain', 'gain_ready', keywords='Gain additional phase residual overlap impurity mixture'),
  S('auto-search.status', 'Tell inactive, busy, unavailable and zero apart',
    'Avoid treating missing work as a negative scientific result.', 'Candidate score cells and bottom status',
    'Read the status and score-cell explanations. Inactive means scoring is not currently active/available. A running task has not finished. No score means no displayed qualifying result in that context. A numerical zero is a calculated number. Check diagnostics for failed or unavailable references.',
    'You can explain why a cell has no number instead of assuming the phase is absent.',
    'After changing data, calibration, filters or accepted phases, previous scores may be cleared or recalculated. Wait for the current task, not a stale result.', 'status', keywords='inactive no score loading failed unavailable zero cancel'),
 )),
 C('phases', '7 · Candidates and selected phases', 'Distinguish a possible card from an accepted component and inspect result meaning.', (
  S('phases.candidates', 'A candidate is a hypothesis',
    'Separate database retrieval from an interpretation you have accepted.', 'Candidate list below the graph',
    'Read Source, Database ID, Formula, Phase name, space group and the available score columns. A row is a retrieved card. It is not automatically a component of the sample. The same composition can have multiple distinct structures or near-equivalent cards.',
    'You use the list for comparison rather than reading it as a composition report.',
    'Formula and phase name are not substitutes for reflection agreement. Keep genuinely distinct structures available for review.', 'candidates', 'has_candidates', keywords='candidate hypothesis source database ID polymorph'),
  S('phases.preview', 'Preview reflections and open the card',
    'Inspect the reference before committing to it.', 'Single click a candidate; Phase details; Entries → Open entry card',
    'Single click a row to preview its reflections and show the reference details. Compare marker positions across the measured range, not only the tallest peak. Use Phase details or Open entry card to inspect the structure and available diffraction information.',
    'The preview/card belongs to the selected database ID.',
    'A transient preview is different from the total calculated profile of accepted phases. Loading/preparation may finish asynchronously.', 'candidate-card', 'candidate_selected', keywords='preview card diffraction reflections structure'),
  S('phases.accept', 'Accept a phase for the active measurement',
    'Build an explicit working interpretation.', 'Double click a candidate; Selected phases table',
    'Double click the candidate you want to add, or use Entries → Add selected to working set. Wait for accepted-phase calculation. Check that the correct measurement is active; acceptance is per measurement, not automatically for every sample in the project.',
    'The phase appears in Selected phases with its colour, fit/peak coverage and any available estimates.',
    'Adding a CIF to the project tree is a separate operation. If calculation fails, inspect its explanation rather than adding repeated copies.', 'candidates', 'has_accepted', keywords='accept selected phases working set add double click'),
  S('phases.edit', 'Remove, rename, recolour or export a phase',
    'Keep an interpretation readable and revise it when evidence changes.', 'Selected phases → right-click menu',
    'Use the selected-phase context menu to remove a phase from the active measurement, change its display colour/name or export its CIF. Removing a phase updates dependent results; it does not delete that reference from the source database.',
    'The selected-phase set and plotted markers correspond to your current interpretation.',
    'Renaming or recolouring is presentation, not a chemical or crystallographic refinement. Save XPFF to retain the chosen interpretation.', 'selected', keywords='remove rename color colour export CIF'),
  S('phases.quant', 'Scores, I/Ic and mass-fraction estimates',
    'Interpret numbers according to their actual meaning.', 'Selected phases → Fit / Peaks, Est. wt.% and I/Ic',
    'Fit/Peaks describes calculated agreement and assigned peaks. Est. wt.% is the available model-based mass fraction estimate, not the Match or Gain score. I/Ic is an ideal calculated reference-intensity estimate. Quant needs compatible structural inputs and separable phase contributions; applied Le Bail intensity adjustment does not supply structural mass fractions.',
    'You distinguish a fit score, reference intensity and quantitative composition estimate.',
    'Unavailable is not zero content. Read the reason for missing Quant; preferred orientation, overlapping phases and model limitations require scientific assessment.', 'selected', keywords='mass fraction quantitative Quant weight percent I/Ic RIR intensity'),
 )),
 C('processing', '8 · Preprocessing and reversibility', 'Preview background, smoothing, crop and angular corrections without losing the source.', (
  S('processing.original', 'Original data versus displayed/scoring data',
    'Know which signal a processing operation affects.', 'Processing tab; original file and project',
    'Select the intended measurement before opening processing. The stored source is retained while working processing can be changed. Display normalization and vertical stacking are not counts corrections. Finder can score automatic preparation or the visible processed signal according to the chosen scoring context.',
    'You distinguish original counts, processed data and display-only scaling.',
    'Do not infer a new measurement from a visually normalized curve. Note the scoring context when comparing results before and after processing.', 'processing', keywords='original raw counts visible Auto scoring context'),
  S('processing.background', 'Estimate and inspect the background',
    'Separate slowly varying background from diffraction features.', 'Processing → Background; Pattern → Automatic → Edit background',
    'Open Background, inspect the preview and adjust the available controls. Compare the estimated background with weak and broad features. Apply accepts the chosen operation; Cancel returns to the state before opening; Reset undoes the stored background-processing step where available.',
    'The chosen background is plausible across the range without swallowing diffraction peaks.',
    'A broad feature may be scientifically meaningful. Opening a panel or seeing a preview does not mean you have committed that processing.', 'background', 'background_panel_open', keywords='SNIP background subtract preview apply cancel reset amorphous'),
  S('processing.smoothing', 'Smooth conservatively and reset it',
    'Reduce noise while checking that peak features remain useful.', 'Processing → Smoothing',
    'Open Smoothing and compare its preview with the original peak shapes. Apply only when the result is appropriate. Use the panel Reset if that smoothing step was unhelpful, rather than reloading the entire sample. The same controls are reached from Pattern → Automatic → Smooth raw data.',
    'You can try smoothing and undo it while retaining the rest of the project.',
    'Smoothing can change weak/close features. It does not recover information that the experiment did not measure.', 'smoothing', 'smoothing_panel_open', keywords='smooth noise reset rollback undo'),
  S('processing.crop', 'Restrict the working range',
    'Focus analysis on a useful angular interval.', 'Processing → Crop XRD',
    'Choose the crop interval on the active measurement and review its preview before applying. The source file is kept. Graph zoom is a view operation; crop changes the working data range used by subsequent processing/search.',
    'You can distinguish a cropped working range from a temporarily zoomed plot.',
    'Cropping away diagnostic peaks may make phases harder to distinguish. The 0–125° navigation bound is not itself a crop of the source file.', 'crop', 'crop_panel_open', keywords='crop angular range zoom source retained'),
  S('processing.zero', 'Angular calibration versus display correction',
    'Avoid applying the same correction twice.', 'Tools → Calibrate pattern; Processing → Zero shift; Correct zero',
    'Calibrate pattern lets you set a total numerical 2θ correction: original angle minus correction. Apply updates the working axis, preserves counts/source, and invalidates dependent searches; rerun them. Correct zero is a display correction and is different from applying a manual calibration to the working data.',
    'You know whether you changed only the view or the working angular coordinates.',
    'A positive manual correction moves peaks left. Reset calibration also rolls back dependent later processing; inspect the result before continuing.', 'calibration-menu', keywords='zero angular calibrate correction specimen displacement'),
  S('processing.reset', 'Use Apply, Cancel, Reset and Reset processing',
    'Recover from an unsuitable processing choice.', 'Processing panels; Reset processing toolbar button',
    'Apply commits the current panel choice. Cancel restores the panel-opening state. Reset returns to that step’s saved checkpoint where offered and clears dependent later edits. Reset processing restores the active original measurement and clears its processing history while retaining the loaded sample and selected phases.',
    'You can revise preprocessing without deleting or reimporting the sample.',
    'Read the scope of the reset you are using. Changed input requires refreshing dependent fit, assignments and search scores.', 'reset-processing', keywords='undo checkpoint rollback reset cancel apply history'),
 )),
 C('instrument', '9 · Instrument and profile improvements', 'Set radiation/widths and understand calibration and limited Le Bail.', (
  S('instrument.saved', 'Choose and save a profile',
    'Reuse one consistent instrument description.', 'Instrument settings',
    'Open Instrument settings and manage reusable profiles through Profiles…. Create, save, import or export a profile there. This window does not change measurements. To change a measurement, open Processing → Instrument and radiation, choose the profile and its scope, then press Apply.',
    'The measurement and future search setup can use the intended saved profile.',
    'A similarly named profile may use a different wavelength or geometry. The demo profile is labelled synthetic and is not your instrument calibration.', 'instrument', 'instrument_open', keywords='instrument saved profile diffractometer apply selected'),
  S('instrument.radiation', 'Radiation components and instrumental widths',
    'Describe the radiation and resolution actually used for measurement.', 'Instrument → Wavelength / Resolution',
    'Review wavelength, monochromatic versus Kα doublet radiation, relative components and the selected width model. The instrument description is used by profile-related calculations; Kα2 is not automatically a second material phase. Resolution parameters describe the instrument, not arbitrary sample broadening.',
    'The radiation and resolution model match the intended experiment.',
    'Parameters from another wavelength or geometry can shift predicted reflections or widths. Do not compensate for a wrong instrument by adding unsupported phases.', 'instrument-radiation', keywords='alpha1 alpha2 Kalpha doublet wavelength TCH U V W X Y resolution'),
  S('instrument.calibration', 'Calibrate resolution from a standard',
    'Estimate instrumental profile parameters from an appropriate reference measurement.', 'Instrument settings → Resolution → Calibrate from standard',
    'Load a measured standard and choose its CIF from a file or configured references. Identify peaks, calculate the whole profile, review the residual and indicators, then use the parameters to create a new unsaved instrument profile. Complete its metadata and save it. The model assumes negligible intrinsic size/strain broadening of the coarse-grained standard.',
    'You understand how a suitable standard supplies an instrument-only broadening estimate.',
    'An ordinary broadened sample is not automatically a calibration standard. Synthetic tutorial data demonstrate controls, not independent experimental calibration accuracy.', 'instrument-resolution', keywords='standard calibration CIF coarse grain instrumental broadening'),
  S('instrument.lebail', 'Use limited Le Bail knowingly',
    'Understand an optional improvement and its quantitative limits.', 'Identify phases setup → Le Bail',
    'Le Bail can adjust accepted CIF-phase descriptions through joint and phase-wise passes with a shared limit of three cycles/two seconds. It retains a validated improvement when available, keeping fixed background/radiation/common zero for that adjustment. This is limited profile improvement, not a full refinement.',
    'An applied Le Bail result is identified as such and does not display structural Quant mass fractions.',
    'Le Bail cannot identify a missing database card or validate an unsupported phase. An unavailable runtime, ambiguity or lack of improvement can retain the ordinary structural fit.', 'auto-lebail', keywords='Le Bail refinement cycles two seconds Quant improvement'),
 )),
 C('peaks', '10 · Peaks and their information', 'Select search evidence, inspect a peak and work without a measured profile.', (
  S('peaks.select', 'Select peaks for Peak search',
    'Search with chosen experimental maxima.', 'Peak search toolbar button; graph',
    'Enter Peak search, left click near maxima to mark them and right click marked maxima to remove those marks. Review tolerance in Processing → Peak search, then run the search from Elements. The selection belongs to the active measurement.',
    'Marked maxima provide the evidence for the following peak search.',
    'Marking maxima alone does not start database retrieval. Clearing selected search peaks clears these marks rather than deleting measured intensity samples.', 'peak-search', 'selected_peaks', keywords='peak search select tolerance mark unmark'),
  S('peaks.find', 'Find peaks automatically, then review',
    'Prepare a search selection more quickly.', 'Pattern → Peak searching → Find peaks',
    'Run Find peaks to add detected maxima to the current search selection. Detection uses the active processed/cropped signal and radiation settings. Inspect marks, remove unwanted ones and add missed ones before searching. Esc or a relevant context/data change cancels pending detection.',
    'The graph shows a reviewed set of maxima; a separate search is still required.',
    'Noise, shoulders and overlaps can limit detection. An automatically marked point is not a confirmed phase assignment.', 'pattern-menu', 'selected_peaks', keywords='Find peaks detect automatic Esc cancel'),
  S('peaks.manual', 'Create a peak list without an XRD file',
    'Use known positions and relative intensities when raw profile data are unavailable.', 'Peaks → Add peak',
    'Add peak can create a manual peak list with an initial 0–125° field and 0–100 intensity. Click the graph or enter exact values in the floating editor. Update/remove selected entries there or use Delete peak. Entered intensities affect height and intensity-weighted Peak search ranking.',
    'Your position/intensity list can be saved in XPFF and used for peak-based search.',
    'Zero-intensity peaks are ignored for ranking. A manual list has no measured widths, integrated areas, background profile or profile-based Quant.', 'peaks-menu', keywords='manual add delete peak list no measurement intensity 0 100'),
  S('peaks.info', 'Inspect local peak shape and area',
    'Examine what a measured feature actually looks like.', 'Peaks → Peak information; Pattern → Profile fitting',
    'Choose Peak information, Fit a peak or Peak area, then click a measured maximum. The movable card shows the local profile, fitted curve and residual with the configured radiation components. Review centre, d-spacing, height, component FWHM, integrated area and asymmetry. Click another peak to reuse the card.',
    'A local fit and its measured characteristics are visible without editing the pattern.',
    'Displayed stacking/normalization is removed from the reported values. The fit measure does not establish phase purity or prove a solid solution.', 'peaks-menu', 'peak_card_open', keywords='FWHM width area shape asymmetric local fit peak information'),
  S('peaks.hkl', 'Read phase and hkl assignments',
    'Connect a measured maximum with current accepted-phase reflections.', 'Peak information card; phase markers',
    'Inspect phase names and h k l in the peak card. They come from the current accepted-phase assignments for that measurement; overlapping assignments can list more than one phase. The marker colour connects the assignment to its selected phase.',
    'You can distinguish a current assignment from an unassigned or unavailable peak.',
    'A preview marker is not an accepted assignment. Recalculate after changing data or phase geometry, and keep overlap ambiguity in mind.', 'selected', keywords='hkl Miller indices assigned overlap phase marker'),
 )),
 C('multi', '11 · Single and multi-pattern views', 'Compare samples while keeping the active analysis context clear.', (
  S('multi.one', 'Display one active measurement',
    'Inspect a sample without a crowded graph.', 'Below graph → Patterns → One',
    'Choose One or double click a measurement row. The graph focuses on that sample and its interpretation. Changing the displayed sample does not merge the accepted-phase sets of other samples.',
    'One sample is displayed and the selected-phase table refers to the intended active sample.',
    'If the curve/table do not appear to agree, inspect the active tree row and the current Patterns mode.', 'patterns', 'single_pattern_mode', keywords='single one active pattern'),
  S('multi.all', 'Compare checked measurements',
    'See a series together.', 'Tree checkboxes; Patterns → All selected',
    'Check at least two measurements and choose All selected. The demo contains a pure-phase signal and a mixture for comparison. Click the intended sample row before running a search; the stack is a display of several measurements, not one combined search target.',
    'Multiple checked patterns appear together.',
    'A group must contain checked measurements. Each sample retains its own phases and processing even when several are displayed.', 'patterns', 'multiple_patterns', keywords='multi all selected stack compare series'),
  S('multi.normalize', 'Normalize and offset a stack',
    'Separate curves visually without confusing their measured intensities.', 'Below graph → Normalize and Offset',
    'Use Normalize to compare shapes on a relative display scale and Offset to separate stacked curves. Compare the same view with normalization on and off. These are display controls rather than a new measurement or a composition calculation.',
    'Curves are readable and you know which display scaling is active.',
    'A visually taller normalized curve does not imply more material. Use the appropriate quantitative model and diagnostics for composition questions.', 'normalize', keywords='normalize intensity vertical offset stacking'),
  S('multi.labels', 'Keep labels, colours and legends useful',
    'Make sample identity clear in a comparison figure.', 'Plot settings; tree names; Selected phases colours',
    'Choose appropriate curve/phase labels and legend options in Plot settings. Give measurements meaningful names and keep the stack order logical. Phase colours connect accepted phases and markers; sample curve colours serve a separate purpose.',
    'A reader can identify samples and phases without guessing.',
    'Long names can crowd a figure. Adjust the available label/legend settings and preview the export at its intended size.', 'plot-settings', keywords='legend labels common individual color sample names'),
 )),
 C('appearance-export', '12 · Appearance, panels and export', 'Set a readable workspace and save the right kind of output.', (
  S('appearance-export.plot', 'Set curves, axes, markers and legends',
    'Control what the graph communicates.', 'Plot settings; View → Plot appearance',
    'Open Plot settings to inspect curve, marker, axis, label, legend and layer options. Enable only the relevant information for the figure. The white scientific canvas and scientific marker/phase colours have a different role from the surrounding light/dark application theme.',
    'The graph shows the intended measurements and interpretation layers.',
    'A hidden calculated curve or marker layer is not a failed calculation. Check visibility settings before rerunning an analysis.', 'plot-settings', 'plot_settings_open', keywords='plot appearance axes axis d spacing marker legend grid layer'),
  S('appearance-export.aspect', 'Fit, aspect ratio, zoom and pan',
    'Use the allocated graph area appropriately.', 'Below graph → Aspect; Fit plot; View → Autoscale / Reset zoom',
    'Choose Fit, 1:1 or a fixed aspect such as 16:9 as appropriate. Zoom/pan for inspection, then use Fit plot to see the full current content again. Aspect controls the canvas proportions; it is different from the measurement’s angular interval or crop.',
    'The graph occupies the intended area with readable axis labels.',
    'Navigation remains within 0–125°. Check crop and display selection if Fit plot does not show data you expected.', 'aspect', keywords='aspect 1:1 16:9 fit plot zoom pan autoscale'),
  S('appearance-export.layout', 'Resize panels and scale the interface',
    'Adapt the workspace to your screen.', 'Edit layout; interface-scale control',
    'Press Edit layout to unlock the panel boundaries, adjust their proportions and table columns, then release it to save and lock them. Use interface scaling to adjust fonts and controls for your display. Plot proportions have their own Aspect setting; saved layout does not freeze scientific X/Y zoom ranges.',
    'The chosen panel/table proportions remain readable when the workspace is resized.',
    'A locked boundary cannot be dragged. Use a supported HD–2K workspace and check both interface scale and plot aspect when space feels wrong.', 'layout', keywords='Edit layout panels pin unlock lock scale fonts HD 2K'),
  S('appearance-export.image', 'Export a figure',
    'Save the plotted view for publication or editing.', 'Graph right click → Export image',
    'Open Export image and review its preview, size, resolution and visible layers. SVG/PDF are vector-oriented outputs; PNG/TIFF/JPG are raster formats. SVG includes named groups/layer metadata for CorelDRAW/Inkscape. Check legends and markers at the intended output size before saving.',
    'The saved figure contains the intended visible curves, labels, legends and markers.',
    'A raster image has fixed pixels; raising size/resolution affects the output. A figure does not retain an editable scientific XPFF interpretation.', 'plot', keywords='export image SVG PDF PNG TIFF JPG JPEG Corel Inkscape resolution dpi'),
  S('appearance-export.csv', 'Export candidates or a structural CIF',
    'Share reference details in the appropriate format.', 'Tools → Export candidate list; candidate/selected-phase right click → Export CIF',
    'Export candidate list writes the displayed candidate table as CSV. Export CIF writes a structural reference when available. Save XPFF when sharing the measured sample together with its interpretation; a table or CIF alone is not the experimental project.',
    'The output format matches the information you intended to share.',
    'Unavailable or inactive score cells should remain understandable in an exported table. Check the database ID, not just the display name, before exporting a structure.', 'tools-menu', keywords='export candidate CSV table CIF structure'),
  S('appearance-export.settings', 'Export settings and preserve the project',
    'Reuse a working configuration and distinguish it from results.', 'Tools → Export settings / Import settings; File → Save project',
    'Use settings export/import to transfer the supported configuration. Save the project separately to retain measurements, notes, phases and compatible calculated results. Review any credentials or personal configuration before sharing a settings bundle.',
    'Configuration transfer and scientific-project saving serve their distinct purposes.',
    'An exported image, settings bundle or candidate list cannot replace an XPFF backup. Keep personal API keys and library contents out of public distributions.', 'tools-menu', keywords='export import settings save project backup'),
  S('appearance-export.planned', 'Recognise planned tools and find help again',
    'Discover functions without mistaking a placeholder for a calculation.', 'Experimental; Help → Learn Finder / Manual',
    'Experimental entries labelled planned are not implemented. Other entries explicitly labelled in development also do not provide a finished analysis. Reopen Learn Finder for any chapter or search for a control name; use Manual for the compact reference. You can pause a chapter and resume later.',
    'You know how to locate help and distinguish available functionality from future tools.',
    'A placeholder does not modify the measurement or calculate a hidden result. Report unexpected behaviour with the action and its exact message.', 'help-menu', keywords='experimental planned facet substrate texture in development help manual'),
 )),
)

from xrd_finder.learning.topics import additional_topics
from xrd_finder.learning.overview import OVERVIEW
_EXTRA_TOPICS=additional_topics(S)
CHAPTERS=tuple(replace(chapter,steps=chapter.steps+_EXTRA_TOPICS.get(chapter.id,())) for chapter in CHAPTERS)

_STEP_CHAPTER = {step.id: chapter for chapter in CHAPTERS for step in chapter.steps}
STEPS = {step.id: step for chapter in CHAPTERS for step in chapter.steps}


def chapter_for(step_id):
    return _STEP_CHAPTER.get(step_id)


def find_steps(query):
    words = re.findall(r'[\w]+', str(query).casefold())
    words = [word for word in words if word not in {'how','why','what','the','to','a','an','is','can','i'}]
    if not words:
        return list(STEPS.values())
    hits=[]
    for step in STEPS.values():
        title=(chapter_for(step.id).title+' '+step.title+' '+step.keywords).casefold()
        body=' '.join((title,step.purpose,step.where,step.instruction,step.expected,step.troubleshooting)).casefold()
        if all(word in body for word in words):
            hits.append((sum(5 if word in title else 1 for word in words),step))
    hits.sort(key=lambda item:-item[0])
    return [step for _,step in hits]


ASSISTANT_ROUTES = {
 'complete':('Complete Finder workflow with my XRD',tuple(
     step.id for chapter_id in ('projects','tree','databases','library','manual-search','processing',
                               'instrument','auto-search','phases','peaks','multi','appearance-export')
     for step in next(chapter for chapter in CHAPTERS if chapter.id==chapter_id).steps
     if step.id not in {'projects.import','projects.save'})+('projects.save',)),
 'overview':('Quick overview of all Finder areas',tuple(OVERVIEW)),
 'identify':('Analyse and identify phases in my XRD',('tree.active','databases.sources','databases.paths',
              'databases.credentials','library.bulk','manual-search.elements','manual-search.gate',
              'library.manual','processing.original','processing.background','processing.smoothing',
              'processing.crop','processing.zero','processing.reset','instrument.saved','instrument.radiation',
              'instrument.calibration','instrument.lebail','auto-search.setup',
              'auto-search.profile','auto-search.match','phases.preview','phases.accept',
              'auto-search.gain','phases.quant','peaks.info','peaks.hkl','appearance-export.plot',
              'appearance-export.image','projects.save')),
 'library':('Search manually / build my library',('databases.sources','databases.paths','databases.credentials',
              'manual-search.elements','manual-search.gate','manual-search.run','manual-search.formula',
              'library.import','library.manual','library.audit')),
 'processing':('Prepare or correct my pattern',('processing.background','processing.smoothing','processing.crop',
              'processing.zero','processing.reset','projects.save')),
 'instrument':('Set up an instrument profile',('instrument.saved','instrument.radiation',
              'instrument.calibration','instrument.lebail')),
 'peaks':('Search and inspect peaks',('peaks.select','peaks.find','manual-search.run','peaks.info','peaks.hkl','peaks.manual')),
 'compare':('Compare my measurements',('tree.visibility','tree.series','tree.order','multi.all',
              'multi.normalize','multi.labels','multi.one')),
 'export':('Prepare and export my figure',('appearance-export.plot','appearance-export.aspect',
              'appearance-export.layout','appearance-export.image','appearance-export.csv',
              'appearance-export.settings')),
 'project':('Organise and save my project',('projects.import','projects.cif','tree.series','tree.order',
              'projects.notes','projects.save')),
}


def route_steps(route_id,*,has_pattern,has_library):
    steps=list(ASSISTANT_ROUTES[route_id][1])
    if route_id=='overview':return steps
    if not has_pattern and steps[0]!='projects.import':steps.insert(0,'projects.import')
    if has_pattern:steps=[key for key in steps if key!='projects.import']
    if route_id=='identify' and not has_library:
        position=steps.index('auto-search.setup')
        steps[position:position]=[key for key in ('library.empty','library.import') if key not in steps]
    return steps


def upgrade_route(route_id,step_ids):
    """Saved short routes must not keep skipping the newly required setup decisions."""
    steps=list(step_ids)
    if route_id=='identify' and 'auto-search.setup' in steps:
        required=ASSISTANT_ROUTES['identify'][1]
        for key in required[:required.index('auto-search.setup')]:
            if key not in steps:steps.insert(steps.index('auto-search.setup'),key)
    return steps


SHORT_PROMPTS={
 'projects.import':'Click Import data and choose your XRD file. Your current project will not be replaced.',
 'tree.active':'Click the measurement you want to analyse in the project tree.',
 'manual-search.elements':'Select only the elements you know are present. Left click requires; right click excludes. Use Skip if chemistry is unknown.',
 'manual-search.gate':'Choose Allow others if unknown components are possible, or Exclude others for a known complete element set.',
 'library.empty':'Click Identify phases once and inspect Local cards available. Zero cards needs references or less restrictive filters.',
 'library.manual':'Before auto search, check references for this sample using manual formula/name or Elements search. Retrieve suitable CIFs, or import your own. A nonempty database can still lack your material family. Confirm only after reviewing this, or use Skip deliberately.',
 'library.import':'Import suitable CIFs with Import data. Continue once a usable local reference is prepared; no extra import is needed if retrieval already supplied it.',
 'auto-search.setup':'Click the down arrow inside Identify phases. Review Local cards available in the setup below it.',
 'auto-search.profile':'Choose your saved instrument profile if available. Otherwise retain the current basic setup and continue.',
 'auto-search.match':'Click Identify phases. Wait for Match, then review the top candidates.',
 'phases.preview':'Click a candidate once. Compare its reflections with your measured peaks.',
 'phases.accept':'Double click the candidate that you judge to be supported. This adds it to Selected phases.',
 'auto-search.gain':'Wait for Gain and inspect additional candidates. Add another phase only when the evidence supports it; no positive Gain is a valid stopping point.',
 'phases.quant':'Review Selected phases. Fit/Peaks, Est. wt.% and I/Ic describe different things; use ? for their meanings.',
 'projects.save':'Use Save or File → Save project as to retain this interpretation in XPFF.',
 'databases.sources':'Open Manage databases and inspect which sources are enabled and ready.',
 'databases.paths':'Inspect the database location and its tooltip. This is where your local reference library is stored.',
 'databases.credentials':'Configure only sources you intend to use. API keys, licences or a local collection may be required.',
 'manual-search.run':'Click Search database in Elements. Inspect the returned candidates.',
 'manual-search.formula':'Use Search → Search by formula/name for a known composition, compound name or card ID.',
 'processing.background':'Open Background and inspect the preview. Use Apply only if appropriate; Cancel or Reset can undo a choice.',
 'processing.smoothing':'Try Smoothing on your sample. Inspect weak peaks before you Apply; Reset can undo smoothing.',
 'processing.crop':'Choose a useful working angular range in Crop XRD. Zooming alone does not crop the data.',
 'processing.zero':'Use Tools → Calibrate pattern only if you intend to change the working angular scale.',
 'processing.reset':'Use Reset for a processing step, or Reset processing for the active original measurement.',
 'instrument.saved':'Open Instrument settings and inspect or select the profile for this measurement.',
 'instrument.radiation':'Review wavelength, Kα components and Resolution before applying a profile.',
 'instrument.calibration':'Use Resolution → Calibrate from standard only with a suitable standard measurement and its CIF.',
 'instrument.lebail':'If desired, enable Le Bail in search setup. It is limited improvement and does not supply structural Quant.',
 'peaks.select':'Click Peak search, then left click maxima to mark and right click marked maxima to unmark.',
 'peaks.find':'Use Pattern → Peak searching → Find peaks; review the marks before searching.',
 'peaks.info':'Choose Peaks → Peak information and click a measured maximum.',
 'peaks.hkl':'Inspect the peak card for current phase and hkl assignments. Overlaps may have several assignments.',
 'peaks.manual':'Use Peaks → Add peak when you need a position/intensity list, including without a measured profile.',
 'multi.all':'Check at least two measurements, then choose Patterns → All selected.',
 'multi.one':'Choose Patterns → One, or double click a measurement to display it alone.',
 'multi.normalize':'Try Normalize and Offset to make the comparison readable. These do not create new measured counts.',
 'appearance-export.plot':'Open Plot settings and choose the curves, markers, axes and legends you want.',
 'appearance-export.layout':'Press Edit layout, adjust panel proportions, then release it to save and lock them.',
 'appearance-export.image':'Right click the graph → Export image. Inspect the preview and save the required format.',
 'appearance-export.csv':'Use Tools → Export candidate list for CSV; use a phase context menu to export its CIF.',
}


def short_prompt(step):
    return SHORT_PROMPTS.get(step.id,step.instruction.split('. ')[0]+'.')
