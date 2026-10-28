"""Adapt measured-peak Gain to the window without using plotted phase scales."""
from __future__ import annotations

import numpy as np

from xrd_finder.finder.gain_policy import GainStage
from xrd_finder.services.gain_peak_search import build_gain_peak_search_context, score_gain_peak_candidate


def clear_gain_column(rows):
    result = []
    for row in rows:
        copied = list(row)
        copied.extend([''] * max(0, 7-len(copied)))
        copied[6] = ''
        result.append(copied)
    return result


def build_window_peak_gain_context(window):
    adapter = getattr(window, '_gain_observation', None)
    if adapter is not None:
        observed, saved_background, finder_observed, background_removed = adapter()
        if saved_background is not None and finder_observed is not None:
            observed = finder_observed
    else:
        pattern = window._active_pattern()
        observed = window._active_scoring_observed_data()
        saved_background = window._pattern_finder_background_data(pattern)
        background_removed = window._pattern_scoring_background_removed(pattern)
        if saved_background is not None:
            finder_observed = window._pattern_finder_observed_data(pattern)
            if finder_observed is not None and len(finder_observed):
                observed = finder_observed
    if observed is None or not len(observed):
        window._last_gain_debug = 'Gain: no observed data'
        return None
    x = np.asarray(observed[:, 0], dtype=float)
    y = np.asarray(observed[:, 1], dtype=float)
    if saved_background is not None:
        background = np.interp(x, saved_background[:, 0], saved_background[:, 1])
        signal = y-background
    elif getattr(window, '_scoring_source', 'Auto') == 'Auto' or background_removed:
        signal = y.copy()
    else:
        signal = y-np.asarray(window._estimate_background(x, y), dtype=float)
    if not np.all(np.isfinite(x)) or np.any(np.diff(x) <= 0) or not np.any(np.isfinite(signal)):
        window._last_gain_debug = 'Gain: invalid experimental grid'
        return None
    try:
        instrument = (window._gain_instrument_profile() if hasattr(window, '_gain_instrument_profile')
                      else window._instrument_profile_for_pattern(pattern))
    except (AttributeError, ValueError):
        instrument = None
    # The window wrapper supplies the active pattern's instrument itself.
    prepare_reuse = getattr(window, '_prepare_observed_peak_reuse', None)
    if prepare_reuse is not None:
        prepare_reuse(x, signal)
    records = window._observed_peak_records(x, signal, limit=160, residual=True)
    widths = [float(record.fwhm) for record in records if np.isfinite(record.fwhm) and record.fwhm > 0]
    width = max(float(np.median(widths)), .05) if widths else .18
    raw_patterns, patterns = [], []
    for candidate in window.match_candidates or []:
        peaks = tuple(window._candidate_peaks_for_gain(candidate) or ())
        if not peaks:
            window._last_gain_debug = 'Gain: waiting for selected reference lines'
            return None
        raw_patterns.append(peaks)
        patterns.append(tuple(window._adjusted_gain_peaks(candidate, peaks)))
    search = build_gain_peak_search_context(records, patterns, base_fwhm=width,
                                           two_theta_range=(float(x[0]),float(x[-1])))
    window._last_gain_debug = (f'Gain: {len(search.direct_records)} independent peaks, '
                              f'{len(search.overlap_records)} shared peaks')
    return {
        'key': (window._gain_context_key() if hasattr(window, '_gain_context_key')
                else window._active_probability_context_key()), 'x': x, 'target': signal,
        'fwhm': width, 'instrument_profile': instrument, 'peak_search': search,
        'selected_phase_patterns': search.accepted_patterns,
        'selected_phase_patterns_raw': raw_patterns,
        'selected_peak_positions': np.asarray([p.two_theta for phase in search.accepted_patterns for p in phase]),
    }


def score_window_peak_gain_row(window, row, context, *, preliminary=False):
    candidate = {'Source':row[0] if len(row)>0 else '', 'Entry':row[1] if len(row)>1 else '',
                 'Formula':row[2] if len(row)>2 else '', 'Phase':row[3] if len(row)>3 else ''}
    key = window._candidate_key(candidate)
    cache = context.setdefault('_gain_peak_candidate_scores', {})
    if key not in cache:
        peaks = window._candidate_aligned_gain_peaks_cached(candidate, context)
        # Canonical raw patterns catch variant cards before any cell adjustment.
        if window._candidate_duplicates_selected_phase(candidate, peaks, context):
            from xrd_finder.services.gain_peak_search import GainPeakCandidateScore
            cache[key] = GainPeakCandidateScore(equivalent_to_accepted=True)
        else:
            cache[key] = score_gain_peak_candidate(peaks, context['peak_search'])
        context.setdefault('_gain_dominant_evidence_by_key', {})[key] = (
            GainStage.DIRECT if cache[key].direct_score >= cache[key].overlap_score*.72 else GainStage.OVERLAP)
    return float(cache[key].retrieval_score if preliminary else cache[key].score)
