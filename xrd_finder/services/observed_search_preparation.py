from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import numpy as np

from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.preprocessing_service import (
    AutoPreprocessingResult, auto_preprocess_for_scoring, estimate_background,
)
from xrd_finder.ui.peak_matching import ObservedLineRecord, observed_peak_records


class ObservedSearchCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ObservedSearchInput:
    observed: np.ndarray
    preprocess_auto: bool
    background_removed: bool
    instrument_profile: InstrumentProfile | None
    preprocessing: AutoPreprocessingResult | None = None
    global_zero_shift: float = 0.0

    def __post_init__(self):
        data = np.asarray(self.observed, dtype=float)
        owned = np.frombuffer(data.tobytes(), dtype=float).reshape(data.shape)
        object.__setattr__(self, 'observed', owned)
        object.__setattr__(self, 'instrument_profile', deepcopy(self.instrument_profile))
        object.__setattr__(self, 'preprocessing', deepcopy(self.preprocessing))


@dataclass(frozen=True, slots=True)
class ObservedSearchResult:
    x: np.ndarray
    corrected: np.ndarray
    records: list[ObservedLineRecord]
    preprocessing: AutoPreprocessingResult | None


def prepare_observed_search(inputs: ObservedSearchInput, *, cancelled=lambda: False,
                            refine_peaks: bool = True) -> ObservedSearchResult:
    def check_cancelled():
        if cancelled():
            raise ObservedSearchCancelled()

    check_cancelled()
    x, y = inputs.observed[:, 0], inputs.observed[:, 1]
    preprocessing = None
    if inputs.preprocess_auto:
        preprocessing = inputs.preprocessing
        if preprocessing is None:
            preprocessing = auto_preprocess_for_scoring(x, y)
        x, corrected = preprocessing.x, preprocessing.corrected_y
    elif inputs.background_removed:
        corrected = y
    else:
        corrected = y - estimate_background(x, y, degree=10, method='auto')
    check_cancelled()
    # Position selection can reuse the radiation-aware detector without paying
    # for individual profile fits. Existing Match/Gain preparation is unchanged.
    options = {} if refine_peaks else {'refine_peak': lambda *_args, **_kwargs: None}
    records = observed_peak_records(
        x, corrected, limit=80, instrument_profile=inputs.instrument_profile,
        residual=False, global_zero_shift=inputs.global_zero_shift,
        **options,
    )
    check_cancelled()
    return ObservedSearchResult(x, corrected, records, preprocessing)
