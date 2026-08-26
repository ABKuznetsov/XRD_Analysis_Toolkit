from __future__ import annotations

from typing import Any

from crystal_viewer.core.model import AtomSite, CrystalStructure, SiteComponent, UnitCell


def to_pymatgen(structure: CrystalStructure):
    """Adapt the internal structure without collapsing disordered sites."""
    from pymatgen.core import Lattice, Structure

    lattice = Lattice.from_parameters(
        structure.cell.a,
        structure.cell.b,
        structure.cell.c,
        structure.cell.alpha,
        structure.cell.beta,
        structure.cell.gamma,
    )
    species = []
    for site in structure.sites:
        positive = [component for component in site.components if component.occupancy > 0.0]
        total = sum(float(component.occupancy) for component in positive)
        scale = 1.0 / total if total > 1.0 else 1.0
        species.append(
            {
                component.element: float(component.occupancy) * scale
                for component in positive
            }
        )
    properties = {
        "label": [site.label for site in structure.sites],
        "Uiso": [site.u_iso for site in structure.sites],
        "disorder_group": [site.disorder_group for site in structure.sites],
        "assembly": [site.assembly for site in structure.sites],
        "source_site_key": [site.source_site_key for site in structure.sites],
    }
    return Structure(
        lattice,
        species,
        [site.fractional for site in structure.sites],
        coords_are_cartesian=False,
        site_properties=properties,
    )


def from_pymatgen(structure: Any, name: str = "") -> CrystalStructure:
    """Adapt a pymatgen Structure used by structure_bulder and ThermoXRD."""
    lattice = structure.lattice
    cell = UnitCell(
        a=float(lattice.a),
        b=float(lattice.b),
        c=float(lattice.c),
        alpha=float(lattice.alpha),
        beta=float(lattice.beta),
        gamma=float(lattice.gamma),
    )
    sites = []
    for index, site in enumerate(structure):
        species = list(site.species.items())
        species.sort(
            key=lambda item: (
                -float(item[1]),
                getattr(item[0], "symbol", str(item[0])),
            )
        )
        symbols = [getattr(specie, "symbol", str(specie)) for specie, _ in species]
        components = tuple(
            SiteComponent(getattr(specie, "symbol", str(specie)), float(value))
            for specie, value in species
        )
        element = "/".join(symbols)
        occupancy = sum(float(value) for _, value in species)
        label = str(site.properties.get("label", f"{element}{index + 1}"))
        sites.append(
            AtomSite(
                label=label,
                element=element,
                fractional=tuple(float(value % 1.0) for value in site.frac_coords),
                occupancy=float(occupancy),
                u_iso=site.properties.get("Uiso"),
                components=components,
                disorder_group=str(site.properties.get("disorder_group", "")),
                assembly=str(site.properties.get("assembly", "")),
                source_site_key=str(site.properties.get("source_site_key", label)),
            )
        )
    try:
        space_group = structure.get_space_group_info()[0]
    except Exception:
        space_group = ""
    return CrystalStructure(
        name=name or str(getattr(structure.composition, "reduced_formula", "Structure")),
        cell=cell,
        asymmetric_sites=list(sites),
        sites=sites,
        formula=str(structure.composition.formula),
        space_group=space_group,
    )
