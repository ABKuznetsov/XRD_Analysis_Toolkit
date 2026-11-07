"""Optional learning invitation after the main window is ready."""
import os
from pathlib import Path

from PySide6.QtCore import QObject,Qt,QTimer
from PySide6.QtWidgets import QApplication,QCheckBox,QDialog,QHBoxLayout,QLabel,QPushButton,QScrollArea,QVBoxLayout,QWidget
from PySide6.QtSvgWidgets import QSvgWidget
from shiboken6 import isValid

from xrd_finder.ui.theme import FINDER_BRAND_BLUE, colored_hover_background, theme_colors


OFFER_SETTING='learning/offer_on_startup'


class LearningWelcomeDialog(QDialog):
    def __init__(self,window):
        super().__init__(window)
        self.owner=window
        self.setObjectName('learningWelcome')
        self.setProperty('independentUiScale',True)
        self.setWindowTitle('Explore XRD Phase Finder')
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(self.windowFlags()|Qt.WindowType.Tool)
        self.resize(660,510);self.setMinimumSize(430,420)
        outer=QVBoxLayout(self);outer.setContentsMargins(24,20,24,20);outer.setSpacing(14)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.NoFrame)
        body=QWidget();scroll.setWidget(body);outer.addWidget(scroll,1)
        layout=QVBoxLayout(body);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        self.illustration=QSvgWidget(str(Path(__file__).parent/'assets/learning-welcome.svg'))
        self.illustration.setMinimumHeight(145);self.illustration.setMaximumHeight(185)
        self.illustration.setAccessibleName('Learning illustration: diffraction plot, highlighted control and help card')
        layout.addWidget(self.illustration)
        self.heading=QLabel('Discover Finder')
        self.heading.setObjectName('welcomeTitle');self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.description=QLabel('Discover the tools, or analyse your own XRD step by step. Follow the highlights and open explanations whenever you need them.')
        self.description.setObjectName('welcomeDescription');self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.location_note=QLabel('Find the assistant any time: <b>Help → Learn Finder</b>.')
        self.location_note.setWordWrap(True);self.location_note.setObjectName('welcomeLocation')
        layout.addWidget(self.location_note)
        self.dont_show_again=QCheckBox("Don't show again")
        row=QHBoxLayout();outer.addLayout(row)
        self.overview_button=QPushButton('Quick overview')
        self.workflow_button=QPushButton('Guided workflow')
        self.skip_button=QPushButton('Skip for now')
        self.skip_button.setToolTip("Offer again next launch unless Don't show again is checked.")
        for button in (self.overview_button,self.workflow_button):
            button.setMinimumHeight(44);row.addWidget(button,1)
        self.overview_button.setObjectName('welcomePrimary')
        self.skip_button.setObjectName('welcomeSkip')
        footer=QHBoxLayout();outer.addLayout(footer)
        footer.addWidget(self.dont_show_again);footer.addStretch(1);footer.addWidget(self.skip_button)
        c=theme_colors(widget=window)
        self.setStyleSheet(f'''
            QDialog#learningWelcome, QScrollArea, QScrollArea > QWidget > QWidget {{ background:{c['panel']}; }}
            QLabel {{ color:{c['text']}; background:transparent; font-size:15px; }}
            QLabel#welcomeTitle {{ font-size:28px; font-weight:700; }}
            QLabel#welcomeDescription {{ font-size:17px; }}
            QLabel#welcomeLocation {{ color:{c['muted']}; font-size:14px; }}
            QCheckBox {{ color:{c['muted']}; font-size:14px; spacing:8px; }}
            QCheckBox::indicator {{ width:18px; height:18px; }}
            QPushButton {{ color:{c['text']}; background:{c['alt']}; border:1px solid {c['border']};
                border-radius:8px; font-size:15px; font-weight:600; padding:7px 14px; }}
            QPushButton:hover {{ border-color:{FINDER_BRAND_BLUE}; background:{c['hover']}; }}
            QPushButton#welcomePrimary {{ background:#087f69; color:white; border-color:#119b7f; }}
            QPushButton#welcomePrimary:hover {{ background:{colored_hover_background('#087f69')}; border-color:#119b7f; }}
            QPushButton#welcomeSkip {{ background:transparent; border:0; color:{c['muted']}; font-weight:400; font-size:14px; }}
        ''')
        self.overview_button.clicked.connect(lambda:self._start('overview'))
        self.workflow_button.clicked.connect(lambda:self._start('complete'))
        self.skip_button.clicked.connect(self.reject)
        self.finished.connect(self._remember)

    def showEvent(self,event):
        available=self.screen().availableGeometry()
        width=max(300,available.width()-32);height=max(240,available.height()-48)
        self.setMinimumSize(min(430,width),min(420,height))
        self.resize(min(self.width(),width),min(self.height(),height))
        super().showEvent(event)

    def _remember(self,*_):
        if self.dont_show_again.isChecked():
            self.owner.settings.setValue(OFFER_SETTING,False)
            self.owner.settings.sync()

    def _start(self,route_id):
        self.accept()
        from xrd_finder.ui.learning_actions import LearningController
        controller=getattr(self.owner,'_learning_controller',None)
        if controller is None:
            controller=self.owner._learning_controller=LearningController(self.owner)
        controller.start_assistant(route_id)


class StartupLearningOffer(QObject):
    def __init__(self,window,delay_ms):
        super().__init__(window)
        self.window=window;self.dialog=None
        self.timer=QTimer(self);self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._show_when_ready)
        self.timer.start(delay_ms)

    def _show_when_ready(self):
        if not isValid(self.window) or not self.window.isVisible():return
        if not self.window.settings.value(OFFER_SETTING,True,type=bool):return
        gain=getattr(self.window,'gain_job_controller',None)
        busy=bool(getattr(self.window,'_auto_search_in_progress',False) or getattr(gain,'running',False))
        if QApplication.activeModalWidget() is not None or busy:
            self.timer.start(500);return
        self.dialog=LearningWelcomeDialog(self.window)
        self.dialog.show();self.dialog.raise_()

    def cancel(self):
        self.timer.stop()
        if self.dialog is not None and isValid(self.dialog):self.dialog.reject()


def schedule_learning_offer(window,*,delay_ms=700):
    if (os.environ.get('XRD_FINDER_LEARNING_DEMO')=='1' or
            not window.settings.value(OFFER_SETTING,True,type=bool)):
        return None
    offer=getattr(window,'_startup_learning_offer',None)
    if offer is None:
        offer=window._startup_learning_offer=StartupLearningOffer(window,delay_ms)
    return offer
