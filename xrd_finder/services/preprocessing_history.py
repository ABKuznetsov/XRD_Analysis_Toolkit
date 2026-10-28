"""Bounded processing checkpoints, persisted with each pattern."""
from copy import deepcopy


_EMPTY={'processed_points':[],'processed_label':'','processed_background_removed':False,
        'estimated_background_points':[],'estimated_background_with_halo_points':[],
        'angle_calibration_deg':0.0}


def capture_processing(pattern):
    return {name:deepcopy(getattr(pattern,name,default)) for name,default in _EMPTY.items()}


def restore_processing(pattern,state):
    # Crop intervals are independent user edits, but their coordinate system
    # must follow a calibration undone through this or an earlier checkpoint.
    delta = float(getattr(pattern,'angle_calibration_deg',0.)) - float(state.get('angle_calibration_deg',0.))
    if delta:
        pattern.crop_ranges = [[float(a)+delta,float(b)+delta] for a,b in pattern.crop_ranges]
    for name,default in _EMPTY.items():
        setattr(pattern,name,deepcopy(state.get(name,default)))


def remember_processing(pattern,kind,before):
    history=getattr(pattern,'preprocessing_history',None)
    if history is None:
        history=pattern.preprocessing_history=[]
    # Reset removes all applications of the selected operation, including
    # later dependent edits. Retain one snapshot per operation type.
    if not any(step['kind']==kind for step in history):
        history.append({'kind':kind,'before':deepcopy(before)})


def reset_processing(pattern,kind):
    history=getattr(pattern,'preprocessing_history',[])
    for index,step in enumerate(history):
        if step['kind']==kind:
            restore_processing(pattern,step['before'])
            del history[index:]
            return True
    if not history and getattr(pattern,'processed_points',[]):
        # Old projects have no checkpoints: restore the original trace while
        # retaining crop ranges, source path, phases and other project data.
        restore_processing(pattern,_EMPTY)
        return True
    return False
