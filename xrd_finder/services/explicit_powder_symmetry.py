"""Calculation-only full-cell representation for valid noncatalog CIF settings.

The reported cell is never changed. Expanding every orbit once and calculating
that complete cell in P1 preserves structure factors, including centering and
screw/glide cancellations. Powder families are regrouped using the ORIGINAL
rotations, so this representation does not add artificial independent lines.
"""
from __future__ import annotations

from dataclasses import replace
import math

from cristma.core.values import MeasuredValue
from cristma.crystallography import SpaceGroupCatalog
from cristma.crystallography.symmetry_context import SymmetryContext
from cristma.structure import IndependentSite
from cristma.symmetry.orbit import expand_structure

from xrd_finder.services.calculated_pattern_service import HKLPeak


SOURCE_OPERATIONS = "powder_source_symmetry_operations"


def systematically_absent(hkl, operations):
    # In a complete group the little group of h contains the identity. A
    # nontrivial EXACT translation character on that group forces F(h)=0.
    # This avoids treating floating-point cancellation noise as weak lines.
    for operation in operations:
        transformed = tuple(sum(hkl[i] * operation.rotation[i][j] for i in range(3))
                            for j in range(3))
        if transformed == hkl:
            phase = sum(hkl[i] * operation.translation[i] for i in range(3))
            if phase % 1:
                return True
    return False


def filter_absent_powder_families(lines, operations):
    if not operations:
        return lines
    families = tuple(f for f in lines.families
                     if not systematically_absent(f.representative_hkls[0].as_tuple(), operations))
    return replace(lines, families=families,
                   provenance=replace(lines.provenance, families_emitted=len(families)))


def explicit_powder_model(structure):
    """Validate exact reported symmetry before any full-cell calculation."""
    definition = structure.space_group
    if definition is None or definition.provenance not in {"reported", "derived"}:
        raise ValueError("Explicit powder calculation requires defined symmetry operations")
    context = SymmetryContext.from_definition(definition, structure.cell)
    expanded = expand_structure(structure)
    if not expanded.atoms:
        raise ValueError("Explicit powder calculation requires occupied atomic sites")
    sites = tuple(
        IndependentSite(
            id=atom.id, label=f"{atom.source_site_id}:{index}",
            components=atom.components,
            fractional=tuple(MeasuredValue(float(value), None, None) for value in atom.fractional),
            displacement=atom.displacement,
            metadata={"source_site_id": atom.source_site_id,
                      "source_operation": atom.representative_image.operation_id},
        )
        for index, atom in enumerate(expanded.atoms)
    )
    p1 = SpaceGroupCatalog.default().by_number(1)[0]
    calculation = replace(
        structure, sites=sites, properties=expanded.properties,
        space_group=p1.definition(provenance="derived"),
        metadata={**structure.metadata, SOURCE_OPERATIONS: context.operations,
                  "powder_source_group": definition,
                  "source_representation": "reported_symmetry_full_cell_P1_v1"},
    )
    return calculation, p1


def regroup_powder_peaks(peaks, operations):
    """Sum P1 Friedel families belonging to one original powder family."""
    if not operations:
        return tuple(peaks)
    rotations = sorted({tuple(tuple(int(x) for x in row) for row in op.rotation)
                        for op in operations})
    families = {}
    for peak in peaks:
        hkl = (peak.h, peak.k, peak.l)
        if systematically_absent(hkl, operations):
            continue
        orbit = [tuple(sum(hkl[i] * rotation[i][j] for i in range(3)) for j in range(3))
                 for rotation in rotations]
        key = min(orbit + [tuple(-x for x in member) for member in orbit])
        families.setdefault(key, []).append(peak)
    result = []
    for hkl, members in families.items():
        first = members[0]
        if any(not math.isclose(p.d, first.d, rel_tol=1e-8, abs_tol=1e-10) for p in members):
            raise ValueError("Fitted cell separates symmetry-equivalent powder reflections")
        raw = math.fsum(p.raw_intensity for p in members)
        if raw <= 0.:
            continue  # Systematic extinctions of the original operation set.
        intrinsic = math.fsum(float(p.intrinsic_intensity) for p in members)
        result.append(HKLPeak(
            h=hkl[0], k=hkl[1], l=hkl[2], d=first.d, two_theta=first.two_theta,
            intensity=raw, multiplicity=sum(p.multiplicity for p in members),
            f2=math.fsum(p.f2 for p in members), intrinsic_intensity=intrinsic,
            lp=first.lp, raw_intensity=raw, intensity_origin=first.intensity_origin,
        ))
    maximum = max((p.raw_intensity for p in result), default=0.)
    if maximum > 0.:
        for peak in result:
            peak.intensity = 100. * peak.raw_intensity / maximum
    return tuple(sorted(result, key=lambda p: (p.two_theta, p.h, p.k, p.l)))
