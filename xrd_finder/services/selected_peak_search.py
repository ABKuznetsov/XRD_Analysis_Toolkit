from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3
from typing import Callable, Iterable

import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass(frozen=True, slots=True)
class SelectedPeakQuery:
    selected_two_theta: tuple[float, ...]
    wavelength: float
    tolerance_two_theta_deg: float
    zero_shift_deg: float = 0.
    sources: tuple[str, ...] = ()
    required_elements: tuple[str, ...] = ()
    excluded_elements: tuple[str, ...] = ()
    allow_inorganic: bool = True
    allow_organic: bool = True
    selected_intensities: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        values = (self.wavelength, self.tolerance_two_theta_deg, self.zero_shift_deg)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("Wavelength, position tolerance and zero correction must be finite")
        if self.wavelength <= 0. or self.tolerance_two_theta_deg <= 0.:
            raise ValueError("Wavelength and position tolerance must be positive")
        angles = tuple(sorted(set(float(value) for value in self.selected_two_theta)))
        if not angles or any(not math.isfinite(value) or not 0. < value < 180.
                             or not 0. < value - self.zero_shift_deg < 180. for value in angles):
            raise ValueError("Select at least one valid peak between 0 and 180 degrees after zero correction")
        if self.selected_intensities is not None:
            if len(self.selected_intensities) != len(self.selected_two_theta):
                raise ValueError('Each selected peak needs one intensity.')
            weights = {}
            for angle, raw in zip(self.selected_two_theta, self.selected_intensities, strict=True):
                value = float(raw)
                if not math.isfinite(value) or not 0. <= value <= 100.:
                    raise ValueError('Manual peak intensities must be between 0 and 100.')
                value = round(value, 2)
                if value > 0.:
                    weights[float(angle)] = max(weights.get(float(angle), 0.), value)
            if not weights:
                raise ValueError('At least one manual peak must have intensity above zero.')
            angles = tuple(sorted(weights))
            object.__setattr__(self, 'selected_intensities', tuple(weights[a] for a in angles))
        object.__setattr__(self, "selected_two_theta", angles)
        object.__setattr__(self, "sources", tuple(sorted({str(source).strip().upper() for source in self.sources if str(source).strip()})))


@dataclass(frozen=True, slots=True)
class SelectedPeakMatch:
    selected_two_theta: float
    corrected_two_theta: float
    selected_d: float
    reference_d: float
    reference_two_theta: float
    angle_error_deg: float


@dataclass(frozen=True, slots=True)
class SelectedPeakAssessment:
    selected_count: int
    matches: tuple[SelectedPeakMatch, ...]
    selected_weights: tuple[tuple[float, float], ...] = ()

    @property
    def matched_count(self) -> int:
        return len(self.matches)

    @property
    def coverage_percent(self) -> float:
        if self.selected_weights:
            matched = {match.selected_two_theta for match in self.matches}
            return 100.*sum(w for a, w in self.selected_weights if a in matched)/sum(w for _, w in self.selected_weights)
        return 100. * self.matched_count / self.selected_count

    @property
    def mean_angle_error_deg(self) -> float | None:
        return float(np.mean([match.angle_error_deg for match in self.matches])) if self.matches else None


@dataclass(frozen=True, slots=True)
class SelectedPeakCandidate:
    source: str
    entry_id: str
    formula: str
    name: str
    spacegroup: str
    iic: float | None
    iic_method: str
    derived_version: int
    match: SelectedPeakAssessment


@dataclass(frozen=True, slots=True)
class SelectedPeakSearchResult:
    query: SelectedPeakQuery
    candidates: tuple[SelectedPeakCandidate, ...] = ()
    cancelled: bool = False


class SelectedPeakSearchError(RuntimeError):
    pass


def _d_at(angle: float, wavelength: float) -> float:
    return wavelength / (2. * math.sin(math.radians(angle / 2.)))


def _d_windows(query: SelectedPeakQuery) -> list[tuple[float, float]]:
    windows = []
    for raw in query.selected_two_theta:
        angle = raw - query.zero_shift_deg
        low = angle - query.tolerance_two_theta_deg
        high = angle + query.tolerance_two_theta_deg
        d_low = _d_at(high, query.wavelength) if high < 180. else query.wavelength / 2.
        d_high = _d_at(low, query.wavelength) if low > 0. else math.inf
        windows.append((float(np.nextafter(d_low, -math.inf)), float(np.nextafter(d_high, math.inf))))
    return windows


