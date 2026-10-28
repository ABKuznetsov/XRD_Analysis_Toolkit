"""A movable, modeless measurement card over the existing Finder workspace."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QPixmap, QColor
from PySide6.QtWidgets import QLabel, QFormLayout, QHBoxLayout, QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea
import pyqtgraph as pg

from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog, scrollable_dialog_body
from xrd_finder.ui.xrd_plot import create_xrd_plot_widget


class PeakInformationDialog(ScreenBoundDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle('Peak information')
        self.resize(800, 750)
        self.data = None
        self.pattern_id = ''
        self._phase_lines = []
        layout = scrollable_dialog_body(self)
        scroll = self.findChild(QScrollArea)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: 0; }')
        scroll.viewport().setAutoFillBackground(False)
        scroll.widget().setAutoFillBackground(False)
        self.pattern_label = QLabel()
        self.pattern_label.setTextFormat(Qt.TextFormat.PlainText)
        self.pattern_label.setWordWrap(True)
        self.pattern_label.setProperty('uiRole', 'sectionTitle')
        layout.addWidget(self.pattern_label)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.profile_plot = create_xrd_plot_widget()
        self.profile_plot.setTitle(None)
        self.profile_plot.setFixedHeight(210)
        self.profile_plot.addLegend(labelTextColor='#111111')
        self.profile_plot.hideAxis('bottom')
        self.residual_plot = create_xrd_plot_widget()
        self.residual_plot.setTitle(None)
        self.residual_plot.setFixedHeight(100)
        self.residual_plot.setXLink(self.profile_plot)
        layout.addWidget(self.profile_plot)
        layout.addWidget(self.residual_plot)
        forms = QHBoxLayout()
        columns = [QFormLayout(), QFormLayout()]
        for column in columns:
            column.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            forms.addLayout(column)
        self.metrics = {}
        for index, (key, caption) in enumerate((
            ('maximum', 'Measured maximum 2θ (°)'), ('center', 'Fitted center 2θ (°)'),
            ('d', 'Measured d (Å)'), ('wavelength', 'Wavelength (Å)'),
            ('height', 'Height above background'), ('width', 'Component FWHM (°)'),
            ('area', 'Integrated area (units · °)'), ('quality', 'Local fit score'),
            ('asymmetry', 'Area asymmetry'),
        )):
            label = QLabel('—')
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            columns[0 if index < 4 else 1].addRow(caption, label)
            self.metrics[key] = label
        self.metrics['quality'].setToolTip('Reduction of squared error relative to a local linear background; not phase probability.')
        self.metrics['width'].setToolTip('Width of the fitted profile component. Radiation satellites are modeled separately.')
        self.metrics['d'].setToolTip('Bragg d-spacing from the measured fitted center and the primary wavelength; display zero correction is not applied.')
        layout.addLayout(forms)
        self.assignment_status = QLabel()
        self.assignment_status.setWordWrap(True)
        layout.addWidget(self.assignment_status)
        self.assignments_table = QTableWidget(0, 5)
        self.assignments_table.setHorizontalHeaderLabels(['Phase', 'Database ID', 'h k l', 'Calc. 2θ (°)', 'Δ2θ (°)'])
        self.assignments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.assignments_table.verticalHeader().hide()
        self.assignments_table.setMinimumHeight(85)
        self.assignments_table.setMaximumHeight(130)
        self.assignments_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.assignments_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.assignments_table)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)
        hint = QLabel('The local profile includes the configured radiation components and a linear background. '
                      'Positions use the measured axis; display stacking and normalization are removed. '
                      'One peak cannot establish phase purity or identify a solid solution.')
        hint.setWordWrap(True)
        hint.setProperty('uiRole', 'muted')
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        self.layout().addWidget(buttons)

    def set_data(self, data, pattern_id, pattern_name):
        self.data, self.pattern_id = data, pattern_id
        self.pattern_label.setText(pattern_name)
        self.status_label.setText(data.status)
        fit = data.fit
        values = dict(maximum=data.maximum_position, center=fit.two_theta if fit else None,
            d=data.d_spacing, wavelength=data.wavelength, height=fit.height if fit else None,
            width=fit.fwhm_observed if fit else None, area=fit.area if fit else None,
            quality=fit.fit_quality if fit else None, asymmetry=fit.asymmetry if fit else None)
        for key, value in values.items():
            self.metrics[key].setText('—' if value is None else f'{value:.6g}')
        self.profile_plot.clear()
        self.residual_plot.clear()
        self._phase_lines = []
        self.profile_plot.plot(data.x, data.y, pen=pg.mkPen('#222222', width=1.2), symbol='o',
            symbolSize=3, symbolBrush='#222222', symbolPen=None, name='Measured')
        if fit is not None:
            self.profile_plot.plot(data.x, data.model, pen=pg.mkPen('#087f69', width=1.6), name='Local fit')
            self.profile_plot.plot(data.x, data.background, pen=pg.mkPen('#8c7853', style=Qt.PenStyle.DashLine), name='Background')
            self.residual_plot.plot(data.x, data.y-data.model, pen=pg.mkPen('#7e57c2', width=1.2))
        self.residual_plot.addItem(pg.InfiniteLine(0., angle=0, pen=pg.mkPen('#999999', style=Qt.PenStyle.DashLine)))
        self.profile_plot.autoRange(padding=.03)
        self.residual_plot.autoRange(padding=.03)
        self.warning_label.setText('\n'.join(data.warnings))

    def set_assignments(self, assignments, available, colors=None):
        for line in self._phase_lines:
            self.profile_plot.removeItem(line)
        self._phase_lines = []
        colors = colors or {}
        self.assignments_table.setRowCount(len(assignments))
        observed = self.data.fit.two_theta if self.data.fit is not None else self.data.maximum_position
        for row, assignment in enumerate(assignments):
            hkl = tuple(assignment.hkl)
            values = [assignment.phase_name, assignment.candidate_key,
                ' '.join(map(str, hkl)) if any(hkl) else 'Not indexed',
                f'{assignment.calc_two_theta:.5f}', f'{observed-assignment.calc_two_theta:+.5f}']
            for column, value in enumerate(values):
                self.assignments_table.setItem(row, column, QTableWidgetItem(value))
            color = colors.get(assignment.candidate_key, ('#d93025', '#1a73e8', '#188038')[row % 3])
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(color))
            self.assignments_table.item(row, 0).setIcon(QIcon(swatch))
            line = pg.InfiniteLine(assignment.calc_two_theta, angle=90,
                pen=pg.mkPen(color, width=1., style=Qt.PenStyle.DotLine))
            self.profile_plot.addItem(line, ignoreBounds=True)
            self._phase_lines.append(line)
        self.assignment_status.setText(
            'Current accepted-phase assignments (several phases may overlap):' if assignments else
            'Unassigned peak in the current accepted-phase model.' if available else
            'Current phase/hkl assignments are not available. Accept phases and wait for their profile calculation.'
        )

    def showEvent(self, event):
        super().showEvent(event)
        density = getattr(self, '_ui_density_factor', 1.)
        font = QFont()
        font.setPointSizeF(max(5., 9.*density))
        for plot, label in ((self.profile_plot, 'Intensity'), (self.residual_plot, 'ΔI')):
            for name in ('left', 'bottom'):
                plot.getAxis(name).setTickFont(font)
            plot.setLabel('left', label, color='#111111', **{'font-size': f'{max(5.,10.*density)}pt'})
        self.profile_plot.plotItem.legend.setLabelTextSize(f'{max(5.,9.*density)}pt')
        self.residual_plot.setLabel('bottom', 'Measured 2θ (°)', color='#111111', **{'font-size': f'{max(5.,10.*density)}pt'})
