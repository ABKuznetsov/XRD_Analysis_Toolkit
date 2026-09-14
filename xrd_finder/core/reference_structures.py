from __future__ import annotations

from xrd_finder.core.structure import AtomSite, CellParameters, Structure


def create_corundum_reference_structure() -> Structure:
    """Return the embedded corundum reference used for I/Ic estimation."""
    structure = Structure.create("Corundum")
    structure.formula = "Al2O3"
    structure.space_group = "R -3 c"
    structure.space_group_number = "167"
    structure.cell = CellParameters(a=4.76060, b=4.76060, c=12.99400, alpha=90.0, beta=90.0, gamma=120.0)
    structure.symops = [
        "x,y,z",
        "-y,x-y,z",
        "-x+y,-x,z",
        "y,x,-z+1/2",
        "x-y,-y,-z+1/2",
        "-x,-x+y,-z+1/2",
        "x+2/3,y+1/3,z+1/3",
        "-y+2/3,x-y+1/3,z+1/3",
        "-x+y+2/3,-x+1/3,z+1/3",
        "y+2/3,x+1/3,-z+5/6",
        "x-y+2/3,-y+1/3,-z+5/6",
        "-x+2/3,-x+y+1/3,-z+5/6",
        "x+1/3,y+2/3,z+2/3",
        "-y+1/3,x-y+2/3,z+2/3",
        "-x+y+1/3,-x+2/3,z+2/3",
        "y+1/3,x+2/3,-z+7/6",
        "x-y+1/3,-y+2/3,-z+7/6",
        "-x+1/3,-x+y+2/3,-z+7/6",
    ]
    structure.atoms = [
        AtomSite(label="Al", element="Al", x=0.0, y=0.0, z=0.3522, occupancy=1.0),
        AtomSite(label="O", element="O", x=0.694, y=0.0, z=0.25, occupancy=1.0),
    ]
    return structure
