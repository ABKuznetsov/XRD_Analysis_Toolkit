"""Concrete organic/MOF sources on top of the common connection manager."""
from dataclasses import replace
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox,QFileDialog,QHBoxLayout,QLabel,QPushButton,QVBoxLayout

from xrd_finder.services.curated_libraries import PRESETS,preset_connection
from xrd_finder.services.library_connections import LibraryConnection,load_connections,save_connections
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


SOURCES = (
    ('core_mof','CoRE MOF SI · metal-organic frameworks'),
    ('curated_cofs','CURATED COFs · organic frameworks'),
    ('qmof','QMOF · DFT-relaxed metal-organic frameworks'),
    ('cod_organic','COD · organic and metal-organic crystals'),
    ('omdb','OMDB · organic molecular crystals'),
)


class ReadyLibrariesDialog(ScreenBoundDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner
        self.setWindowTitle('Organic and MOF databases');self.resize(740,390)
        layout=QVBoxLayout(self)
        self.source=QComboBox()
        for key,label in SOURCES:self.source.addItem(label,key)
        layout.addWidget(self.source)
        self.description=QLabel();self.description.setWordWrap(True);self.description.setOpenExternalLinks(True)
        self.description.setTextFormat(Qt.TextFormat.RichText)
        self.description.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.description,1)
        self.note=QLabel('Downloaded CIFs are prepared in background processes and cached for local search, Match and Gain. '
                         'No database is included in the installer. Your current element restrictions are preserved.')
        self.note.setWordWrap(True);layout.addWidget(self.note)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        self.connect_button=QPushButton();self.connect_button.clicked.connect(self.connect_source)
        self.import_button=QPushButton('Import CIF ZIP…');self.import_button.clicked.connect(self.import_zip)
        source_button=QPushButton('Open source');source_button.clicked.connect(self.open_source)
        close=QPushButton('Close');close.clicked.connect(self.close)
        for button in (self.connect_button,self.import_button,source_button,close):buttons.addWidget(button)
        self.source.currentIndexChanged.connect(self._update);self._update()

    def _update(self):
        key=self.source.currentData()
        if key in PRESETS:
            preset=PRESETS[key];description=preset.description;self.source_url=preset.record_url
        elif key=='core_mof':
            self.source_url='https://zenodo.org/records/15055758'
            description=('CoRE MOF SI 2024: 2,664 computation-ready CIF structures. Download: 44 MB. '
                'ASR / FSR / ion-containing variants are retained; the authors’ non-ready subset is excluded. '
                'These are processed structures, not measured powder profiles.')
        elif key=='cod_organic':
            self.source_url='https://www.crystallography.net/cod/'
            description=('Search COD for organic and metal-organic crystals by formula, name or selected elements. '
                'No API key is needed. This enables Organic and CIF structures and uses the existing COD online connection. '
                'Downloaded cards keep their original COD numbers; no second copy of COD is created. '
                'Finder classifies organic compounds by the presence of both C and H.')
        else:
            self.source_url='https://omdb.mathub.io/dataset'
            description=('OMDB-GAP1 v1.1: 12,500 organic molecular crystals. Download currently requires a personal login on the OMDB website. '
                'Open source, sign in and download the dataset. Extract its CIF collection, then import a CIF ZIP here '
                'or connect the extracted CIF folder under Add / manage database connections. '
                'No automatic web login is performed. Only crystal CIFs can be prepared; a properties table or isolated molecule is insufficient.')
        dark=getattr(self.owner,'_is_dark_theme',lambda:False)()
        link_color='#79cfff' if dark else '#145ca6'
        self.description.setText(escape(description)+'<br><br><a style="color:'+link_color+'" href="'+
            escape(self.source_url,quote=True)+'">Source, authors and terms</a>')
        self.connect_button.setText('Use organic search' if key=='cod_organic' else 'Open download page' if key=='omdb' else 'Download and prepare…')
        self.import_button.setVisible(key!='cod_organic')

    def open_source(self):
        QDesktopServices.openUrl(QUrl(self.source_url))

    def _enable_organic(self, *, only=False):
        self.owner.organics_checkbox.setChecked(True)
        if only:self.owner.inorganics_checkbox.setChecked(False)
        self.owner.structural_data_checkbox.setChecked(True)

    def _save_connection(self,connection):
        connections=load_connections(self.owner.settings)
        connections=[c for c in connections if c.source!=connection.source]+[connection]
        save_connections(self.owner.settings,connections)
        self.owner._refresh_custom_source_names()
        manager=getattr(self.owner,'_library_connections_dialog',None)
        if manager is not None:manager.refresh()

    def connect_source(self):
        key=self.source.currentData()
        if key=='omdb':self.open_source();return
        self._enable_organic(only=key=='cod_organic')
        if key=='cod_organic':
            self.owner._set_source_enabled('sources/cod_online',True)
            self.owner._show_menu_panel(self.owner.composition_panel)
            self.owner._set_background_status('Organic COD enabled. Choose elements and Search database, or use Search → Search by formula.')
            self.close();return
        if key=='core_mof':self.owner._prepare_core_mof_library()
        else:
            connection=preset_connection(key);self._save_connection(connection)
            self.owner._prepare_library_connection(connection)

    def import_zip(self):
        key=self.source.currentData()
        path,_=QFileDialog.getOpenFileName(self,'Original CIF library archive',str(Path.home()),'CIF ZIP (*.zip)')
        if not path:return
        self._enable_organic()
        if key=='core_mof':self.owner._prepare_core_mof_library(archive_path=path);return
        if key in PRESETS:
            connection=replace(preset_connection(key),kind='zip',location=path)
        else:
            connection=LibraryConnection(name='OMDB CIFs',source='LIB_4F4D44420001',kind='zip',location=path)
        self._save_connection(connection);self.owner._prepare_library_connection(connection)
