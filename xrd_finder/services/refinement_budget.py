"""One cooperative wall-clock deadline for a complete position-refinement step."""
from __future__ import annotations

import math
from time import monotonic


class RefinementDeadline(Exception):
    """Internal early exit; callers retain their last validated geometry."""


class RefinementBudget:
    def __init__(self, seconds: float = 2., *, clock=None):
        self._clock = monotonic if clock is None else clock
        self.started = self._clock()
        duration = float(seconds)
        self.deadline = self.started + (min(max(duration, 0.), 2.) if math.isfinite(duration) else 0.)

    @property
    def remaining(self):
        return max(0., self.deadline-self._clock())

    @property
    def elapsed(self):
        return max(0., self._clock()-self.started)

    @property
    def expired(self):
        # Reserve time for publishing the last validated result. Individual
        # numerical trials use bounded small arrays and check this same budget.
        return self.remaining <= .025

    def check(self):
        if self.expired:
            raise RefinementDeadline()
