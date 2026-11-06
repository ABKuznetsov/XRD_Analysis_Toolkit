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
from xrd_finder.io.native_cif_session import read_native_cif, native_cif_session
from cristma.symmetry.orbit import expand_structure

from xrd_finder.core.reference_structures import corundum_reference_path
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
from xrd_finder.services.element_masses import species_atomic_weight
from xrd_finder.services.iic_thermal_model import iic_thermal_model, DEFAULT_UISO_ANGSTROM2


# Native defaults and bounded normalizations do not need additional checks.
_ACCEPTABLE_WARNINGS = frozenset({
    "cif.map.occupancy_defaulted",
    "crystallography.orbit.reported_wyckoff_mismatch",
    "cif.map.special_position_symmetrized",
    "cif.map.adp_symmetrized",
})

# Reference I/Ic is approximate. These annotations do not alter the native
# occupied model; reject duplicate full sites, not legitimate mixed sites.
_APPROXIMATE_WARNINGS = frozenset({
    "crystallography.orbit.reported_multiplicity_mismatch",
    "crystallography.orbit.wyckoff_multiplicity_mismatch",
    "cif.map.coincident_sites_unmerged",
    "cif.map.symmetry_equivalent_sites_unmerged",
    "cif.map.symmetry_expanded_sites_collapsed",
})
_POSITION_OCCUPANCY_TOLERANCE = .01


