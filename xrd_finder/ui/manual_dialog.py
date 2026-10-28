"""A bundled offline guide to the workflows available in Finder."""
from PySide6.QtCore import QEvent
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QDialogButtonBox, QTextBrowser, QVBoxLayout

from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog
from xrd_finder.ui.theme import theme_colors


MANUAL_HTML = """
<h1>XRD Phase Finder — User manual</h1>
<p><a href="#project">Projects</a> · <a href="#processing">Processing</a> ·
<a href="#search">Search</a> · <a href="#phases">Phases</a> ·
<a href="#peaks">Peak information</a> · <a href="#export">Export</a></p>

<h2 id="project">Projects and measurements</h2>
<p>Use <b>New project</b> to start, <b>Open project</b> to load an .xpff file,
and <b>Import data</b> to add XRD measurements or CIF structures.
Use <b>Save</b> or <b>Save project as</b> to keep the interpretation in an .xpff project.</p>
<p>Select a measurement row in the project tree to make it active.
Checkboxes control which patterns, structures or series are displayed.
Double-click a measurement to display it alone. Use <b>Add series</b> and the
tree's context menu to organise measurements and structures.
The <b>Up</b> and <b>Down</b> controls change display order.</p>
<p><b>Database → Project phases</b> reveals imported CIF structures in the existing
project tree. This does not change their visibility or the active measurement.
Search candidates are added separately to the active measurement's <b>Selected phases</b> table.</p>
<p><b>Edit → Sample ID, Sample date/time, Sample notes</b> records the active sample's
identifier, measurement date and synthesis or preparation notes. These fields are saved
with that measurement. An unknown measurement date can stay empty.</p>
<h2>Manual peaks without a measured pattern</h2>
<p><b>Peaks → Add peak</b> creates a separate manual peak list, or reopens the active
manual list. Its initial field is <b>0–125°</b> and <b>0–100 intensity</b>.
Click the graph to add a peak at that position and intensity, or type exact values
in the floating editor. Use <b>Update selected</b>, <b>Remove selected</b>, right-click,
or <b>Peaks → Delete peak</b> to edit the list. Close the editor or press Esc to leave input mode.</p>
<p>Manual peak positions and intensities are saved in .xpff without a source XRD file.
<b>Peak search</b> ranks candidates by the fraction of entered intensity explained
by matching positions. Stronger peaks have greater weight. Zero-intensity entries
remain editable but are ignored in searching. This compares weighted position coverage,
not agreement with theoretical intensity ratios. A manual list has no measured line
profile, so widths, areas, background processing and profile Quant are unavailable.</p>

<h2 id="processing">Processing and plot controls</h2>
<p>Open <b>Processing</b> for <b>Smoothing</b>, <b>Background</b> and <b>Crop XRD</b>.
The corresponding <b>Pattern</b> menu entries open these same controls.
Opening a background panel may show a live preview; use the panel's buttons to
apply, cancel or reset the processing.</p>
<ul>
<li><b>Apply</b> commits the current processing settings.</li>
<li><b>Cancel</b> restores the state from when that panel was opened.</li>
<li><b>Reset</b>, where available, rolls back that processing step using its saved checkpoint.</li>
<li><b>Reset processing</b> restores the active original measurement and clears its processing history.</li>
</ul>
<p><b>Zero shift</b> shows the refined zero and an additional visual correction.
The visual correction requires <b>Correct zero</b>; it changes the display,
not peak assignments or scientific calculations.</p>
<p><b>Tools → Calibrate pattern</b> opens manual angular calibration for the active
measured profile. Enter the <b>total</b> correction numerically or with the arrows
(step 0.01°). The corrected angle is original 2θ minus correction; a positive
value moves peaks left. The plot previews the working axis, temporarily pausing
display-only zero correction. <b>Cancel</b> restores the previous display.</p>
<p><b>Apply</b> updates the working angular coordinates, background and crop intervals,
preserving measured intensities and the source file. Accepted phases are recalculated;
previous search scores and peak marks are cleared. Run Identify phases or Peak search
again for scores on the corrected axis. Repeating the same correction does not
add it again. The correction is saved in .xpff. <b>Reset</b> undoes this calibration
and any later dependent processing. This is a manual alignment, not an automatic
instrument calibration. Manual peak lists are edited through their peak editor.</p>
<p><b>Patterns</b> chooses one measurement or all checked measurements.
<b>Aspect</b> controls how the plot fits its area. <b>Normalize</b> and <b>Offset</b>
control the displayed intensities and stacking. <b>Fit plot</b>, <b>View → Autoscale</b>
and <b>Reset zoom</b> restore the full plotted range.</p>
<p>Plot navigation is bounded to <b>0–125°</b> in all modes. When a loaded file extends
outside this range, Finder warns you. The complete measured data and source file are retained;
the range limit controls viewing only.</p>
<p><b>Plot settings</b> controls curves, markers, labels and legends.
<b>Edit layout</b> unlocks panel movement; lock it again to keep the adjusted layout.</p>

<h2 id="search">Finding candidate phases</h2>
<p>Configure sources in <b>Manage databases</b>. Online services require their
configured access and a network connection. Offline mode uses local libraries,
SQL indexes and downloaded caches. <b>Database → Materials Project</b> opens its
settings, including the API-key field.</p>
<p>In <b>Elements</b>, left-click an element to require it (blue), right-click to
exclude it (pink), and leave it optional (green) when it may be present.
Use the same mouse button again to clear that element's selection.
The <b>Allow others / Exclude others</b> control changes how the remaining elements are treated.</p>
<p><b>Identify phases</b> searches using the active pattern.
<b>Search → Search by formula</b> sends a formula through the enabled local and online sources.
<b>Search by elements</b> opens the chemical filters and uses the selected elements.</p>
<p><b>Peak search</b> enters the existing manual selection mode:
left-click close to an experimental maximum to mark it, and right-click a marked
maximum to unmark it. Adjust the tolerance in <b>Processing → Peak search</b>, then
run the search from the element panel. <b>Clear selected search peaks</b> clears
only this selection for the active measurement.</p>
<p><b>Pattern → Peak searching → Find peaks</b> automatically marks up to 80 detected
maxima in the active displayed pattern and adds them to the existing search selection.
It uses the current crop and processing, removes display stacking and intensity scaling,
and uses the configured radiation profile. It does not start a database search.
The task runs in the background; <b>Esc</b>, clearing the selection, changing data or
leaving peak-search mode cancels it. Manually review the marks, then run <b>Peak search</b>.</p>
<p><b>Match score</b> describes the configured comparison with the measurement.
<b>Gain</b> ranks additional peak evidence after accepting phases.
These scores are not identification probabilities or mass fractions.
<b>Inactive</b> means that scoring is disabled or unavailable; it is different from a calculated zero.
Check the displayed status when a result is loading, incomplete or failed.</p>

<h2 id="phases">Reviewing and accepting phases</h2>
<p>Click a candidate to preview its reflections and reference card.
Double-click to add it to <b>Selected phases</b>. The accepted-phase calculation
updates the profile, assignments and available estimates in the background.
The reference card is also available through <b>Entries → Open entry card</b>.</p>
<p>Use the selected-phase context menu to rename a phase, change its plot colour,
export a CIF or remove it from the active measurement. Add a candidate's CIF
to the project through <b>Entries</b> when it should appear in the project tree.</p>
<p><b>Est. wt.%</b> is available only when the current quantitative model can supply
an estimate. Read its diagnostics when an estimate is unavailable.
A missing result must not be interpreted as zero content.</p>

<h2 id="peaks">Inspecting a peak and its area</h2>
<p>Choose <b>Peaks → Peak information</b>, <b>Pattern → Profile fitting → Fit a peak</b>
or <b>Peak area</b>, then click an experimental maximum.
A movable card opens over Finder. In a stack of curves, click the desired curve's peak.</p>
<p>The card shows the measured local profile, a local fit with the configured radiation
components and a linear background, and the residual. It reports the measured maximum,
fitted centre, measured d-spacing, wavelength, height, component FWHM, fitted integrated
area, fit score and asymmetry. Normalisation and stack offsets are removed from its
intensity values. Its positions use the measured axis.</p>
<p>Phase names and <b>h k l</b> come from the current accepted-phase assignments for
that measurement. All recorded overlapping assignments are listed. Without a current
assignment, the card says that it is unavailable or that the peak is unassigned.</p>
<p>Click another peak to update the same card. Close the card, press <b>Esc</b>, or
right-click the main plot to exit this mode. Inspection does not edit the pattern
or phase selection. The fit score is a local fit measure, not a phase probability.
The card does not classify a sample as a pure phase or a solid solution.</p>

<h2 id="export">Saving figures and candidate lists</h2>
<p>Right-click the main plot and choose <b>Export image</b> to configure a figure.
Available formats include SVG, PDF, PNG, TIFF and JPG.
SVG contains named groups and layer metadata for vector editors.
Review the preview and settings before saving.</p>
<p><b>Tools → Export candidate list</b> saves the displayed candidate table as CSV.
<b>Export settings / Import settings</b> transfers Finder settings.
Save the .xpff project to retain the measurement interpretation and sample notes.</p>

<h2>Experimental tools</h2>
<p><b>Experimental</b> lists planned Facet Indexing, Substrate Peak Suppression and
Texture Suppression tools. Entries labelled <b>planned</b> are not implemented in
the current version. They do not run calculations or change a measurement.</p>
"""


class ManualDialog(ScreenBoundDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Finder manual')
        self.resize(760, 700)
        layout = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setAccessibleName('Finder user manual')
        self.browser.setOpenExternalLinks(False)
        self.browser.setHtml(MANUAL_HTML)
        self.browser.installEventFilter(self)
        layout.addWidget(self.browser, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _refresh_link_color(self):
        dark = self.browser.palette().color(QPalette.ColorRole.Base).lightness() < 128
        color = theme_colors(dark)['link']
        if color == getattr(self, '_manual_link_color', None):
            return
        self._manual_link_color = color
        position = self.browser.verticalScrollBar().value()
        self.browser.document().setDefaultStyleSheet(f'a {{ color: {color}; }}')
        self.browser.setHtml(MANUAL_HTML)
        self.browser.verticalScrollBar().setValue(position)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_link_color()

    def eventFilter(self, watched, event):
        if watched is self.browser and event.type() == QEvent.Type.PaletteChange:
            self._refresh_link_color()
        return super().eventFilter(watched, event)
