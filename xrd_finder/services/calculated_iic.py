"""Calculated Cu K-alpha1 RIR with a persistent, common corundum reference."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading

import cristma
from xrd_finder.io.native_cif_session import read_native_cif
from cristma.chemistry.species import IsotopeSpecies
from cristma.symmetry.orbit import expand_structure

from xrd_finder.core.reference_structures import corundum_reference_path
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
from xrd_finder.services.element_masses import atomic_weight


class CalculatedIic:
    """Ideal random-powder estimate, not a measured or database RIR value.

    Hubbard & Snyder (1988), doi:10.1017/S0885715600013257, equations 1--6:
    for equal mass fractions the common factors cancel, leaving
    [max(m |F|^2 LP) / (M_cell V_cell)] relative to corundum.
    No peak-height, sample-width, current-zoom or fitted-scale normalization.
    """

    def __init__(self, root: str | Path, adapter=None) -> None:
        self.root = Path(root)
        self.adapter = adapter or CristmaPowderAdapter()
        self.instrument = InstrumentProfile.default_cu_kalpha()
        self.parameters = {
            "method": "cristma-rir-v1", "cristma": version("cristma"),
            "reference": hashlib.sha256(corundum_reference_path().read_bytes()).hexdigest(),
            "radiation": asdict(self.instrument.radiation),
            "geometry": asdict(self.instrument.geometry),
            "range_deg": [5., 120.], "component": "primary", "scattering": "default-xray",
        }
        self.signature = hashlib.sha256(json.dumps(self.parameters, sort_keys=True).encode()).hexdigest()
        self.cache_path = self.root / f"corundum-{self.signature}.json"
        self._reference = None
        self._lock = threading.Lock()

    @staticmethod
    def strongest_line(peaks) -> float:
        # Only merge mathematically coincident lines within floating-point
        # roundoff, not reflections unresolved by a particular instrument.
        strongest, group, previous = 0., [], None
        for peak in sorted(peaks, key=lambda item: item.two_theta):
            angle, intensity = float(peak.two_theta), float(peak.raw_intensity)
            if not (math.isfinite(angle) and math.isfinite(intensity) and intensity >= 0.):
                raise ValueError("Non-finite native reference intensity")
            if previous is None or not math.isclose(angle, previous, rel_tol=64.*sys.float_info.epsilon):
                strongest = max(strongest, math.fsum(group))
                group = []
                previous = angle
            group.append(intensity)
        return max(strongest, math.fsum(group))

    def _phase_data(self, path, peaks=None) -> dict:
        result = read_native_cif(path)
        if any(getattr(item.severity, "value", "") in ("warning", "error") for item in result.diagnostics):
            raise ValueError("Calculated I/Ic requires a CIF without parser recovery")
        structure, _setting = self.adapter._structure_and_setting(path)
        mass = 0.
        for atom in expand_structure(structure).atoms:
            for component in atom.components:
                occupancy = float(component.occupancy.value)
                if not math.isfinite(occupancy) or not 0. <= occupancy <= 1.:
                    raise ValueError("Invalid occupied unit-cell mass")
                if occupancy == 0.:
                    continue
                if isinstance(component.species, IsotopeSpecies):
                    raise ValueError("Calculated I/Ic requires an isotope mass table")
                weight = atomic_weight(component.species.require_element())
                if not math.isfinite(weight) or weight <= 0.:
                    raise ValueError("Calculated I/Ic requires known atomic masses")
                mass += weight * occupancy
        volume = float(structure.cell.volume)
        if not (math.isfinite(mass) and mass > 0. and math.isfinite(volume) and volume > 0.):
            raise ValueError("Calculated I/Ic requires a positive unit-cell mass and volume")
        if peaks is None:
            peaks = self.adapter.reference_sticks_from_cif(
                path, two_theta_min=5., two_theta_max=120., instrument_profile=self.instrument, use_lp=True,
            )
        strongest = self.strongest_line(peaks)
        if strongest <= 0.:
            raise ValueError("No nonzero native diffraction lines for calculated I/Ic")
        return {"mass": mass, "volume": volume, "strongest": strongest,
                "power": strongest / (mass * volume), "peaks": [asdict(peak) for peak in peaks]}

    def reference_data(self) -> dict:
        with self._lock:
            if self._reference is not None:
                return self._reference
            try:
                saved = json.loads(self.cache_path.read_text(encoding="utf-8"))
                data = saved["data"]
                digest = hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()
                valid = (saved["signature"] == self.signature and saved["digest"] == digest
                         and all(math.isfinite(data[key]) and data[key] > 0.
                                 for key in ("mass", "volume", "strongest", "power"))
                         and data["power"] == data["strongest"] / (data["mass"] * data["volume"]))
                if valid:
                    self._reference = data
                    return data
            except (OSError, ValueError, KeyError, TypeError):
                pass
            data = self._phase_data(corundum_reference_path())
            payload = {"signature": self.signature, "parameters": self.parameters, "data": data,
                       "digest": hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()}
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as output:
                    temporary = Path(output.name)
                    json.dump(payload, output, sort_keys=True, allow_nan=False)
                os.replace(temporary, self.cache_path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self._reference = data
            return data

    def calculate(self, path, peaks=None) -> tuple[float, str]:
        fingerprint = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        reference = self.reference_data()
        phase = self._phase_data(path, peaks)
        value = phase["power"] / reference["power"]
        if not math.isfinite(value) or value <= 0.:
            raise ValueError("Calculated I/Ic is not positive and finite")
        if fingerprint != hashlib.sha256(Path(path).read_bytes()).hexdigest():
            raise ValueError("CIF changed during calculated I/Ic evaluation")
        return value, json.dumps({"signature": self.signature, "structure": fingerprint,
                                  "status": "calculated", "value": value, "parameters": self.parameters,
                                  "cell_mass": phase["mass"], "cell_volume": phase["volume"],
                                  "strongest_line": phase["strongest"],
                                  "reference_power": reference["power"]}, sort_keys=True)

    def current(self, metadata: str) -> bool:
        try:
            record = json.loads(metadata)
            return record.get("signature") == self.signature and record.get("status") in {"calculated", "unavailable"}
        except (ValueError, TypeError, AttributeError):
            return False

    def value_current(self, value, metadata: str) -> bool:
        if not self.current(metadata):
            return False
        record = json.loads(metadata)
        if record["status"] == "unavailable":
            return value is None
        return (isinstance(value, (int, float)) and math.isfinite(value) and value > 0.
                and record.get("value") == value)
