"""Crystal Mechanics and structural DOF analysis package."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell

__all__ = ["AtomSite", "CrystalStructure", "UnitCell"]
__version__ = "1.0.1"


def __getattr__(name: str):
    if name in __all__:
        from crystal_viewer.core import model

        return getattr(model, name)
    raise AttributeError(name)
