"""Chemical typography for the UI; never used as stored or calculation data."""
from __future__ import annotations

from functools import lru_cache
from html import escape
import re

from cristma.chemistry.elements import ELEMENT_SYMBOLS
from xrd_finder.finder.composition_validation import CifCompositionError, formula_amounts
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPalette, QTextDocument
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem


# IUPAC Red Book (2005), Table VI, electropositive constituents first.
# https://publications.iupac.org/books/rbook/Red_Book_2005.pdf
# No chemistry engine or optional pymatgen import is needed while painting.
_SEQUENCE = (
    'Rn Xe Kr Ar Ne He Fr Cs Rb K Na Li Ra Ba Sr Ca Mg Be '
    'Lr No Md Fm Es Cf Bk Cm Am Pu Np U Pa Th Ac Lu Yb Tm Er Ho Dy Tb Gd Eu Sm Pm Nd Pr Ce La Y Sc '
    'Hf Zr Ti Ta Nb V W Mo Cr Re Tc Mn Os Ru Fe Ir Rh Co Pt Pd Ni Au Ag Cu Hg Cd Zn '
    'Tl In Ga Al B Pb Sn Ge Si C Bi Sb As P N H Po Te Se S O At I Br Cl F'
).split()
_ORDER = {symbol: index for index, symbol in enumerate(_SEQUENCE)}
_TOKEN = re.compile(r'([A-Z][a-z]?)(\d+(?:\.\d+)?|\.\d+)?')
_SUBSCRIPT = re.compile(r'([A-Z][a-z]?|\)|\])(\d+(?:\.\d+)?|\.\d+)')
_SUBSCRIPT_TO_ASCII = str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789')


@lru_cache(maxsize=4096)
def _formula_parts(text: str):
    compact = re.sub(r'\s+', '', text.translate(_SUBSCRIPT_TO_ASCII))
    if not compact or len(compact) > 1024:
        return None
    # Explicit substitution groups are display notation, not an occupancy model.
    validation = re.sub(r'\(([A-Z][a-z]?)(?:,[A-Z][a-z]?)+\)', r'\1', compact)
    try:
        amounts = formula_amounts(validation)
    except (CifCompositionError, ValueError, OverflowError):
        return None
    symbols = re.findall(r'[A-Z][a-z]?', compact)
    if not symbols or not set(symbols) <= ELEMENT_SYMBOLS:
        return None
    tokens = list(_TOKEN.finditer(compact))
    flat = ''.join(match.group() for match in tokens) == compact
    return compact, amounts, tokens if flat else None


@lru_cache(maxsize=4096)
def canonical_display_formula(text: str) -> str:
    """Order flat sum formulae; retain explicit groups and molecular sequences.

    Counts and formula-unit multiplicity are retained. Repeated atom symbols
    (CH3COOH), parentheses, hydration and an explicit leading acid H are not
    flattened or inferred from an empirical composition.
    """
    parts = _formula_parts(text)
    if parts is None:
        return text
    compact, amounts, tokens = parts
    if (tokens is None or len(tokens) != len(amounts) or tokens[0][1] == 'H'
            or ('H' in amounts and not re.search(r'\s', text))):
        return compact
    if 'C' in amounts and 'H' in amounts and set(amounts) <= {'C', 'H', 'O', 'N', 'P', 'S', 'F', 'Cl', 'Br', 'I'}:
        order = lambda m: (0 if m[1] == 'C' else 1 if m[1] == 'H' else 2, m[1])
    elif all(symbol in _ORDER for symbol in amounts):
        order = lambda m: (_ORDER[m[1]],)
    else:
        return compact
    return ''.join(m[1] + (m[2] or '') for m in sorted(tokens, key=order))


@lru_cache(maxsize=4096)
def formula_html(text: str) -> str:
    """Real subscripts, including decimal amounts; ordinary names stay text."""
    if _formula_parts(text) is None:
        return escape(text)
    canonical = canonical_display_formula(text)
    return _SUBSCRIPT.sub(lambda m: m[1] + '<sub>' + m[2] + '</sub>', escape(canonical))


class FormulaDisplayDelegate(QStyledItemDelegate):
    """Paint chemistry without replacing any QTableWidgetItem model value."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = canonical_display_formula(str(index.data() or ''))

    def paint(self, painter, option, index):
        raw = str(index.data() or '')
        html = formula_html(raw)
        if '<sub>' not in html:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        color = opt.palette.color(QPalette.ColorRole.HighlightedText if opt.state & QStyle.StateFlag.State_Selected
                                  else QPalette.ColorRole.Text)
        opt.text = ''
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        document = QTextDocument()
        document.setDocumentMargin(0.)
        document.setDefaultFont(opt.font)
        document.setHtml(f'<span style="color:{color.name()}; white-space:nowrap;">{html}</span>')
        width = document.idealWidth()
        ellipsis = opt.fontMetrics.horizontalAdvance('…') if width > rect.width() else 0
        painter.save()
        painter.setClipRect(rect)
        painter.translate(rect.left(), rect.top() + (rect.height() - document.size().height())*.5)
        document.drawContents(painter, QRectF(0., 0., max(0., rect.width()-ellipsis), document.size().height()))
        painter.restore()
        if ellipsis:
            painter.save()
            painter.setPen(color)
            painter.drawText(rect.adjusted(rect.width()-ellipsis, 0, 0, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, '…')
            painter.restore()
