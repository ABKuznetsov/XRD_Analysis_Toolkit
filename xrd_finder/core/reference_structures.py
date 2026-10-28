from __future__ import annotations

from pathlib import Path

from xrd_finder.core.structure import Structure


def corundum_reference_path() -> Path:
    return Path(__file__).with_name("corundum_reference.cif")


def create_corundum_reference_structure() -> Structure:
    """Read the single embedded reference, including its derived cell volume."""
    from xrd_finder.io.cif_loader import create_phase_from_cif

    _phase, structure = create_phase_from_cif(corundum_reference_path())
    return structure
