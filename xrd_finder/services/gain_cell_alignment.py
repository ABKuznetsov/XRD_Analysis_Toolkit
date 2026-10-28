"""Job-local indexed cell alignment with a fixed experimental zero."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from cristma.core import MeasuredValue, UnitCell
from cristma.diffraction import MillerIndex, ReciprocalMetric

from xrd_finder.finder.cell_parameter_estimator import CellParameterEstimate, FastCellParameterEstimator
from xrd_finder.finder.models import ObservedPeak
from xrd_finder.services.calculated_pattern_service import HKLPeak


@dataclass(frozen=True)
class GainCellAlignment:
    estimate: CellParameterEstimate
    peaks: tuple[HKLPeak, ...]


def refine_gain_cell(*, initial_cell, peaks, records, wavelength, zero_shift_deg):
    """Propose a metric from indexed residual lines, without changing F2 or zero."""
    if not peaks or any((peak.h, peak.k, peak.l) == (0, 0, 0) for peak in peaks):
        return None
    observed = [ObservedPeak(float(record.two_theta), float(record.area), float(record.fwhm))
                for record in records]
    estimate = FastCellParameterEstimator().estimate(
        initial_cell=initial_cell, calculated_peaks=list(peaks), observed_peaks=observed,
        wavelength=float(wavelength), zero_shift_deg=float(zero_shift_deg), refine_zero_shift=False)
    if estimate is None:
        return None
    native_cell = UnitCell(*[
        MeasuredValue(float(getattr(estimate.cell, name)), None, str(getattr(estimate.cell, name)))
        for name in ('a', 'b', 'c', 'alpha', 'beta', 'gamma')])
    metric = ReciprocalMetric.from_cell(native_cell)
    aligned = []
    for peak in peaks:
        d = metric.d_spacing(MillerIndex(peak.h, peak.k, peak.l))
        argument = float(wavelength) / (2.0 * d)
        if not 0.0 < argument < 1.0:
            continue
        angle = 2.0 * math.degrees(math.asin(argument)) + float(zero_shift_deg)
        aligned.append(replace(peak, d=d, two_theta=angle))
    return GainCellAlignment(estimate, tuple(aligned)) if aligned else None
