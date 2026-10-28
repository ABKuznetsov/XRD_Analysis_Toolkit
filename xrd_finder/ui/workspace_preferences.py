"""One workspace record for view settings and relative panel/column layout."""
import json
import math

WORKSPACE_KEY = 'ui/workspace_view_v1'
DEFAULT_SPLITTER_PROPORTIONS = {
    'main_splitter': (204/2506, 1765/2506, 537/2506),
    'center_splitter': (650/830, 180/830),
    'composition_splitter': (377/1161, 784/1161),
}


def normalized_proportions(values, count):
    if not isinstance(values, (list, tuple)) or len(values) != count or count < 1:
        return None
    try:
        if any(isinstance(value, bool) for value in values):
            return None
        numbers = [float(value) for value in values]
        if not all(math.isfinite(value) and value > 0 for value in numbers):
            return None
        largest = max(numbers)
        scaled = [value/largest for value in numbers]
        total = sum(scaled)
        result = [value/total for value in scaled]
        return result if all(value > 0 for value in result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def load_workspace_preferences(settings=None):
    if settings is None:
        from xrd_finder.ui.app_settings import app_settings
        settings = app_settings()
    try:
        data = json.loads(settings.value(WORKSPACE_KEY, '', type=str))
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def save_workspace_preferences(settings, data):
    settings.setValue(WORKSPACE_KEY, json.dumps(data))
