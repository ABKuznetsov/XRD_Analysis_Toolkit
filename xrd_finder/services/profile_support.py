"""Reflection coverage for the existing finite, area-normalized kernels."""
import math

PROFILE_KERNEL_WINDOW_FWHM = 25.


def profile_reflection_range(low, high, fwhm, *, wavelengths=(), zero_shift=0., cell_scale=1.):
    """Keep centres whose local kernel can intersect the sampled interval.

    This does not change the kernel or its finite 25-FWHM integration window.
    Multiple wavelengths can move a secondary component into the scan even
    when the primary-component centre lies below the visible marker range.
    """
    radius = PROFILE_KERNEL_WINDOW_FWHM * max(float(fwhm), 1.e-6)
    lower, upper = max(.001, float(low)-radius-float(zero_shift)), min(179.999, float(high)+radius-float(zero_shift))
    def inverse(angle, ratio):
        argument = float(cell_scale)*ratio*math.sin(math.radians(angle/2.))
        return math.degrees(2.*math.asin(min(1.,max(0.,argument))))
    components = tuple(float(w) for w in wavelengths)
    lower_ratio = components[0]/max(components) if components else 1.
    return max(.001,inverse(lower,lower_ratio)), min(179.999,inverse(upper,1.))
