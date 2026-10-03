from __future__ import annotations

import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from xrd_finder.ui.plot_view_settings import PlotViewSettings, PlotViewSettingsWidget
from xrd_finder.services.calculated_pattern_service import HKLPeak
from xrd_finder.ui.structure_overlay import prepare_structure_overlay


class PreviewSticksVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_checkbox_is_editable_and_persists_hidden_state(self):
        widget = PlotViewSettingsWidget()

        self.assertTrue(widget.layer_preview_peak_positions_checkbox.isEnabled())
        widget.layer_preview_peak_positions_checkbox.setChecked(False)
        self.assertFalse(widget.settings().layer_preview_peak_positions_visible)

        widget.set_settings(
            PlotViewSettings(layer_preview_peak_positions_visible=False),
            emit=False,
        )
        self.assertFalse(widget.layer_preview_peak_positions_checkbox.isChecked())

    def test_structure_preview_uses_indexed_cristma_peaks_when_supplied(self):
        class LegacyCalculatorMustNotRun:
            def calculate_sticks(self, *args, **kwargs):
                raise AssertionError("legacy structure-factor calculation was used")

        indexed_peak = HKLPeak(
            h=-1,
            k=-1,
            l=0,
            d=5.555178,
            two_theta=15.941,
            intensity=40.9803,
            multiplicity=4,
            raw_intensity=56780.207787,
        )

        overlay = prepare_structure_overlay(
            structure=object(),
            observed=None,
            calculated_pattern_service=LegacyCalculatorMustNotRun(),
            estimate_background=lambda x, y: np.zeros_like(x),
            observed_peak_positions=lambda x, y: np.array([], dtype=float),
            estimate_profile_fwhm=lambda x, y: 0.18,
            estimate_phase_alignment=lambda peaks, positions, structure: type(
                "Alignment", (), {"zero_shift": 0.0}
            )(),
            wavelength=1.54056,
            include_kalpha2=False,
            peaks_override=[indexed_peak],
        )

        self.assertEqual(len(overlay.peaks), 1)
        self.assertAlmostEqual(overlay.peaks[0].two_theta, 15.941, places=3)
        self.assertAlmostEqual(overlay.peaks[0].intensity, 40.9803, places=3)


if __name__ == "__main__":
    unittest.main()
