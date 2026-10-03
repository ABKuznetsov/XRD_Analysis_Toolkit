from __future__ import annotations

import math

from cristma.diffraction import TchProfile

from xrd_finder.instrument.models import ResolutionProfile


_GAUSSIAN_FWHM_FACTOR = 2.0 * math.sqrt(2.0 * math.log(2.0))


def cristma_tch_profile(resolution: ResolutionProfile) -> TchProfile:
    """Convert Finder Caglioti coefficients to CRiStMa GSAS CW units.

    Finder stores ``U``, ``V`` and ``W`` in squared degrees so that the
    Gaussian FWHM is ``sqrt(U tan²θ + V tanθ + W)``.  Its ``X`` and ``Y``
    terms are in degrees.  CRiStMa 0.1.0b12 accepts the equivalent GSAS
    continuous-wave coefficients in centidegrees (variance for U/V/W).
    Keeping the conversion here prevents instrument profiles saved by Finder
    from becoming about 40–100 times narrower after the CRiStMa upgrade.
    """

    gaussian_scale = (100.0 / _GAUSSIAN_FWHM_FACTOR) ** 2
    lorentzian_scale = 100.0
    return TchProfile(
        u=float(resolution.u) * gaussian_scale,
        v=float(resolution.v) * gaussian_scale,
        w=float(resolution.w) * gaussian_scale,
        x=float(resolution.x) * lorentzian_scale,
        y=float(resolution.y) * lorentzian_scale,
    )


__all__ = ["cristma_tch_profile"]
