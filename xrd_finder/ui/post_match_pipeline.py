from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class PostMatchPipeline:
    """Independent stages that run after a Match candidate is accepted."""

    refresh_selected_profile: Callable[..., None]
    refine_indexed_cells: Callable[..., bool]
    refresh_gain: Callable[[], None]
    should_autozoom: Callable[[], bool]

    def candidate_added(self) -> None:
        """Estimate the accepted cell while rendering, then refresh Gain.

        FinderService performs the fast indexed-position estimate. The separate
        full cell-fit action remains explicit rather than running a second fit
        automatically for every acceptance.
        """

        self.run_profile_stage()
        self.run_gain_stage()

    def run_profile_stage(self) -> None:
        self.refresh_selected_profile(
            auto_zoom=self.should_autozoom(),
            active_only=True,
        )

    def run_cell_stage(self) -> bool:
        return bool(
            self.refine_indexed_cells(
                show_messages=False,
                recalculate=False,
                latest_only=True,
            )
        )

    def run_gain_stage(self) -> None:
        self.refresh_gain()
