"""One learning controller per Finder window; no scientific state in progress."""
import os
from pathlib import Path
from PySide6.QtCore import QObject
from xrd_finder.learning.catalog import CHAPTERS,STEPS,chapter_for,route_steps
from xrd_finder.learning.progress import LearningProgress
from xrd_finder.services.cache_paths import default_data_root
from xrd_finder.ui.learning_targets import TargetHighlight


class LearningController(QObject):
    def __init__(self,window,*,progress_path=None):
        super().__init__(window)
        self.window=window
        path=progress_path or os.environ.get('XRD_FINDER_LEARNING_PROGRESS_FILE') or default_data_root()/'settings/learning-progress.json'
        self.progress=LearningProgress(path).load()
        from xrd_finder.ui.learning_hint import LearningHintPopup
        self.hint_popup=LearningHintPopup(window)
        self.highlight=TargetHighlight(self,on_help=self.show_step_help,on_clear=self.hint_popup.hide)
        from xrd_finder.ui.learning_coach import LearningCoach
        from xrd_finder.ui.learning_dialog import LearningCatalogDialog
        self.coach=LearningCoach(self);self.catalog=LearningCatalogDialog(self)

    def open(self,chapter_id=None):
        self.pause()
        self.catalog.refresh()
        self.catalog.show();self.catalog.raise_();self.catalog.activateWindow()
        if chapter_id:
            chapter=next((chapter for chapter in CHAPTERS if chapter.id==chapter_id),None)
            if chapter is not None:self.catalog.search.setText(chapter.title.split('·')[-1].strip())

    def start_chapter(self,chapter_id,step_id=None):
        chapter=next((chapter for chapter in CHAPTERS if chapter.id==chapter_id),None)
        if chapter is None:raise ValueError('Unknown learning chapter')
        self.catalog.hide();self.coach.start(chapter,step_id)

    def resume(self):
        current=self.progress.current_step
        route=self.progress.current_route
        if route and current in route['steps']:
            self.catalog.hide();self.coach.start_route(route['id'],route['steps'],current)
        elif current in STEPS:self.start_chapter(chapter_for(current).id,current)
        else:self.start_chapter(CHAPTERS[0].id)

    def start_assistant(self,route_id='complete'):
        steps=route_steps(route_id,has_pattern=self.window._active_pattern() is not None,
                          has_library=(self.window.local_phase_cache.peak_indexed_count()>0 if route_id=='identify' else False))
        self.catalog.hide();self.coach.start_route(route_id,steps)

    def show_step_help(self):
        if self.coach.step is not None and self.highlight.question is not None:
            self.hint_popup.show_step(self.coach.step,self.highlight.question)

    def save_progress(self):
        try:self.progress.save()
        except OSError as exc:
            self.window._set_background_status('Learning progress could not be saved: '+str(exc))

    def pause(self):
        self.coach.hide();self.highlight.clear()

    def close(self):
        self.pause();self.catalog.hide()

    def launch_demo(self,chapter_id=None,step_id=None):
        if os.environ.get('XRD_FINDER_LEARNING_DEMO')=='1':
            self.start_assistant('identify');return True
        from xrd_finder.ui.learning_demo_launch import launch_learning_demo
        return launch_learning_demo(self.window,self.progress.path,chapter_id=chapter_id,step_id=step_id)


class PhaseFinderLearningActionsMixin:
    def _toggle_context_help(self):
        controller=getattr(self,'_context_help_controller',None)
        if controller is None:
            from xrd_finder.ui.context_help import ContextHelpController
            controller=self._context_help_controller=ContextHelpController(self)
        controller.set_enabled(not controller.enabled)

    def _show_learning_guide(self):
        context=getattr(self,'_context_help_controller',None)
        if context is not None:context.set_enabled(False)
        controller=getattr(self,'_learning_controller',None)
        if controller is None:controller=self._learning_controller=LearningController(self)
        controller.open()

    def _close_learning_guide(self):
        context=getattr(self,'_context_help_controller',None)
        if context is not None:context.set_enabled(False)
        offer=getattr(self,'_startup_learning_offer',None)
        if offer is not None:offer.cancel()
        controller=getattr(self,'_learning_controller',None)
        if controller is not None:controller.close()
