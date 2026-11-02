"""An independent temporary Finder instance; set paths before any service import."""
import argparse
import json
import os
from pathlib import Path
import tempfile


def main():
    parser=argparse.ArgumentParser(description='Isolated offline Finder practice')
    parser.add_argument('--chapter');parser.add_argument('--step')
    parser.add_argument('--smoke',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='xrd-finder-learning-') as folder:
        root=Path(folder)
        os.environ.update(XRD_FINDER_DATA_DIR=folder,XRD_FINDER_OFFLINE='1',XRD_FINDER_LEARNING_DEMO='1',
            MPLCONFIGDIR=str(root/'matplotlib'),XRD_FINDER_LOG_DIR=str(root/'logs'))
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QLabel
        from xrd_finder.learning.demo import build_demo_workspace
        from xrd_finder.instrument.library import InstrumentProfileLibrary
        from xrd_finder.ui.app_settings import app_settings
        from xrd_finder.ui.analysis_windows import PhaseFinderWindow
        from xrd_finder.ui.learning_actions import LearningController
        data=build_demo_workspace(root)
        app=QApplication.instance() or QApplication([])
        app.setApplicationName('XRD Phase Finder · Training')
        library=InstrumentProfileLibrary(root/'settings/instrument_profiles.json')
        library.save_profile(data.profile)
        settings=app_settings();settings.setValue('instrument/active_profile_id',data.profile.profile_id)
        window=PhaseFinderWindow(data.project)
        window.setWindowTitle('XRD Phase Finder · Training sandbox · synthetic data')
        banner=QLabel('Training sandbox · synthetic data · offline · your projects and libraries are kept separate',window)
        banner.setWordWrap(True);window.layout().insertWidget(1,banner)
        window.tree.set_checked_pattern_ids([data.project.patterns[0].id])
        window.tree.select_object('pattern',data.project.patterns[0].id)
        controller=window._learning_controller=LearningController(window)
        window.show()
        if args.chapter:controller.start_chapter(args.chapter,args.step)
        else:controller.start_assistant('identify')
        if args.smoke:
            window._confirm_project_replacement=lambda:True
            timer=QTimer(window);timer.setSingleShot(True);timer.timeout.connect(window.close);timer.start(800)
        code=app.exec()
        summary=dict(patterns=len(data.project.patterns),references=data.cache.peak_indexed_count(),
                     data_root=str(root),offline=os.environ['XRD_FINDER_OFFLINE'])
    if args.smoke:print('XRD_LEARNING_SMOKE='+json.dumps(dict(summary,cleaned_up=not root.exists())),flush=True)
    return int(code)


if __name__=='__main__':raise SystemExit(main())