def match_selected_peaks(query: SelectedPeakQuery, reference_d_spacings: Iterable[float]) -> SelectedPeakAssessment:
    """Maximize one-to-one selected-line coverage, then minimize position error.

    No reference-intensity term, missing-reference-line penalty, automatic zero
    fit, cell deformation or minimum three-line gate is applied here.
    """
    selected = np.asarray(query.selected_two_theta, dtype=float)
    corrected = selected - query.zero_shift_deg
    references = np.asarray(sorted({float(value) for value in reference_d_spacings
                                    if math.isfinite(float(value)) and float(value) >= query.wavelength / 2.}), dtype=float)
    count = len(selected)
    weights = tuple(zip(query.selected_two_theta, query.selected_intensities, strict=True)) if query.selected_intensities is not None else ()
    if not len(references):
        return SelectedPeakAssessment(count, (), weights)
    angles = np.degrees(2. * np.arcsin(query.wavelength / (2. * references)))
    windows = _d_windows(query)
    allowed = np.asarray([(references >= low) & (references <= high) for low, high in windows])
    errors = np.abs(corrected[:, None] - angles[None, :])
    # Each real edge costs at most 1. An unmatched peak costs n+1, so one
    # additional match always wins over every possible sum of n residuals.
    costs = np.full((count, len(references) + count), float(count + 1))
    costs[:, :len(references)] = np.where(
        allowed, np.minimum(errors / query.tolerance_two_theta_deg, 1.), np.inf)
    if query.selected_intensities is not None:
        # Intensities have 0.01 resolution. One weight unit must outweigh the
        # sum of all angular-error tie breakers, just as count does above.
        units = np.rint(np.asarray(query.selected_intensities)*100.)
        costs[:] = 0.
        costs[:, :len(references)] = np.where(allowed,
            -units[:, None]*(count+1)+np.minimum(errors/query.tolerance_two_theta_deg, 1.), np.inf)
    rows, columns = linear_sum_assignment(costs)
    matches = tuple(
        SelectedPeakMatch(float(selected[row]), float(corrected[row]),
                          _d_at(float(corrected[row]), query.wavelength),
                          float(references[column]), float(angles[column]), float(errors[row, column]))
        for row, column in zip(rows, columns) if column < len(references) and allowed[row, column]
    )
    return SelectedPeakAssessment(count, matches, weights)


def search_selected_peaks(
    index_path: str | Path,
    query: SelectedPeakQuery,
    *,
    derived_version: int,
    progress: Callable[[str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> SelectedPeakSearchResult:
    """Search all eligible indexed phases, never a capped Auto-search shortlist.

    The connection is read-only. Only indexed d spacings and small card metadata
    are read; this operation cannot download, reindex, calculate CIFs or run Gain.
    """
    is_cancelled = cancelled or (lambda: False)
    stopped = SelectedPeakSearchResult(query, cancelled=True)
    if is_cancelled():
        return stopped
    if not query.sources:
        return SelectedPeakSearchResult(query)
    if not query.allow_inorganic and not query.allow_organic:
        return SelectedPeakSearchResult(query)
    where = ["p.derived_version = ?", f"p.source in ({', '.join('?' for _ in query.sources)})",
             "((pp.norm_intensity > 0 and pp.norm_intensity < ?) or (pp.intensity > 0 and pp.intensity < ?))"]
    params: list[object] = [int(derived_version), *query.sources, math.inf, math.inf]
    for elements, operator in ((query.required_elements, "exists"), (query.excluded_elements, "not exists")):
        for element in sorted(set(elements)):
            where.append(f"{operator} (select 1 from phase_elements e where e.source=p.source and e.entry_id=p.entry_id and e.element=?)")
            params.append(element)
    if query.allow_inorganic != query.allow_organic:
        # Preserve Finder's existing C-and-H material-class convention.
        organic = " and ".join(
            "exists (select 1 from phase_elements e where e.source=p.source and e.entry_id=p.entry_id and e.element=?)"
            for _ in ("C", "H"))
        where.append(f"({'not' if query.allow_inorganic else ''} ({organic}))")
        params.extend(("C", "H"))
    windows = _d_windows(query)
    entries: dict[tuple[str, str], tuple[dict, set[float]]] = {}
    uri = Path(index_path).resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            # All chunks must see the same index while preparation workers write.
            connection.execute("begin")
            connection.set_progress_handler(lambda: int(is_cancelled()), 5000)
            # Bound SQL bind parameters, not scientific evidence or candidates.
            for start in range(0, len(windows), 100):
                if is_cancelled():
                    return stopped
                batch = windows[start:start + 100]
                if progress:
                    progress("Reading local peak index", start, len(windows))
                values = ", ".join("(?, ?)" for _ in batch)
                cursor = connection.execute(
                    f"""with search_windows(min_d,max_d) as (values {values})
                    select p.source,p.entry_id,p.formula,p.name,p.spacegroup,p.iic,p.iic_method,p.derived_version,pp.d
                    from search_windows w
                    join phase_peaks pp on pp.d between w.min_d and w.max_d
                    join phases p on p.source=pp.source and p.entry_id=pp.entry_id
                    where {' and '.join(where)}""",
                    (*[value for bounds in batch for value in bounds], *params),
                )
                for row in cursor:
                    if is_cancelled():
                        return stopped
                    key = (row['source'], row['entry_id'])
                    if key not in entries:
                        metadata = dict(row)
                        metadata.pop('d')
                        entries[key] = (metadata, set())
                    entries[key][1].add(float(row['d']))
    except sqlite3.Error as exc:
        if is_cancelled():
            return stopped
        raise SelectedPeakSearchError(f"Local selected-peak search failed: {exc}. Results are incomplete.") from exc
    candidates = []
    for index, (metadata, spacings) in enumerate(entries.values()):
        if is_cancelled():
            return stopped
        assessment = match_selected_peaks(query, spacings)
        if assessment.matched_count:
            candidates.append(SelectedPeakCandidate(**metadata, match=assessment))
        if progress and (index % 25 == 0 or index + 1 == len(entries)):
            progress("Matching selected peaks", index + 1, len(entries))
    candidates.sort(key=lambda candidate: (-candidate.match.coverage_percent,
                                           -candidate.match.matched_count,
                                           candidate.match.mean_angle_error_deg,
                                           candidate.source, candidate.entry_id))
    return SelectedPeakSearchResult(query, tuple(candidates))
