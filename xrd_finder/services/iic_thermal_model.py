"""Explicit isotropic approximation used only by theoretical I/Ic."""
from dataclasses import replace
import math

from cristma.core.values import MeasuredValue, parse_measured_value
from cristma.structure import DisplacementParameters

DEFAULT_UISO_ANGSTROM2 = .01


def _reported_biso(result, structure):
    """Recover reported B when an anisotropic tensor hid it in the mapper."""
    values = {}
    for block in result.document.blocks:
        if structure.id != f"cif:{block.name}":
            continue
        for loop in block.loops_with_tag('_atom_site_label'):
            label = loop.column_index('_atom_site_label')
            column = loop.column_index('_atom_site_B_iso_or_equiv')
            if column is None:
                continue
            for row in loop.row_tokens:
                value = parse_measured_value(row[column].raw)
                if value.value is not None:
                    values[row[label].value] = value
    return values


def iic_thermal_model(result):
    """Return a calculation-only result and a complete list of substitutions.

    Existing Uiso (including zero), Biso and reported Ueq stay authoritative.
    Only unavailable isotropic data use the operator's chosen default; invalid
    reported values are errors. The original CIF/document is never rewritten.
    """
    if not result.structures:
        raise ValueError("CIF contains no crystal structure for I/Ic calculation")
    structure = result.structures[0]
    reported_b = _reported_biso(result, structure)
    sites = []; assumptions = []; changed = False
    for site in structure.sites:
        displacement = site.displacement
        scalar = None if displacement is None else displacement.isotropic
        if scalar is not None and scalar.value is not None:
            value = float(scalar.value)
            if not math.isfinite(value) or value < 0.:
                raise ValueError(f"Invalid reported isotropic displacement for {site.label}")
            sites.append(site)
            continue
        if site.label in reported_b:
            value = reported_b[site.label]
            if not math.isfinite(float(value.value)) or value.value < 0.:
                raise ValueError(f"Invalid reported Biso for {site.label}")
            displacement = DisplacementParameters(kind='B_iso', isotropic=value, reported_kind='B')
        else:
            displacement = DisplacementParameters(kind='U_iso',
                isotropic=MeasuredValue(DEFAULT_UISO_ANGSTROM2, None, None, 'angstrom^2'))
            assumptions.append(dict(site=site.label, u_iso_angstrom2=DEFAULT_UISO_ANGSTROM2,
                reason='No reported isotropic displacement usable by the X-ray model'))
        sites.append(replace(site, displacement=displacement)); changed = True
    if changed:
        structure = replace(structure, sites=tuple(sites))
        result = replace(result, structures=(structure, *result.structures[1:]))
    return result, assumptions, changed
