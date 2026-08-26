from __future__ import annotations

from collections.abc import Iterable

from crystal_viewer.core.model import AtomSite


def atom_legend_labels(
    sites: Iterable[AtomSite],
    *,
    split_occupancies: bool,
    show_vacancies: bool,
) -> tuple[str, ...]:
    """Return unique chemical legend labels; occupancy stays encoded in sphere sectors."""
    labels: set[str] = set()
    for site in sites:
        if split_occupancies and site.is_disordered:
            labels.update(component.element for component in site.components)
            if show_vacancies and site.vacancy_fraction > 1e-6:
                labels.add("Vacancy")
        else:
            labels.add(site.element)
    return tuple(sorted(labels))
