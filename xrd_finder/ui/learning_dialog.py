"""Searchable chapter catalog and reference browser for the real application."""
from html import escape
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox,QHBoxLayout,QLabel,QLineEdit,QPushButton,QSplitter,QTextBrowser,QToolButton,QTreeWidget,QTreeWidgetItem,QVBoxLayout,QWidget
from xrd_finder.learning.catalog import ASSISTANT_ROUTES,CHAPTERS,STEPS,chapter_for,find_steps
from xrd_finder.ui.learning_coach import lesson_html
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


class LearningCatalogDialog(ScreenBoundDialog):
    def __init__(self,controller):
        super().__init__(controller.window)
        self.controller=controller
        self.setWindowTitle('Learn Finder')
        self.setWindowModality(Qt.NonModal)
        self.resize(650,330);self.setMinimumSize(320,240)
        layout=QVBoxLayout(self)
        introduction=QLabel('The complete workflow covers Finder on your own XRD: databases, processing, instruments, search, results and exports. Follow the highlights; click ? when needed. You choose which operations to apply. Shorter task routes are also available.')
        introduction.setWordWrap(True);layout.addWidget(introduction)
        self.context_label=QLabel();self.context_label.setWordWrap(True);layout.addWidget(self.context_label)
        self.route_selector=QComboBox()
        for key,(title,_steps) in ASSISTANT_ROUTES.items():self.route_selector.addItem(title,key)
        layout.addWidget(self.route_selector)
        self.use_my_xrd_button=QPushButton('Start with my XRD')
        self.use_my_xrd_button.clicked.connect(lambda:controller.start_assistant(self.route_selector.currentData()))
        layout.addWidget(self.use_my_xrd_button)
        self.topics_button=QToolButton();self.topics_button.setText('Find a feature / all topics');self.topics_button.setCheckable(True)
        layout.addWidget(self.topics_button)
        self.reference_body=QWidget();reference_layout=QVBoxLayout(self.reference_body)
        reference_layout.setContentsMargins(0,0,0,0);layout.addWidget(self.reference_body,1)
        self.search=QLineEdit();self.search.setPlaceholderText('Search topics: database, Gain, background, hkl, export…')
        self.search.setAccessibleName('Search learning topics');reference_layout.addWidget(self.search)
        self.splitter=QSplitter(Qt.Horizontal);self.splitter.setChildrenCollapsible(False)
        self.chapter_tree=QTreeWidget();self.chapter_tree.setHeaderHidden(True);self.chapter_tree.setMinimumWidth(130)
        self.chapter_tree.setWordWrap(True)
        self.browser=QTextBrowser();self.browser.setOpenLinks(False);self.browser.setMinimumWidth(160)
        self.splitter.addWidget(self.chapter_tree);self.splitter.addWidget(self.browser)
        self.splitter.setSizes([300,600]);reference_layout.addWidget(self.splitter,1)
        self.progress_label=QLabel();self.progress_label.setWordWrap(True);layout.addWidget(self.progress_label)
        row=QHBoxLayout();layout.addLayout(row)
        self.start_button=QPushButton('Start here');self.resume_button=QPushButton('Resume')
        self.demo_button=QPushButton('No data? Try a demo');self.close_button=QPushButton('Close')
        for button in (self.start_button,self.resume_button,self.demo_button,self.close_button):row.addWidget(button)
        self.search.textChanged.connect(self.refresh)
        self.chapter_tree.currentItemChanged.connect(self._selected)
        self.chapter_tree.itemDoubleClicked.connect(lambda *_:self.start_selected())
        self.start_button.clicked.connect(self.start_selected)
        self.resume_button.clicked.connect(controller.resume)
        self.demo_button.clicked.connect(lambda:controller.launch_demo())
        self.close_button.clicked.connect(self.close)
        self.topics_button.toggled.connect(self._show_topics)
        self.reference_body.hide()
        self.start_button.hide()
        self.refresh()

    def _show_topics(self,visible):
        self.reference_body.setVisible(visible)
        self.start_button.setVisible(visible)
        bounds=self.controller.window
        self.resize(min(930 if visible else 650,max(320,bounds.width()-16)),
                    min(650 if visible else 330,max(240,bounds.height()-40)))

    def refresh(self,*_):
        selected=self.selected_step_id()
        ordered=find_steps(self.search.text());hits={step.id for step in ordered}
        ranking={step.id:index for index,step in enumerate(ordered)}
        if self.search.text().strip():self.topics_button.setChecked(True)
        pattern=self.controller.window._active_pattern()
        self.context_label.setText('Active sample: '+pattern.name if pattern is not None
            else 'No active measurement yet. The first step will highlight Import data; your project will stay open.')
        self.chapter_tree.clear()
        selected_item=None;first=None
        chapters=sorted(CHAPTERS,key=lambda chapter:min((ranking.get(step.id,len(STEPS)) for step in chapter.steps),default=len(STEPS)))
        for chapter in chapters:
            steps=[step for step in chapter.steps if step.id in hits]
            if not steps:continue
            root=QTreeWidgetItem([chapter.title]);root.setData(0,Qt.UserRole,steps[0].id)
            root.setToolTip(0,chapter.summary);self.chapter_tree.addTopLevelItem(root)
            for step in steps:
                prefix='✓ ' if step.id in self.controller.progress.completed else ''
                item=QTreeWidgetItem([prefix+step.title]);item.setData(0,Qt.UserRole,step.id);root.addChild(item)
                if first is None:first=item
                if step.id==selected:selected_item=item
            root.setExpanded(bool(self.search.text().strip()))
        self.chapter_tree.setCurrentItem((first if self.search.text().strip() else selected_item or first))
        count=len(self.controller.progress.completed)
        self.progress_label.setText(f'Progress: {count}/{len(STEPS)} steps. You can pause and resume at any time.')
        self.resume_button.setEnabled(self.controller.progress.current_step in STEPS)
        self.start_button.setEnabled(first is not None)
        if first is None:self.browser.setHtml('<p>No matching topics. Try a shorter control name or clear the search.</p>')

    def selected_step_id(self):
        item=self.chapter_tree.currentItem()
        return item.data(0,Qt.UserRole) if item is not None else None

    def _selected(self,item,*_):
        step_id=item.data(0,Qt.UserRole) if item is not None else None
        if step_id in STEPS:
            step=STEPS[step_id];chapter=chapter_for(step_id)
            self.browser.setHtml('<h3>'+escape(chapter.title)+'</h3><h2>'+escape(step.title)+'</h2>'+lesson_html(step))

    def start_selected(self):
        step_id=self.selected_step_id()
        if step_id in STEPS:self.controller.start_chapter(chapter_for(step_id).id,step_id)
