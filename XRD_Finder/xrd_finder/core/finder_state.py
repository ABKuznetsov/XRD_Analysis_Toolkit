from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FinderProjectState:
    checked_pattern_ids: list[str] = field(default_factory=list)
    checked_phase_ids: list[str] = field(default_factory=list)
    current_object_type: str = ""
    current_object_id: str = ""
    tree_expansion_state: dict[str, bool] = field(default_factory=dict)
    show_all_selected_patterns: bool = False
    pattern_stack_offset_percent: int = 10
    normalize_observed_patterns: bool = False
    grid_visible: bool = True
    show_hkl_labels: bool = False
    right_tab: str = "Elements"
    candidate_rows: list[dict[str, str]] = field(default_factory=list)
    candidate_current_row: int = -1
    match_candidates: list[dict[str, str]] = field(default_factory=list)
    match_current_row: int = -1
    match_quantities: dict[str, float] = field(default_factory=dict)
    match_iic: dict[str, float] = field(default_factory=dict)
    match_zero_shifts: dict[str, float] = field(default_factory=dict)
    match_cell_scales: dict[str, float] = field(default_factory=dict)
    match_alignment_scores: dict[str, str] = field(default_factory=dict)
    profile_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    phase_colors: dict[str, str] = field(default_factory=dict)
    observed_pattern_colors: dict[str, str] = field(default_factory=dict)
    plot_view_settings: dict[str, Any] = field(default_factory=dict)
    plot_view_range: list[list[float]] = field(default_factory=list)
    selected_elements: list[str] = field(default_factory=list)
    selected_element_order: list[str] = field(default_factory=list)
    element_states: dict[str, str] = field(default_factory=dict)
    exclude_all_other_elements: bool = False
    search_text: str = ""
    name_text: str = ""
    formula_text: str = ""
    ccdc_doi_text: str = ""
    inorganics_checked: bool = True
    organics_checked: bool = False
    structural_data_checked: bool = True
    reference_patterns_checked: bool = False
    rank_by_probability_checked: bool = True
