"""Start a separate offline practice process without replacing user work."""
import os
from pathlib import Path
import sys
from PySide6.QtCore import QProcess,QProcessEnvironment
from PySide6.QtWidgets import QMessageBox
from xrd_finder.services.cache_paths import default_data_root


def demo_environment(base,*,package_root,progress_path):
    env=dict(base)
    for name in list(env):
        if (name.startswith('XRD_FINDER_') or 'API_KEY' in name or name=='MAPI_KEY'
                or name.endswith('_TOKEN')):env.pop(name,None)
    env.update(PYTHONPATH=str(package_root)+os.pathsep+env.get('PYTHONPATH',''),
        PYTHONDONTWRITEBYTECODE='1',XRD_FINDER_OFFLINE='1',XRD_FINDER_LEARNING_DEMO='1',
        XRD_FINDER_LEARNING_PROGRESS_FILE=str(progress_path),
        OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
    return env


def launch_learning_demo(window,progress_path,*,chapter_id=None,step_id=None):
    if getattr(sys,'frozen',False):
        QMessageBox.information(window,'Training demo','The isolated demo needs a Python worker runtime. You can use the assistant on your own measurement in this build.')
        return False
    package_root=Path(__file__).resolve().parents[2]
    env=demo_environment(os.environ,package_root=package_root,progress_path=progress_path)
    process=QProcess(window)
    environment=QProcessEnvironment()
    for key,value in env.items():environment.insert(key,value)
    process.setProcessEnvironment(environment)
    process.setProgram(sys.executable)
    arguments=['-m','xrd_finder.apps.learning_demo']
    if chapter_id:arguments+=['--chapter',chapter_id]
    if step_id:arguments+=['--step',step_id]
    process.setArguments(arguments);process.setWorkingDirectory(str(package_root))
    log=default_data_root().parent/'logs/learning-demo.log'
    log.parent.mkdir(parents=True,exist_ok=True)
    process.setProcessChannelMode(QProcess.MergedChannels)
    process.setStandardOutputFile(str(log))
    started=process.startDetached()
    ok=started[0] if isinstance(started,tuple) else bool(started)
    process.deleteLater()
    if not ok:
        QMessageBox.warning(window,'Training demo','Could not start the isolated demo. See '+str(log))
    else:window._set_background_status('Opening a separate offline training sandbox…')
    return ok
