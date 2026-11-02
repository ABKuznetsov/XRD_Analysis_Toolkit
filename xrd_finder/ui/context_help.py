"""Persistent click-to-explain mode; intercepted clicks never execute commands."""
import weakref
from PySide6.QtCore import QObject,QEvent,Qt,QPoint,QSignalBlocker
from PySide6.QtWidgets import QApplication,QWidget,QMenu,QMenuBar
from shiboken6 import isValid
from xrd_finder.ui.context_help_topics import resolve_help
from xrd_finder.ui.learning_hint import LearningHintPopup
from xrd_finder.ui.learning_targets import TargetHighlight


class ContextHelpController(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window;self.enabled=False;self._hover=None
        self.popup=LearningHintPopup(window)
        # Unlike a one-shot Qt.Popup, this card must not grab the mouse: users
        # can immediately point at the next control or switch Help off.
        self.popup.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.popup.setAttribute(Qt.WA_ShowWithoutActivating,True)
        self.popup.setProperty('independentUiScale',True)
        self.popup.heading.setStyleSheet('font-size:16px;font-weight:600;')
        self.popup.browser.setStyleSheet('font-size:14px;')
        self.highlight=TargetHighlight(self,color='#7c3aed',scroll_to_target=False)

    def set_enabled(self,enabled):
        enabled=bool(enabled)
        if enabled==self.enabled:return
        self.enabled=enabled
        app=QApplication.instance()
        if enabled:
            offer=getattr(self.window,'_startup_learning_offer',None)
            if offer is not None:offer.cancel()
            learning=getattr(self.window,'_learning_controller',None)
            if learning is not None:learning.close();learning.hint_popup.hide()
            app.installEventFilter(self)
            app.setOverrideCursor(Qt.WhatsThisCursor)
        else:
            app.removeEventFilter(self);app.restoreOverrideCursor()
            self.popup.hide();self.highlight.clear();self._hover=None
        button=self.window._layout_state.help_button
        with QSignalBlocker(button):button.setChecked(enabled)
        self.window.finder_top_toolbar._apply_style()

    def _belongs(self,widget):
        current=widget
        while current is not None:
            if current is self.window:return True
            current=current.parentWidget()
        return False

    def _highlight(self,target):
        old=self._hover() if self._hover else None
        if old is target and self.highlight.active:return
        self._hover=weakref.ref(target)
        self.highlight.show(target)

    def eventFilter(self,watched,event):
        if not self.enabled or not isinstance(watched,QWidget) or not isValid(watched):return False
        if not self._belongs(watched):return False
        kind=event.type()
        if kind in (QEvent.KeyPress,QEvent.ShortcutOverride) and event.key()==Qt.Key_Escape:
            event.accept()
            if kind==QEvent.KeyPress:self.set_enabled(False)
            return True
        if watched is self.popup or self.popup.isAncestorOf(watched):return False
        button=self.window._layout_state.help_button
        if watched is button or button.isAncestorOf(watched):return False
        # The application menu remains available to enter Learn Finder or leave Help.
        if isinstance(watched,QMenuBar):return False
        if isinstance(watched,QMenu) and watched.title().replace('&','')=='Help':return False
        if kind in (QEvent.Enter,QEvent.MouseMove,QEvent.HoverMove,QEvent.MouseButtonPress):
            position=event.globalPosition().toPoint() if hasattr(event,'globalPosition') else None
            subject=watched
            if position is not None and not isinstance(watched,QMenu):
                child=watched.childAt(watched.mapFromGlobal(position))
                if child is not None:subject=child
            if isinstance(watched,QMenu) and position is not None:
                action=watched.actionAt(watched.mapFromGlobal(position))
                if action is self.window.finder_top_toolbar._overflow_actions.get(button):return False
            target,article=resolve_help(self.window,subject,position)
            self._highlight(target)
            if kind==QEvent.MouseButtonPress:
                if isinstance(watched,QMenu):watched.hide()
                self.popup.show_content(article.title,(('What',article.what),('Why',article.why),
                    ('How to use',article.how)),target,position+QPoint(12,16) if position is not None else None)
                return True
        if kind in (QEvent.MouseButtonRelease,QEvent.MouseButtonDblClick,QEvent.ContextMenu,
                    QEvent.Wheel,QEvent.KeyPress,QEvent.KeyRelease,QEvent.ShortcutOverride):
            event.accept();return True
        if kind==QEvent.ToolTip:return True
        return False
