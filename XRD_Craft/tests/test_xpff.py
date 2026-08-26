from __future__ import annotations

import json
import zipfile

import pytest

from crystal_viewer.core.xpff import load_xpff_structures


def _cif(name: str, element: str = "Si") -> str:
    return f"""data_{name}
_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_name_H-M_alt 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
{element}1 {element} 0 0 0
"""


def _archive(tmp_path, manifest: dict, members: dict[str, str]):
    path = tmp_path / "project.xpff"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
        for member, content in members.items():
            archive.writestr(member, content)
    return path


def test_loads_distinct_candidates_referenced_across_all_finder_profiles(tmp_path) -> None:
    manifest = {
        "id": "project-1",
        "name": "Finder project",
        "structures": [],
        "phases": [],
        "finder_state": {
            "match_candidates": [
                {"Source": "COD", "Entry": "100", "Phase": "Selected phase"}
            ],
            "candidate_cif_paths": {
                "COD:100": "assets/candidates/selected.cif",
                "COD:200": "assets/candidates/profile.cif",
                "COD:300": "assets/candidates/unreferenced.cif",
            },
            "profile_states": {
                "pattern-1": {
                    "candidates": [
                        {"Source": "COD", "Entry": "100", "Phase": "Selected phase"},
                        {"Source": "COD", "Entry": "200", "Phase": "Profile phase"},
                    ]
                },
                "pattern-2": {
                    "candidates": [
                        {"Source": "COD", "Entry": "200", "Phase": "Profile phase"}
                    ]
                },
            },
        },
    }
    path = _archive(
        tmp_path,
        manifest,
        {
            "assets/candidates/selected.cif": _cif("selected", "Si"),
            "assets/candidates/profile.cif": _cif("profile", "Al"),
            "assets/candidates/unreferenced.cif": _cif("unreferenced", "Ca"),
        },
    )

    structures = load_xpff_structures(path)

    assert [item.name for item in structures] == [
        "Selected phase · COD 100",
        "Profile phase · COD 200",
    ]
    assert {site.element for site in structures[0].asymmetric_sites} == {"Si"}
    assert {site.element for site in structures[1].asymmetric_sites} == {"Al"}
    assert str(structures[0].source_path).endswith("project.xpff#COD:100")


def test_loads_explicit_structures_and_phases_then_deduplicates_members(tmp_path) -> None:
    manifest = {
        "id": "project-2",
        "name": "Saved structures",
        "structures": [
            {"id": "structure-1", "name": "Refined", "source_path": "assets/cif/refined.cif"}
        ],
        "phases": [
            {"id": "phase-1", "name": "Reference", "source_path": "assets/cif/reference.cif"},
            {"id": "phase-duplicate", "name": "Duplicate", "source_path": "assets/cif/refined.cif"},
        ],
        "finder_state": {"match_candidates": [], "candidate_cif_paths": {}},
    }
    path = _archive(
        tmp_path,
        manifest,
        {
            "assets/cif/refined.cif": _cif("refined", "B"),
            "assets/cif/reference.cif": _cif("reference", "O"),
        },
    )

    structures = load_xpff_structures(path)

    assert [item.name for item in structures] == ["Refined", "Reference"]
    assert len({str(item.source_path) for item in structures}) == 2


def test_missing_selected_candidate_member_has_contextual_error(tmp_path) -> None:
    path = _archive(
        tmp_path,
        {
            "finder_state": {
                "match_candidates": [{"Source": "COD", "Entry": "404"}],
                "candidate_cif_paths": {"COD:404": "assets/candidates/missing.cif"},
            }
        },
        {},
    )

    with pytest.raises(ValueError, match=r"COD:404.*missing\.cif"):
        load_xpff_structures(path)


def test_rejects_archive_without_selected_or_saved_structures(tmp_path) -> None:
    path = _archive(
        tmp_path,
        {
            "finder_state": {
                "match_candidates": [],
                "candidate_cif_paths": {"COD:200": "assets/candidates/cache-only.cif"},
            }
        },
        {"assets/candidates/cache-only.cif": _cif("cached")},
    )

    with pytest.raises(ValueError, match="selected or saved crystal structures"):
        load_xpff_structures(path)


def test_rejects_unsafe_archive_member(tmp_path) -> None:
    path = _archive(
        tmp_path,
        {
            "structures": [{"id": "bad", "source_path": "../outside.cif"}],
            "finder_state": {},
        },
        {},
    )

    with pytest.raises(ValueError, match="Unsafe XPFF archive member"):
        load_xpff_structures(path)
