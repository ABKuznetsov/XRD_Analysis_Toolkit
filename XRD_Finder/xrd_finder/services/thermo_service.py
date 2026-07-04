from __future__ import annotations

from xrd_finder.core.series import SeriesAnalysis


class ThermoService:
    def create_temperature_series(self, name: str = "Temperature series") -> SeriesAnalysis:
        return SeriesAnalysis.create(name=name, kind="temperature")
