"""One workspace record for view settings and relative panel/column layout."""
import json
import math

WORKSPACE_KEY = 'ui/workspace_view_v1'
DEFAULT_SPLITTER_PROPORTIONS = {
    'main_splitter': (.12429378531073448, .5954802259887007, .280225988700565),
    'center_splitter': (.7208053691275169, .27919463087248314),
    'composition_splitter': (.3714585519412382, .6285414480587619),
}
# Reference proportions chosen in Finder, independent of the screen on which
# that layout was arranged. No user-specific paths or profile state are stored.
DEFAULT_TABLE_PROPORTIONS = {
    'candidates': (.07854406130268199, .10440613026819924, .24042145593869732,
        .1331417624521073, .11398467432950192, .13026819923371646,
        .10057471264367816, .09865900383141762),
    'accepted': (.05672268907563026, .38445378151260506, .27310924369747897,
        .15126050420168066, .13445378151260504),
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
