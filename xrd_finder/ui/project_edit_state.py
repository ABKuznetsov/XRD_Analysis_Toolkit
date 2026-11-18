"""Compare project inputs without treating browsing or rebuilt caches as edits.

This projection is used only by the save prompt. Project files still retain
the complete view, reference metadata and calculated results.
"""

_VIEW_FIELDS = (
    'current_object_type', 'current_object_id', 'tree_expansion_state',
    'right_tab', 'candidate_current_row', 'match_current_row', 'plot_view_range',
    'checked_pattern_ids', 'checked_phase_ids', 'candidate_rows',
    'selected_elements', 'selected_element_order', 'element_states',
    'exclude_all_other_elements', 'search_text', 'name_text', 'formula_text',
    'ccdc_doi_text', 'inorganics_checked', 'organics_checked',
    'structural_data_checked', 'reference_patterns_checked',
    'rank_by_probability_checked', 'scoring_source',
)
_CALCULATED_FIELDS = (
    'match_quantities', 'match_iic', 'match_zero_shifts', 'match_cell_scales',
    'match_alignment_scores', 'analysis_preview_paths',
)
_PROFILE_CACHE_FIELDS = (
    'calculated_result', 'pending_position_alignment', 'result_snapshot',
    'zero_shift_auto_deg', 'zero_shift_observed_width_deg',
)
_CANDIDATE_METRICS = (
    'Match (%)', 'Gain (%)', 'I/Ic*', '_EstimatedCell', '_CellFitPeaks',
    '_CellFitInitialRmsDeg', '_CellFitRmsDeg', '_LeBailMessage',
    '_QuantificationError',
)


def _clean_candidates(candidates):
    for candidate in candidates or ():
        if isinstance(candidate, dict):
            for key in _CANDIDATE_METRICS:
                candidate.pop(key, None)


def project_edit_state(state):
    """Normalize a disposable asdict(Project) snapshot, retaining actual edits."""
    for key in ('root_path', 'updated_at', 'analysis_summary'):
        state.pop(key, None)
    finder = state.get('finder_state') or {}
    has_content = any(state.get(key) for key in (
        'patterns', 'phases', 'structures', 'series', 'analyses', 'refinements'))
    if not has_content and not finder.get('match_candidates'):
        state.pop('finder_state', None)
        return state
    for key in (*_VIEW_FIELDS, *_CALCULATED_FIELDS):
        finder.pop(key, None)
    _clean_candidates(finder.get('match_candidates'))
    for profile in finder.get('profile_states', {}).values():
        if isinstance(profile, dict):
            for key in _PROFILE_CACHE_FIELDS:
                profile.pop(key, None)
            _clean_candidates(profile.get('candidates'))
    # Current matches mirror the active pattern; selecting a different pattern
    # changes that mirror, while its stored per-pattern candidates stay intact.
    if finder.get('profile_states'):
        finder.pop('match_candidates', None)
    for pattern in state.get('patterns', ()):
        pattern.get('metadata', {}).pop('reference_labels_v1', None)
    return state
