"""Load calculation dependencies after the workspace becomes interactive."""
from importlib import import_module

from xrd_finder.services.runtime_diagnostics import diagnostic_logger, trace_operation


CALCULATION_MODULES = (
    'scipy.ndimage',
    'scipy.signal',
    'scipy.optimize',
    'scipy.interpolate',
    'pybaselines',
)


def warm_calculation_modules(*, cancelled=lambda: False):
    """Import engines only; do not read libraries, fit profiles or touch Qt."""
    for name in CALCULATION_MODULES:
        if cancelled():
            return
        try:
            with trace_operation('startup.warm_calculation_module', module=name, slow_ms=0):
                import_module(name)
        except Exception:
            # Optional preparation must not interrupt the workspace. A real
            # operation retains its normal dependency error/fallback handling.
            diagnostic_logger().warning('event=startup.warmup_unavailable module=%s', name)
