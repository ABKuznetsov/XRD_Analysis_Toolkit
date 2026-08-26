from __future__ import annotations

from pathlib import Path

import pytest

from crystal_viewer.core.document import load_document
from crystal_viewer.core.model import UnitCell


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def primitive_cubic_document():
    return load_document(ROOT / "tests/data/morphology/primitive_cubic.cif")


@pytest.fixture
def body_centered_document():
    return load_document(ROOT / "tests/data/morphology/body_centered.cif")


@pytest.fixture
def nonorthogonal_cell() -> UnitCell:
    return UnitCell(5.1, 6.2, 7.3, 78.0, 83.0, 71.0)
