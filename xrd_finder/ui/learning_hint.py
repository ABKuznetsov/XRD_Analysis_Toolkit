"""Opaque on-demand explanation anchored beside a highlighted real control."""
from html import escape
from PySide6.QtCore import QPoint,Qt
from PySide6.QtWidgets import QFrame,QLabel,QTextBrowser,QVBoxLayout
from xrd_finder.ui.theme import theme_colors


class LearningHintPopup(QFrame):
    def __init__(self,parent):
        super().__init__(parent,Qt.WindowType.Popup)
        self.setObjectName('learningHintPopup')
        self.setAttribute(Qt.WA_StyledBackground,True)
        self.setAttribute(Qt.WA_TranslucentBackground,False)
        self.setAutoFillBackground(True);self.setWindowOpacity(1.)
        layout=QVBoxLayout(self);layout.setContentsMargins(12,10,12,10)
        self.heading=QLabel();self.heading.setTextFormat(Qt.PlainText)
        self.heading.setWordWrap(True);layout.addWidget(self.heading)
        self.browser=QTextBrowser();self.browser.setOpenLinks(False)
        self.browser.setMinimumHeight(110);layout.addWidget(self.browser)
        self.resize(390,260)

    def show_step(self,step,anchor):
        fields=(('Why',step.purpose),('What to do',step.instruction),
                ('Expected result',step.expected),('If it does not work',step.troubleshooting))
        self.show_content(step.title,fields,anchor)

    def show_content(self,title,fields,anchor,position=None):
        colors=theme_colors(widget=self.parentWidget())
        self.setStyleSheet(f"QFrame#learningHintPopup {{background:{colors['panel']};color:{colors['text']};"
                           f"border:1px solid {colors['cell_border']};border-radius:7px;}}"
                           f"QTextBrowser {{background:{colors['panel']};color:{colors['text']};border:0;}}")
        self.heading.setText(title)
        self.browser.setHtml(''.join(f'<p><b>{escape(title)}</b><br>{escape(text)}</p>' for title,text in fields))
        available=anchor.screen().availableGeometry()
        width=min(390,max(240,available.width()-24));height=min(300,max(170,available.height()-48))
        self.resize(width,height)
        position=position or anchor.mapToGlobal(QPoint(0,anchor.height()+5))
        self.move(max(available.left()+8,min(position.x(),available.right()-width-8)),
                  max(available.top()+8,min(position.y(),available.bottom()-height-8)))
        self.show();self.raise_()
