"""Bounded candidate-cell proposals in measured-peak space at one scan zero."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

import numpy as np

from xrd_finder.services.gain_peak_search import score_gain_peak_candidate
from xrd_finder.services.gain_shortlist import common_zero_shift


@dataclass(frozen=True, slots=True)
class GainPeakScaleProposal:
    peaks: tuple
    d_spacing_scale: float
    zero_shift_deg: float


def propose_gain_peak_scale(peaks, context, *, wavelength, zero_shift):
    """Move all indexed d spacings together, never individual maxima or zero.

    This is a small identification aid, not a refined crystallographic cell.
    Native strengths and hkl remain unchanged; empirical cards are not warped.
    """
    original = tuple(peaks)
    if (not original or len(context.direct_records) < 3
            or not math.isfinite(wavelength) or wavelength <= 0
            or not math.isfinite(zero_shift)):
        return None
    for peak in original:
        if (not math.isfinite(peak.d) or peak.d <= 0
                or (peak.h, peak.k, peak.l) == (0, 0, 0)):
            return None
        argument = wavelength/(2.*peak.d)
        if not 0 < argument < 1:
            return None
        # Reject inconsistent/empirical d metadata rather than inventing a cell.
        if abs(math.degrees(2.*math.asin(argument))-peak.two_theta) > .02:
            return None

    usable = sorted((p for p in original if p.intensity > 0),
                    key=lambda p: -p.intensity)
    if not usable:
        return None
    maximum = usable[0].intensity
    usable = [p for p in usable[:42] if p.intensity >= .03*maximum]
    records = context.direct_records
    positions = np.asarray([r.two_theta for r in records])
    widths = np.clip([r.fwhm*.5 for r in records], .05, .18)
    d = np.asarray([p.d for p in usable])
    weights = np.sqrt([p.intensity/maximum for p in usable])
    scales = np.linspace(.99, 1.01, 41)
    angles = np.degrees(2.*np.arcsin(np.clip(wavelength/(2.*scales[:, None]*d), 0., 1.))) + zero_shift
    quality = np.exp(-.5*((angles[:, :, None]-positions)/widths)**2)
    support = np.max(quality, axis=2) @ weights
    index = np.lexsort((np.abs(scales-1.), -support))[0]
    scale = float(scales[index])
    if scale == 1.:
        return None

    def shifted(factor):
        return tuple(replace(p, d=p.d*factor,
            two_theta=math.degrees(2.*math.asin(wavelength/(2.*p.d*factor)))+zero_shift)
            for p in original if 0 < wavelength/(2.*p.d*factor) < 1.)

    candidate = shifted(scale)
    baseline = score_gain_peak_candidate(shifted(1.), context)
    proposed = score_gain_peak_candidate(candidate, context)
    if proposed.direct_matches < 3 or proposed.retrieval_score <= baseline.retrieval_score:
        return None
    return GainPeakScaleProposal(candidate, scale, float(zero_shift))


def refine_gain_peak_candidates(calculation, rows, preliminary, context):
    """Refine a bounded union of residual and remembered Match priorities."""
    search = context['peak_search']
    if len(search.direct_records) < 3:
        return
    scores = context.get('_gain_peak_candidate_scores', {})
    eligible = [i for i in preliminary if (e := scores.get(calculation._candidate_key(
        {'Source': rows[i][0], 'Entry': rows[i][1]}))) is not None
        and not e.equivalent_to_accepted]
    selected = set(sorted(eligible, key=lambda i: (-preliminary[i], i))[:64])
    hidden = getattr(calculation, '_candidate_hidden_match_by_key', {})

    def match_priority(index):
        row = rows[index]
        key = calculation._candidate_key({'Source': row[0], 'Entry': row[1]})
        return -calculation._percent_text_value(row[5] or hidden.get(key, '')), index

    # SQL residual rows need not arrive in Match order.
    selected.update(sorted(eligible, key=match_priority)[:64])
    wavelength, _doublet = calculation._gain_radiation()
    zero = common_zero_shift(calculation.match_zero_shifts.values())
    for index in sorted(selected):
        calculation._gain_check_cancelled()
        row = rows[index]
        candidate = {'Source': row[0], 'Entry': row[1], 'Formula': row[2], 'Phase': row[3]}
        key = calculation._candidate_key(candidate)
        if key in calculation.match_cell_scales or key in calculation.match_zero_shifts:
            continue  # Preserve explicit geometry supplied by the caller.
        raw = context.get('_gain_raw_peaks_cache', {}).get(key, ())
        proposal = propose_gain_peak_scale(raw, search, wavelength=wavelength, zero_shift=zero)
        if proposal is None:
            continue
        context.setdefault('_gain_cell_aligned_peaks', {})[key] = proposal.peaks
        context.setdefault('_gain_aligned_peaks_cache', {})[key] = proposal.peaks
        scores.pop(key, None)
        preliminary[index] = calculation._candidate_row_preliminary_gain(row, context)
        context.setdefault('_gain_peak_scale_refinement_by_key', {})[key] = {
            'd_spacing_scale': proposal.d_spacing_scale,
            'zero_shift_deg': proposal.zero_shift_deg,
        }
