"""Hermann–Mauguin typography; source symbols and settings remain unchanged."""
from functools import lru_cache
from html import escape
from importlib.resources import files
import json
import re

from PySide6.QtWidgets import QStyledItemDelegate
from xrd_finder.ui.formula_display import FormulaDisplayDelegate

_SUBSCRIPTS = str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉')
_ASCII = str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789')


def _key(text):
    text = re.sub(r'([₀₁₂₃₄₅₆₇₈₉]+)', lambda m: '_' + m[0].translate(_ASCII), text)
    text = re.sub(r'(\d)\u0305', r'-\1', text)
    return re.sub(r'\s+', '', text.replace('−', '-')).casefold()


@lru_cache(maxsize=1)
def _symbols():
    # Read only the packaged symbol strings. Building the full catalog would
    # instantiate every symmetry operation and Wyckoff map on the GUI thread.
    exact, loose = {}, {}
    try:
        path = files('cristma.reference_data').joinpath('resources/crystallography/space_groups.json')
        for record in json.loads(path.read_text(encoding='utf-8'))['records']:
            short = record['hm_short']
            for alias in (short, record['hm_full']):
                key = _key(alias)
                exact.setdefault(key, set()).add(short)
                loose.setdefault(key.replace('_', ''), set()).add(short)
    except (ImportError, OSError, ValueError, KeyError):
        return {}, {}
    # Ambiguous symbols are preserved rather than assigned a different group.
    return ({key: next(iter(values)) for key, values in exact.items() if len(values) == 1},
            {key: next(iter(values)) for key, values in loose.items() if len(values) == 1})


@lru_cache(maxsize=4096)
def space_group_display(text: str) -> str:
    raw = str(text or '')
    symbol = raw.strip().partition(':')[0]
    exact, loose = _symbols()
    key = _key(symbol)
    canonical = exact.get(key) or loose.get(key.replace('_', ''))
    if canonical is None:
        return symbol
    formatted = re.sub(r'_(\d)', lambda m: m[1].translate(_SUBSCRIPTS), canonical)
    formatted = re.sub(r'\s+', '', formatted)
    formatted = re.sub(r'-(\d)', lambda m: m[1] + '\u0305', formatted)
    return formatted


@lru_cache(maxsize=4096)
def space_group_html(text: str) -> str:
    symbol = space_group_display(text)
    parts = []
    end = 0
    for match in re.finditer(r'[A-Za-z]+|\d\u0305', symbol):
        parts.append(escape(symbol[end:match.start()]))
        if match[0].endswith('\u0305'):
            parts.append('<span style="text-decoration:overline;">' + match[0][0] + '</span>')
        else:
            parts.append('<i>' + escape(match[0]) + '</i>')
        end = match.end()
    parts.append(escape(symbol[end:]))
    return '<span style="font-style:normal;">' + ''.join(parts) + '</span>'


class SpaceGroupDisplayDelegate(FormulaDisplayDelegate):
    def _display_html(self, text):
        return space_group_html(text)

    def initStyleOption(self, option, index):
        QStyledItemDelegate.initStyleOption(self, option, index)
        option.text = space_group_display(str(index.data() or ''))
