"""Validate reported formula proportions against occupied native atom sites."""
from __future__ import annotations

import math
import re


class CifCompositionError(ValueError):
    """The declared composition cannot safely support quantitative analysis."""


def _occupied_components(structure):
    from cristma.symmetry.orbit import expand_structure
    atoms=expand_structure(structure).atoms
    if not atoms:
        raise ValueError('No occupied structural model')
    for atom in atoms:
        for component in atom.components:
            occupancy=float(component.occupancy.value)
            if not math.isfinite(occupancy) or not 0<=occupancy<=1:
                raise ValueError('Invalid atom or occupancy')
            if occupancy>0:
                symbol=component.species.require_element()
                yield symbol,component.species,occupancy


def occupied_composition(structure) -> dict[str, float]:
    """Occupied elements for chemical search, independent of Quant mass support."""
    composition={}
    for symbol,_species,occupancy in _occupied_components(structure):
        composition[symbol]=composition.get(symbol,0.)+occupancy
    if not composition:
        raise ValueError('No occupied structural model')
    return composition


def empirical_search_formula(composition: dict[str,float]) -> str:
    """Reduce integral cell counts without forcing fractional integer ratios.

    Carbon formulas keep native Hill order. For inorganic oxides oxygen goes
    last, so an occupied Ba4Si4O12 cell is presented as BaSiO3.
    """
    from cristma.chemistry.composition import Composition
    amounts=Composition.from_mapping(composition).as_dict()
    if all(value.is_integer() for value in amounts.values()):
        divisor=math.gcd(*(int(value) for value in amounts.values()))
        amounts={symbol:value/divisor for symbol,value in amounts.items()}
    if 'C' in amounts:
        return Composition.from_mapping(amounts).normalized_formula
    return ''.join(Composition.from_mapping({symbol:amounts[symbol]}).normalized_formula
                   for symbol in sorted(amounts,key=lambda symbol:(symbol=='O',symbol)))


def occupied_cell(structure) -> tuple[float, dict[str, float]]:
    """Mass and composition of exactly the native engine's occupied orbits."""
    from cristma.chemistry.species import IsotopeSpecies
    from xrd_finder.services.element_masses import atomic_weight
    total=0.
    composition={}
    for symbol,species,occupancy in _occupied_components(structure):
        if isinstance(species,IsotopeSpecies):
            raise ValueError('Isotope-specific cell masses are not supported for quantitative analysis')
        weight=atomic_weight(symbol)
        if not math.isfinite(weight) or weight<=0:
            raise ValueError('Invalid atom mass')
        total+=weight*occupancy
        composition[symbol]=composition.get(symbol,0.)+occupancy
    if not math.isfinite(total) or total<=0:
        raise ValueError('Unknown cell mass')
    return total,composition


def formula_amounts(formula: str) -> dict[str, float]:
    """Read complete numeric formulas, groups and middle-dot adducts.

    Variable occupancies, charges and other unhandled notation are explicit
    failures: extracting only recognizable element substrings is unsafe.
    """
    text=re.sub(r'\s+', '', formula)
    if not text or len(text)>1024:
        raise CifCompositionError(f'Cannot verify CIF formula: {formula!r}')
    position=0

    def number():
        nonlocal position
        match=re.match(r'(?:\d+(?:\.\d*)?|\.\d+)',text[position:])
        if match is None:return 1.
        position+=len(match.group())
        value=float(match.group())
        if not math.isfinite(value):raise CifCompositionError('Non-finite CIF formula coefficient')
        return value

    def group(closing='',depth=0):
        nonlocal position
        if depth>16:raise CifCompositionError('CIF formula nesting is too deep')
        amounts={}
        found=False
        while position<len(text) and text[position] not in ')]·':
            if text[position] in '([':
                end=')' if text[position]=='(' else ']'
                position+=1
                values=group(end,depth+1)
                if position>=len(text) or text[position]!=end:
                    raise CifCompositionError(f'Unbalanced CIF formula: {formula!r}')
                position+=1
            else:
                match=re.match(r'[A-Z][a-z]?',text[position:])
                if match is None:
                    raise CifCompositionError(f'Cannot verify CIF formula: {formula!r}')
                position+=len(match.group())
                values={match.group():1.}
            multiplier=number()
            for element,value in values.items():
                amounts[element]=amounts.get(element,0.)+value*multiplier
            found=True
        if not found:raise CifCompositionError(f'Empty CIF formula group: {formula!r}')
        return amounts

    result={}
    while position<len(text):
        multiplier=number()
        values=group()
        for element,value in values.items():result[element]=result.get(element,0.)+value*multiplier
        if position==len(text):break
        if text[position]!='·':raise CifCompositionError(f'Unbalanced CIF formula: {formula!r}')
        position+=1
        if position==len(text):raise CifCompositionError(f'Incomplete CIF formula: {formula!r}')
    if not result or not any(value>0 for value in result.values()) or any(
        not math.isfinite(value) or value<0 for value in result.values()
    ):
        raise CifCompositionError(f'Invalid CIF formula amounts: {formula!r}')
    return {element:value for element,value in result.items() if value>0}


def validate_composition(formula: str, occupied: dict[str,float]) -> None:
    if not formula or formula.strip() in {'.','?'}:
        return  # No reported formula; occupied positions still define mass.
    declared=formula_amounts(formula)
    total_declared=sum(declared.values())
    total_occupied=sum(occupied.values())
    if (set(declared)!=set(occupied) or not all(
        math.isclose(declared[element]/total_declared,occupied[element]/total_occupied,
                     rel_tol=.005,abs_tol=.0005) for element in declared
    )):
        actual=' '.join(f'{element}{value:g}' for element,value in sorted(occupied.items()))
        raise CifCompositionError(
            f'CIF formula {formula!r} conflicts with occupied composition {actual!r}; '
            'quantitative phase fractions are unavailable')


def chemical_search_key(formula: str) -> str:
    """Order/notation/formula-unit independent key; no guessed partial parse.

    Ratios use twelve significant digits to discard arithmetic roundoff from
    decimal group multiplication. This is a retrieval key, never Quant input.
    An unsupported declaration keeps its literal text-search path.
    """
    try:
        amounts=formula_amounts(formula or '')
        basis=min(amounts.values())
        ratios={symbol:value/basis for symbol,value in amounts.items()}
        if not all(math.isfinite(value) for value in ratios.values()):
            return ''
        return ';'.join(f'{symbol}:{value:.12g}' for symbol,value in sorted(ratios.items()))
    except (CifCompositionError,ValueError,OverflowError):
        return ''
