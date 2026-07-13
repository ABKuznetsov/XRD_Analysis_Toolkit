from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class CalculationContext:
    wavelength: float
    primary_wavelength: float
    fwhm: float
    two_theta_min: float
    two_theta_max: float
    x_grid_fingerprint: tuple[int, float, float, int]
    profile_eta: float = 0.0
    global_zero_shift: float = 0.0
    cell_scale: float = 1.0

    def with_alignment(self, global_zero_shift: float, cell_scale: float = 1.0) -> "CalculationContext":
        return replace(
            self,
            global_zero_shift=float(global_zero_shift),
            cell_scale=float(cell_scale),
        )

    @property
    def sticks_key(self) -> tuple[float, float, float]:
        return (
            round(float(self.primary_wavelength), 7),
            round(float(self.two_theta_min), 4),
            round(float(self.two_theta_max), 4),
        )

    @property
    def profile_key(self) -> tuple[float, float, float, tuple[int, float, float, int], float, float]:
        return (
            round(float(self.fwhm), 6),
            round(float(self.profile_eta), 5),
            round(float(self.wavelength), 7),
            self.x_grid_fingerprint,
            round(float(self.global_zero_shift), 6),
            round(float(self.cell_scale), 7),
        )
