from __future__ import annotations

from xrd_finder.instrument.models import InstrumentProfile


def packaged_instrument_profiles() -> tuple[InstrumentProfile, ...]:
    return (
        InstrumentProfile.default_cu_kalpha(),
    )
