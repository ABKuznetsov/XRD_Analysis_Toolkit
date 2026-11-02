"""A non-modal coach whose progress never claims unobserved analysis success."""
from html import escape
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QHBoxLayout,QLabel,QPushButton,QTextBrowser,QToolButton,QVBoxLayout
from xrd_finder.learning.catalog import ASSISTANT_ROUTES,CHAPTERS,STEPS,chapter_for,upgrade_route
from xrd_finder.learning.overview import OVERVIEW
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog
from xrd_finder.ui.learning_targets import context_prompt,reveal_overview_target,reveal_target,step_complete


def lesson_html(step):
    sections=(('Why',step.purpose),('Where',step.where),('Try it',step.instruction),
              ('Expected result',step.expected),('If it does not work',step.troubleshooting))
    return '<html><body>'+''.join('<p><b>'+escape(title)+'</b><br>'+escape(text)+'</p>' for title,text in sections)+'</body></html>'


class LearningCoach(ScreenBoundDialog):
    def __init__(self,controller):
        super().__init__(controller.window)
        self.controller=controller;self.window=controller.window
        self.setWindowTitle('Learn Finder · practice')
        self.setWindowFlags(self.windowFlags()|Qt.WindowType.Tool)
        self.setWindowModality(Qt.NonModal)
        self.resize(410,340);self.setMinimumSize(300,240)
        layout=QVBoxLayout(self)
        self.heading=QLabel();self.heading.setWordWrap(True);layout.addWidget(self.heading)
        self.position=QLabel();self.position.setProperty('uiRole','muted');layout.addWidget(self.position)
        self.sample_label=QLabel();self.sample_label.setWordWrap(True);self.sample_label.setProperty('uiRole','muted');layout.addWidget(self.sample_label)
        self.task_label=QLabel();self.task_label.setWordWrap(True);layout.addWidget(self.task_label)
        self.where_label=QLabel();self.where_label.setWordWrap(True);self.where_label.setProperty('uiRole','muted');layout.addWidget(self.where_label)
        self.details_button=QToolButton();self.details_button.setText('Explanation');self.details_button.setCheckable(True)
        layout.addWidget(self.details_button)
        self.browser=QTextBrowser();self.browser.setOpenLinks(False);self.browser.hide();layout.addWidget(self.browser,1)
        self.details_button.toggled.connect(self.browser.setVisible)
        self.state_label=QLabel();self.state_label.setWordWrap(True);layout.addWidget(self.state_label)
        row=QHBoxLayout();layout.addLayout(row)
        self.show_button=QPushButton('Show me');self.check_button=QPushButton('Check step')
        self.demo_button=QPushButton('Open training demo')
        for button in (self.show_button,self.check_button):row.addWidget(button)
        layout.addWidget(self.demo_button)
        row=QHBoxLayout();layout.addLayout(row)
        self.previous_button=QPushButton('Previous');self.next_button=QPushButton('Next')
        self.skip_button=QPushButton('Skip');self.pause_button=QPushButton('Pause')
        for button in (self.previous_button,self.skip_button,self.next_button,self.pause_button):row.addWidget(button)
        self.show_button.clicked.connect(self.show_target)
        self.check_button.clicked.connect(self.check)
        self.previous_button.clicked.connect(lambda:self._move(-1))
        self.next_button.clicked.connect(self._next)
        self.skip_button.clicked.connect(lambda:self._move(1))
        self.pause_button.clicked.connect(controller.pause)
        self.demo_button.clicked.connect(lambda:controller.launch_demo(self.chapter.id,self.step.id))
        self.timer=QTimer(self);self.timer.setInterval(600);self.timer.timeout.connect(self._observe)
        self.step=None;self.chapter=None;self.index=0;self.guided=False;self.sequence=[];self.route_id=None
        self.reveal_timer=QTimer(self);self.reveal_timer.setSingleShot(True);self.reveal_timer.timeout.connect(self.show_target)

    def start(self,chapter,step_id=None):
        self.guided=False;self.route_id=None
        self.chapter=chapter
        ids=[step.id for step in chapter.steps]
        self.sequence=ids
        self.index=ids.index(step_id) if step_id in ids else 0
        self._display()
        self.show();self.raise_();self.activateWindow();self.timer.start()

    def start_route(self,route_id,step_ids,step_id=None):
        self.guided=True;self.route_id=route_id;self.sequence=upgrade_route(route_id,step_ids)
        self.index=self.sequence.index(step_id) if step_id in self.sequence else 0
        missing=[key for key in self.sequence if key not in step_ids]
        if missing:self.index=min(self.index,self.sequence.index(missing[0]))
        self._display()
        self.show();self.raise_();self.activateWindow();self.timer.start();self.reveal_timer.start(0)

    def _display(self):
        self.controller.highlight.clear()
        self.step=STEPS[self.sequence[self.index]];self.chapter=chapter_for(self.step.id)
        self.heading.setText(self.step.title)
        label=ASSISTANT_ROUTES[self.route_id][0] if self.guided else self.chapter.title
        self.position.setText(f'{label} · step {self.index+1}/{len(self.sequence)}\n{self.chapter.title}')
        overview=self.route_id=='overview'
        self.task_label.setText(OVERVIEW[self.step.id][0] if overview else context_prompt(self.window,self.step))
        self.demo_button.setVisible(not overview and self.window._active_pattern() is None)
        self.where_label.setText('Where: '+self.step.where)
        self.browser.setHtml(lesson_html(self.step))
        self.details_button.setChecked(False)
        self.check_button.setText(('I did this' if self.guided else 'Mark read') if self.step.check is None else 'Check step')
        self.check_button.setVisible(not overview)
        self.previous_button.setEnabled(self.index>0)
        self.next_button.setText('Next' if self.index<len(self.sequence)-1 else ('Finish' if self.guided else 'Next chapter'))
        complete=(self.step.id in self.controller.progress.completed and
                  (self.step.check is None or step_complete(self.window,self.step.check)))
        self.next_button.setEnabled(complete or overview)
        self.controller.progress.current_step=self.step.id
        self.controller.progress.current_route=({'id':self.route_id,'steps':list(self.sequence)} if self.guided else None)
        self.controller.save_progress()
        if overview:
            self.state_label.setText('Feature overview only. No action is required; use Next or ? for more detail.')
        elif complete:
            verified=self.controller.progress.completed[self.step.id]
            self.state_label.setText('Goal observed in Finder.' if verified else 'Marked read by you.')
        else:
            self.state_label.setText(('Perform this step, then confirm or use Skip.' if self.guided else 'Use ? if you need an explanation, then Mark read.')
                                     if self.step.check is None else 'Use the highlighted control. The assistant checks for the visible goal.')
        if self.guided:self.reveal_timer.start(0)
        self._update_sample()

    def check(self):
        if self.step.check is None:
            self._complete(False)
        elif step_complete(self.window,self.step.check):
            self._complete(True)
        else:
            self.state_label.setText('The goal is not visible yet. Follow Try it, use Show me or skip this step.')

    def _observe(self):
        self._update_sample()
        if self.route_id=='overview':return
        if self.step is not None:self.task_label.setText(context_prompt(self.window,self.step))
        if self.isVisible() and self.step is not None and self.step.check is not None:
            ready=step_complete(self.window,self.step.check)
            if not self.next_button.isEnabled() and ready:
                self._complete(True)
            elif self.next_button.isEnabled() and not ready:
                self.next_button.setEnabled(False)
                self.state_label.setText('The current workspace has changed. Complete this step again, or use Skip.')

    def _update_sample(self):
        pattern=self.window._active_pattern()
        self.sample_label.setText('Sample: '+str(getattr(pattern,'name','') or 'No active XRD'))

    def _complete(self,verified):
        self.controller.progress.mark(self.step.id,verified=verified)
        self.controller.save_progress()
        self.state_label.setText('Goal observed in Finder. Continue when you are ready.' if verified
                                 else ('Confirmed by you.' if self.guided else 'Marked read by you; no calculation was verified.'))
        self.next_button.setEnabled(True)

    def show_target(self):
        if self.route_id=='overview':
            target,note=reveal_overview_target(self.window,OVERVIEW[self.step.id][1])
        else:target,note=reveal_target(self.window,self.step.target)
        highlighted=self.controller.highlight.show(target) if target is not None else False
        self.state_label.setText(note or ('The control is outlined. You can click it normally.' if highlighted
                                         else 'Use Where to locate this control in the current workspace.'))

    def _next(self):
        if self.route_id=='overview':
            self.controller.progress.mark(self.step.id,verified=False)
            self.controller.save_progress()
        self._move(1)

    def _move(self,delta):
        next_index=self.index+delta
        if 0<=next_index<len(self.sequence):
            self.index=next_index;self._display();return
        if delta>0:
            if self.guided:self.controller.open();return
            chapter_index=CHAPTERS.index(self.chapter)
            if chapter_index+1<len(CHAPTERS):self.controller.start_chapter(CHAPTERS[chapter_index+1].id)
            else:self.controller.open()

    def hideEvent(self,event):
        self.timer.stop();self.reveal_timer.stop();self.controller.highlight.clear()
        super().hideEvent(event)

    def closeEvent(self,event):
        self.timer.stop();self.reveal_timer.stop();self.controller.highlight.clear()
        super().closeEvent(event)
