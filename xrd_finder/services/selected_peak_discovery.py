from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable
from pathlib import Path

from xrd_finder.services.candidate_rows import normalize_candidate_row
from xrd_finder.services.candidate_search_service import CandidateSearchOptions, CandidateSearchService
from xrd_finder.services.network import offline_mode_enabled
from xrd_finder.services.selected_peak_search import SelectedPeakQuery, SelectedPeakSearchResult


def search_with_discovery(
    index_path: str | Path, query: SelectedPeakQuery, options: CandidateSearchOptions,
    service: CandidateSearchService, *, derived_version: int,
    scan: Callable[..., SelectedPeakSearchResult], session_token: int,
    progress: Callable[[str, int, int], None], cancelled: Callable[[], bool],
    partial: Callable[[SelectedPeakSearchResult], None] | None = None,
) -> SelectedPeakSearchResult:
    """Publish indexed matches first; acquisition never supplies scores."""
    def local():
        return scan(index_path, query, derived_version=derived_version,
                    progress=progress, cancelled=cancelled)

    result = local()
    if result.cancelled:
        return result
    if cancelled():
        return replace(result, candidates=(), cancelled=True)
    online = any((options.cod_online_enabled, options.materials_project_enabled,
                  options.aflow_enabled, options.oqmd_enabled))
    # These structural APIs query composition, not measured powder peaks.
    if not online or offline_mode_enabled() or not query.required_elements:
        return result
    if partial is not None:
        partial(result)
    discovery_options = replace(options, observed_peak_positions=[], defer_candidate_preparation=False)
    rows = service.search_elements(
        list(query.required_elements), discovery_options, progress=progress,
        partial_results=lambda rows: None, session_token=session_token, cancelled=cancelled,
    )
    if cancelled():
        return replace(result, candidates=(), cancelled=True)
    service.queue_candidate_rows(rows, session_token=session_token, cancelled=cancelled)
    result = local()
    errors = []
    for row in rows:
        values = normalize_candidate_row(row)
        if not values[1] and any('failed' in str(value).lower() for value in row):
            errors.append(' '.join(str(value) for value in row if value))
    if errors:
        if partial is not None and not result.cancelled:
            partial(result)
        raise RuntimeError('Online selected-peak search is incomplete: ' + '; '.join(errors))
    return result
