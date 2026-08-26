from __future__ import annotations

import numpy as np
import pytest

from crystal_viewer.analysis.twin_law import (
    TwinLaw,
    TwinLawMode,
    twin_cartesian_transform,
    validate_distinct_twin,
)
from crystal_viewer.analysis.morphology import reciprocal_normal
from crystal_viewer.core.model import UnitCell


def test_reflection_plane_and_twofold_axis_have_expected_cartesian_orientation() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    vector = np.asarray((1.0, 2.0, 3.0))

    reflection = twin_cartesian_transform(
        cell,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
    )
    twofold = twin_cartesian_transform(
        cell,
        TwinLaw(TwinLawMode.TWOFOLD, axis_uvw=(0, 0, 1)),
    )

    np.testing.assert_allclose(reflection @ vector, (-1.0, 2.0, 3.0), atol=1e-12)
    np.testing.assert_allclose(twofold @ vector, (-1.0, -2.0, 3.0), atol=1e-12)
    assert np.linalg.det(reflection) == pytest.approx(-1.0)
    assert np.linalg.det(twofold) == pytest.approx(1.0)


def test_reciprocal_twin_matrix_uses_actual_nonorthogonal_cell_basis(nonorthogonal_cell) -> None:
    law = TwinLaw(
        TwinLawMode.MATRIX,
        reciprocal_matrix=((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),
    )

    transform = twin_cartesian_transform(nonorthogonal_cell, law)

    np.testing.assert_allclose(transform, -np.eye(3), atol=1e-10)
    np.testing.assert_allclose(transform.T @ transform, np.eye(3), atol=1e-10)
    source_normal = reciprocal_normal(nonorthogonal_cell, (1, 2, 3))
    target_normal = reciprocal_normal(nonorthogonal_cell, (-1, -2, -3))
    np.testing.assert_allclose(transform @ source_normal, target_normal, atol=1e-10)


@pytest.mark.parametrize(
    "matrix",
    (
        ((1.0, 0.0), (0.0, 1.0)),
        ((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ((float("nan"), 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ((1.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    ),
)
def test_invalid_or_metric_incompatible_matrix_is_rejected(nonorthogonal_cell, matrix) -> None:
    with pytest.raises(ValueError):
        twin_cartesian_transform(
            nonorthogonal_cell,
            TwinLaw(TwinLawMode.MATRIX, reciprocal_matrix=matrix),
        )


def test_parent_symmetry_operation_is_not_a_distinct_twin() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    identity = np.eye(3)
    reflection = twin_cartesian_transform(
        cell,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 0, 0)),
    )

    with pytest.raises(ValueError, match="crystal symmetry"):
        validate_distinct_twin(identity, (np.eye(3, dtype=int),), cell)

    validate_distinct_twin(reflection, (np.eye(3, dtype=int),), cell)


def test_nonidentity_parent_symmetry_operation_is_not_a_distinct_twin() -> None:
    cell = UnitCell(1.0, 1.0, 1.0)
    twofold_z = np.diag((-1.0, -1.0, 1.0))

    with pytest.raises(ValueError, match="crystal symmetry"):
        validate_distinct_twin(
            twofold_z,
            (np.eye(3, dtype=int), np.diag((-1, -1, 1))),
            cell,
        )
