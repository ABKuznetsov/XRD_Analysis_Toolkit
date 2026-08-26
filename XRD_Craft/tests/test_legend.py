from crystal_viewer.core.model import AtomSite, SiteComponent
from crystal_viewer.ui.legend import atom_legend_labels


def test_atom_legend_has_unique_elements_without_occupancy_values() -> None:
    sites = [
        AtomSite("Al1", "Al", (0.0, 0.0, 0.0)),
        AtomSite(
            "T1",
            "Al/Si",
            (0.5, 0.5, 0.5),
            components=(SiteComponent("Al", 0.5), SiteComponent("Si", 0.4)),
        ),
    ]

    assert atom_legend_labels(sites, split_occupancies=True, show_vacancies=True) == (
        "Al",
        "Si",
        "Vacancy",
    )
