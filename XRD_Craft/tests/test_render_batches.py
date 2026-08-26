from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv

from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.scene import build_scene
from crystal_viewer.ui.render_batches import (
    CylinderInstance,
    GradientCylinderInstance,
    DetailLevel,
    OccupancySphereInstance,
    SphereInstance,
    SurfaceInstance,
    build_cylinder_batch,
    build_gradient_cylinder_batch,
    build_occupancy_sphere_batch,
    build_sphere_batch,
    build_surface_batch,
    detail_level_for_atom_count,
    group_spheres_by_material,
)

ROOT = Path(__file__).resolve().parents[1]


def test_detail_level_thresholds() -> None:
    assert detail_level_for_atom_count(500) is DetailLevel.HIGH
    assert detail_level_for_atom_count(501) is DetailLevel.MEDIUM
    assert detail_level_for_atom_count(2000) is DetailLevel.MEDIUM
    assert detail_level_for_atom_count(2001) is DetailLevel.LOW


def test_sphere_batch_preserves_centres_and_source_indices() -> None:
    instances = [
        SphereInstance((0.0, 0.0, 0.0), 0.4, 3),
        SphereInstance((2.0, 0.0, 0.0), 0.6, 8),
    ]

    mesh = build_sphere_batch(instances, DetailLevel.LOW)

    assert mesh is not None
    assert set(np.unique(mesh.cell_data["source_index"])) == {3, 8}
    assert np.isclose(mesh.bounds[0], -0.4, atol=0.03)
    assert np.isclose(mesh.bounds[1], 2.6, atol=0.03)


def test_occupancy_sphere_batch_uses_proportional_cell_colours() -> None:
    mesh = build_occupancy_sphere_batch(
        [
            OccupancySphereInstance(
                center=(0.0, 0.0, 0.0),
                radius=1.0,
                source_index=7,
                sectors=(
                    ((174, 184, 196), 0.50),
                    ((230, 182, 85), 0.30),
                    ((238, 241, 245), 0.20),
                ),
            )
        ],
        DetailLevel.HIGH,
    )

    assert mesh is not None
    colours, counts = np.unique(mesh.cell_data["occupancy_rgb"], axis=0, return_counts=True)
    fractions = {tuple(colour): count / counts.sum() for colour, count in zip(colours, counts)}
    assert np.isclose(fractions[(174, 184, 196)], 0.50, atol=0.06)
    assert np.isclose(fractions[(230, 182, 85)], 0.30, atol=0.06)
    assert np.isclose(fractions[(238, 241, 245)], 0.20, atol=0.06)
    assert set(np.unique(mesh.cell_data["source_index"])) == {7}


def test_cylinder_batch_preserves_endpoints_and_sources() -> None:
    mesh = build_cylinder_batch(
        [
            CylinderInstance((0.0, 0.0, 0.0), (0.0, 0.0, 2.0), 0.1, 4),
            CylinderInstance((2.0, 0.0, 0.0), (2.0, 1.0, 0.0), 0.2, 9),
        ],
        DetailLevel.LOW,
    )

    assert mesh is not None
    assert set(np.unique(mesh.cell_data["source_index"])) == {4, 9}
    assert mesh.bounds[5] >= 1.99
    assert mesh.bounds[3] >= 0.99


def test_gradient_cylinder_batch_uses_interpolated_point_colours() -> None:
    mesh = build_gradient_cylinder_batch(
        [
            GradientCylinderInstance(
                (0.0, 0.0, 0.0),
                (0.0, 0.0, 2.0),
                0.1,
                4,
                (255, 0, 0),
                (0, 0, 255),
            )
        ],
        DetailLevel.LOW,
    )

    assert mesh is not None
    assert "bond_rgb" in mesh.point_data
    assert "bond_rgb" not in mesh.cell_data
    assert tuple(mesh.point_data["bond_rgb"][np.argmin(mesh.points[:, 2])]) == (255, 0, 0)
    assert tuple(mesh.point_data["bond_rgb"][np.argmax(mesh.points[:, 2])]) == (0, 0, 255)
    assert set(np.unique(mesh.cell_data["source_index"])) == {4}


def test_group_spheres_by_material_has_bounded_groups() -> None:
    groups = group_spheres_by_material(
        [
            ("O", SphereInstance((0.0, 0.0, 0.0), 0.3, 0)),
            ("O", SphereInstance((1.0, 0.0, 0.0), 0.3, 1)),
            ("Si", SphereInstance((2.0, 0.0, 0.0), 0.4, 2)),
        ]
    )

    assert set(groups) == {"O", "Si"}
    assert len(groups["O"]) == 2


def test_gehlenite_supercell_material_group_count_is_bounded() -> None:
    structure = load_cif(ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif")
    scene = build_scene(structure, repeat=(4, 4, 4))

    atom_materials = {atom.site.element for atom in scene.atoms}
    bond_materials = {
        scene.atoms[index].site.element
        for bond in scene.bonds
        for index in (bond.first, bond.second)
    }

    assert len(atom_materials) <= 5
    assert len(bond_materials) <= 5


def test_surface_batch_translates_geometry_and_preserves_sources() -> None:
    tetra = pv.Tetrahedron().extract_surface()

    mesh = build_surface_batch(
        [
            SurfaceInstance(tetra, (0.0, 0.0, 0.0), 2),
            SurfaceInstance(tetra, (5.0, 0.0, 0.0), 7),
        ]
    )

    assert mesh is not None
    assert set(np.unique(mesh.cell_data["source_index"])) == {2, 7}
    assert mesh.bounds[1] > 5.0


def test_batches_do_not_use_repeated_pyvista_merge(monkeypatch) -> None:
    def forbidden_merge(*_args, **_kwargs):
        raise AssertionError("batch builders must assemble arrays directly")

    monkeypatch.setattr(pv, "merge", forbidden_merge)
    sphere = build_sphere_batch(
        [
            SphereInstance((0.0, 0.0, 0.0), 0.2, 1),
            SphereInstance((1.0, 0.0, 0.0), 0.2, 2),
        ],
        DetailLevel.LOW,
    )
    cylinder = build_cylinder_batch(
        [
            CylinderInstance((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.1, 1),
            CylinderInstance((1.0, 0.0, 0.0), (1.0, 0.0, 1.0), 0.1, 2),
        ],
        DetailLevel.LOW,
    )

    assert sphere is not None
    assert cylinder is not None


def test_surface_batch_accepts_triangle_strip_tubes() -> None:
    tube = pv.Line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)).tube(
        radius=0.1,
        n_sides=6,
    )
    assert tube.n_strips > 0

    mesh = build_surface_batch([SurfaceInstance(tube, (0.0, 0.0, 0.0), 5)])

    assert mesh is not None
    assert mesh.n_cells > 0
    assert set(np.unique(mesh.cell_data["source_index"])) == {5}