def _validate_occupied_positions(atoms) -> None:
    """Allow rounding, but not multiple full atoms at one periodic position.

    Inspect the exact expanded model used by diffraction and mass calculation.
    No sites, occupancies or source CIF bytes are changed.
    """
    import numpy as np
    from scipy.spatial import cKDTree
    from cristma.symmetry.orbit import DEFAULT_FRACTIONAL_TOLERANCE

    if not atoms:
        raise ValueError("No occupied structural model for calculated I/Ic")
    positions = np.asarray([atom.fractional for atom in atoms]) % 1.
    parent = list(range(len(atoms)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left, right in cKDTree(positions, boxsize=1.).query_pairs(
            DEFAULT_FRACTIONAL_TOLERANCE + 1e-12, p=np.inf):
        parent[find(left)] = find(right)
    occupied = {}
    for index, atom in enumerate(atoms):
        occupied.setdefault(find(index), []).extend(
            float(component.occupancy.value) for component in atom.components)
    if any(math.fsum(values) > 1. + _POSITION_OCCUPANCY_TOLERANCE + 1e-12
           for values in occupied.values()):
        raise ValueError("Overoccupied unit-cell position for calculated I/Ic")


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
            "structure_model": "mp-rest-v2-full-cell-v1",
            "reference": hashlib.sha256(corundum_reference_path().read_bytes()).hexdigest(),
            "radiation": asdict(self.instrument.radiation),
            "geometry": asdict(self.instrument.geometry),
            "range_deg": [5., 120.], "component": "primary", "scattering": "default-xray",
        }
        self.signature = hashlib.sha256(json.dumps(self.parameters, sort_keys=True).encode()).hexdigest()
        # Prepared reflection libraries remain compatible. Old I/Ic values need
        # one thermal-model refresh, separate from preparing search reflections.
        self._legacy_parameters = json.loads(json.dumps(self.parameters))
        self._legacy_signature = self.signature
        self.parameters.update(input_validation="non-destructive-warnings-v2", isotope_masses="nist-h-v1")
        self._v2_signature = hashlib.sha256(json.dumps(self.parameters, sort_keys=True).encode()).hexdigest()
        self.parameters.update(input_validation="bounded-source-normalization-v3",
                               missing_uiso_default_angstrom2=DEFAULT_UISO_ANGSTROM2,
                               noncatalog_symmetry="validated-full-cell-v1")
        self._v3_signature = hashlib.sha256(json.dumps(self.parameters, sort_keys=True).encode()).hexdigest()
        self.parameters.update(input_validation="occupied-site-warning-validation-v4",
                               position_occupancy_tolerance=_POSITION_OCCUPANCY_TOLERANCE)
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
        diagnostics = [item for item in result.diagnostics
                       if getattr(item.severity, "value", "") in ("warning", "error")]
        blocking = [item for item in diagnostics
                    if getattr(item.severity, "value", "") == "error"
                    or item.code not in _ACCEPTABLE_WARNINGS | _APPROXIMATE_WARNINGS]
        if blocking:
            codes = ", ".join(sorted({item.code for item in blocking}))
            raise ValueError(f"Calculated I/Ic blocked by CIF diagnostics: {codes}")
        calculation_result, assumptions, thermal_changed = iic_thermal_model(result)
        structure, setting = self.adapter._structure_and_setting(path, read_result=calculation_result)
        atoms = expand_structure(structure).atoms
        if any(item.code in _APPROXIMATE_WARNINGS for item in diagnostics):
            _validate_occupied_positions(atoms)
        mass = 0.
        for atom in atoms:
            for component in atom.components:
                occupancy = float(component.occupancy.value)
                if not math.isfinite(occupancy) or not 0. <= occupancy <= 1.:
                    raise ValueError("Invalid occupied unit-cell mass")
                if occupancy == 0.:
                    continue
                weight = species_atomic_weight(component.species)
                if not math.isfinite(weight) or weight <= 0.:
                    raise ValueError("Calculated I/Ic requires known atomic masses")
                mass += weight * occupancy
        volume = float(structure.cell.volume)
        if not (math.isfinite(mass) and mass > 0. and math.isfinite(volume) and volume > 0.):
            raise ValueError("Calculated I/Ic requires a positive unit-cell mass and volume")
        if peaks is None or thermal_changed:
            peaks = self.adapter.reference_sticks_from_structure(
                structure, setting, two_theta_min=5., two_theta_max=120.,
                instrument_profile=self.instrument, use_lp=True,
            )
        strongest = self.strongest_line(peaks)
        if strongest <= 0.:
            raise ValueError("No nonzero native diffraction lines for calculated I/Ic")
        return {"mass": mass, "volume": volume, "strongest": strongest,
                "power": strongest / (mass * volume), "peaks": [asdict(peak) for peak in peaks],
                "thermal_assumptions": assumptions,
                "structure_representation": structure.metadata.get('source_representation', 'catalog_setting'),
                "accepted_diagnostics": [dict(code=item.code, message=item.message, recovery=item.recovery)
                                         for item in diagnostics]}

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

    @native_cif_session
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
                                  "reference_power": reference["power"],
                                  "thermal_assumptions": phase["thermal_assumptions"],
                                  "structure_representation": phase["structure_representation"],
                                  "accepted_diagnostics": phase["accepted_diagnostics"]}, sort_keys=True)

    def current(self, metadata: str) -> bool:
        try:
            record = json.loads(metadata)
            if record.get("signature") == self.signature:
                return record.get("status") in {"calculated", "unavailable"}
            if record.get("signature") == self._v3_signature:
                # The scientific calculation is unchanged. Keep existing good
                # values; retry only old failures eligible for the new policy.
                if record.get("status") == "calculated":
                    return True
                if record.get("status") == "unavailable":
                    prefix = "Calculated I/Ic blocked by CIF diagnostics: "
                    reason = record.get("reason", "")
                    codes = set(reason[len(prefix):].split(", ")) if reason.startswith(prefix) else set()
                    retry = (bool(codes & _APPROXIMATE_WARNINGS)
                             and codes <= _ACCEPTABLE_WARNINGS | _APPROXIMATE_WARNINGS)
                    return not retry
            return False
        except (ValueError, TypeError, AttributeError):
            return False

    def compatible_library_signature(self, signature: str) -> bool:
        """The validation upgrade preserves the native reflection calculation.

        Old reflections can be imported without recomputing them. I/Ic receives
        a separate thermal-model update. Different native runtimes still fail.
        """
        return signature in (self.signature, self._legacy_signature, self._v2_signature, self._v3_signature)

    def value_current(self, value, metadata: str) -> bool:
        if not self.current(metadata):
            return False
        record = json.loads(metadata)
        if record["status"] == "unavailable":
            return value is None
        return (isinstance(value, (int, float)) and math.isfinite(value) and value > 0.
                and record.get("value") == value)
