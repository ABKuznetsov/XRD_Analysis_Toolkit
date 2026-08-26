"""Bridges to structures produced by the existing scientific tools."""

from crystal_viewer.adapters.pymatgen import from_pymatgen, to_pymatgen

__all__ = ["from_pymatgen", "to_pymatgen"]
