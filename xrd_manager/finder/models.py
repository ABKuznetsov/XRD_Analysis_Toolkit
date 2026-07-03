from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PeakStatus(str, Enum):
    MATCHED = "matched"
    OVERLAPPING = "overlapping"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class PeakAssignment:
    candidate_key: str
    phase_name: str
    hkl: tuple[int, int, int]
    calc_two_theta: float
    delta_two_theta: float
    intensity_ratio: float


@dataclass(slots=True)
class ObservedPeak:
    two_theta: float
    intensity: float
    fwhm: float
    assignments: list[PeakAssignment] = field(default_factory=list)
    status: PeakStatus = PeakStatus.UNKNOWN


@dataclass(slots=True)
class FinderCandidateInput:
    cif_path: str
    entry_id: str = ""
    name: str = ""
    formula: str = ""
    source: str = ""


@dataclass(slots=True)
class FinderInput:
    pattern_path: str
    candidates: list[FinderCandidateInput]
    wavelength: float | None = None
    two_theta_min: float | None = None
    two_theta_max: float | None = None
    fwhm: float | None = None
    observed_x: list[float] | None = None
    observed_y: list[float] | None = None
    subtract_background: bool = True
    smoothing_window: int = 0
    snap_peak_positions: bool = True


@dataclass(slots=True)
class FinderCandidateResult:
    candidate_key: str
    entry_id: str
    name: str
    formula: str
    source: str
    scale: float = 0.0
    quantity_percent: float = 0.0
    score: float = 0.0
    matched_peaks: int = 0
    total_peaks: int = 0
    status: str = "unmatched"
    cell_scale: float = 1.0
    two_theta: list[float] = field(default_factory=list)
    profile: list[float] = field(default_factory=list)
    peak_two_theta: list[float] = field(default_factory=list)
    peak_reference_two_theta: list[float] = field(default_factory=list)
    peak_intensity: list[float] = field(default_factory=list)


@dataclass(slots=True)
class FinderResult:
    pattern_x: list[float]
    pattern_y: list[float]
    background: list[float]
    calculated_total: list[float]
    global_zero_shift: float
    fwhm: float
    candidates: list[FinderCandidateResult]
    observed_peaks: list[ObservedPeak] = field(default_factory=list)
