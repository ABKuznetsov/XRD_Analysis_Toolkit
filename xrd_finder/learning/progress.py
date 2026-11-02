"""Small atomic learning metadata, independent of XPFF and result caches."""
import json
import os
from pathlib import Path
import tempfile

from xrd_finder.learning.catalog import ASSISTANT_ROUTES,STEPS


class LearningProgress:
    def __init__(self,path):
        self.path=Path(path)
        self.completed={}
        self.current_step=None
        self.current_route=None
        self.load_error=''

    def load(self):
        self.completed={};self.current_step=None;self.current_route=None;self.load_error=''
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('format')!=1 or not isinstance(data.get('completed'),dict):
                raise ValueError('Unrecognised learning progress format')
            self.completed={key:value for key,value in data['completed'].items()
                            if key in STEPS and isinstance(value,bool)}
            current=data.get('current_step')
            self.current_step=current if current in STEPS else None
            route=data.get('current_route')
            if (isinstance(route,dict) and route.get('id') in ASSISTANT_ROUTES and
                isinstance(route.get('steps'),list) and route['steps'] and
                all(isinstance(key,str) and key in STEPS for key in route['steps']) and
                self.current_step in route['steps']):
                self.current_route={'id':route['id'],'steps':route['steps']}
        except FileNotFoundError:
            pass
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            self.load_error=str(exc)
        return self

    def mark(self,step_id,*,verified=False):
        if step_id not in STEPS:raise ValueError('Unknown learning step: '+str(step_id))
        self.completed[step_id]=bool(verified or self.completed.get(step_id,False))

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        # Main Finder and its independent training window may save in either order.
        # Keep previous completions; a manual acknowledgement cannot downgrade one.
        previous=LearningProgress(self.path).load()
        for key,value in previous.completed.items():
            self.completed[key]=bool(value or self.completed.get(key,False))
        data=dict(format=1,completed=self.completed,current_step=self.current_step)
        if self.current_route is not None:data['current_route']=self.current_route
        descriptor,name=tempfile.mkstemp(prefix='.learning-',suffix='.tmp',dir=self.path.parent)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as output:
                json.dump(data,output,indent=2,sort_keys=True)
            os.replace(name,self.path)
        finally:
            Path(name).unlink(missing_ok=True)
