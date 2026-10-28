from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math


def _float_value(record: Mapping[str, object], key: str, default: float = 0.0) -> float:
    try:
        return float(record.get(key, default) or default)
    except (TypeError, ValueError):
        return float(default)


def _int_value(record: Mapping[str, object], key: str, default: int = 0) -> int:
    try:
        return int(record.get(key, default) or default)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True, slots=True)
class ReferenceLine:
    d: float
    two_theta: float
    intensity: float
    normalized_intensity: float
    raw_intensity: float
    h: int = 0
    k: int = 0
    l: int = 0
    multiplicity: int = 1
    intrinsic_intensity: float | None = None
    intensity_origin: str = ""

    @property
    def hkl(self) -> tuple[int, int, int]:
        return (self.h, self.k, self.l)


@dataclass(frozen=True, slots=True)
class ReferenceLineSet:
    source: str
    entry_id: str
    derived_version: int
    provenance: str
    lines: tuple[ReferenceLine, ...]

    @classmethod
    def from_sql_rows(cls, *, source, entry_id, derived_version, provenance, records):
        """Decode the typed reflection projection without intermediate dicts.

        Hand-edited/legacy text values use the same tolerant mapping decoder.
        All reflections and metadata remain available; this is no shortlist.
        """
        lines = []
        columns = ('d','two_theta','intensity','norm_intensity','raw_intensity',
                   'h','k','l','multiplicity','intrinsic_intensity','intensity_origin')
        for record in records:
            try:
                d, angle, intensity, norm, raw, h, k, l, multiplicity, intrinsic, origin = record
                d, angle = d or 0., angle or 0.
                if not (math.isfinite(d) and d > 0. and math.isfinite(angle)):
                    continue
                line = ReferenceLine(d, angle, max(intensity or 0., 0.),
                    max(norm or 0., 0.), max(raw or 0., 0.), int(h or 0), int(k or 0), int(l or 0),
                    max(int(multiplicity or 1), 1), None if intrinsic is None else float(intrinsic),
                    str(origin or ''))
                lines.append(line)
            except (TypeError, ValueError, OverflowError):
                decoded = cls.from_records(source=source, entry_id=entry_id,
                    derived_version=derived_version, provenance=provenance,
                    records=[dict(zip(columns, record))])
                lines.extend(decoded.lines)
        lines.sort(key=lambda line: (line.two_theta, line.h, line.k, line.l))
        return cls(str(source or '').upper(), str(entry_id or ''), int(derived_version),
                   str(provenance or ''), tuple(lines))

    @classmethod
    def from_records(
        cls,
        *,
        source: str,
        entry_id: str,
        derived_version: int,
        provenance: str,
        records: Iterable[Mapping[str, object]],
    ) -> ReferenceLineSet:
        lines = []
        for record in records:
            d = _float_value(record, "d")
            two_theta = _float_value(record, "two_theta")
            intensity = max(_float_value(record, "intensity"), 0.0)
            if not (math.isfinite(d) and d > 0.0 and math.isfinite(two_theta)):
                continue
            lines.append(
                ReferenceLine(
                    d=d,
                    two_theta=two_theta,
                    intensity=intensity,
                    normalized_intensity=max(_float_value(record, "norm_intensity"), 0.0),
                    raw_intensity=max(_float_value(record, "raw_intensity"), 0.0),
                    h=_int_value(record, "h"),
                    k=_int_value(record, "k"),
                    l=_int_value(record, "l"),
                    multiplicity=max(_int_value(record, "multiplicity", 1), 1),
                    intrinsic_intensity=(_float_value(record, "intrinsic_intensity")
                                         if record.get("intrinsic_intensity") is not None else None),
                    intensity_origin=str(record.get("intensity_origin") or ""),
                )
            )
        lines.sort(key=lambda line: (line.two_theta, line.h, line.k, line.l))
        return cls(
            source=str(source or "").upper(),
            entry_id=str(entry_id or ""),
            derived_version=int(derived_version),
            provenance=str(provenance or ""),
            lines=tuple(lines),
        )

    @property
    def fingerprint(self) -> tuple[object, ...]:
        return (
            self.source,
            self.entry_id,
            self.derived_version,
            self.provenance,
            tuple(
                (
                    round(line.d, 7),
                    round(line.two_theta, 5),
                    round(line.intensity, 4),
                    round(line.normalized_intensity, 6),
                    round(line.raw_intensity, 4),
                    line.h,
                    line.k,
                    line.l,
                    line.multiplicity,
                    line.intrinsic_intensity,
                    line.intensity_origin,
                )
                for line in self.lines
            ),
        )


def reference_peaks_for_context(lines, context, instrument_profile=None):
    """Transform known structural strengths; preserve empirical relative data.

    d-dependent scattering strengths use the same default non-anomalous X-ray
    context as the CrIStMa cache. Geometry and spectrum are applied at read time.
    No guessed LP correction is made for measured/unknown reference patterns.
    """
    from xrd_finder.services.calculated_pattern_service import CU_KA1_WAVELENGTH, HKLPeak
    from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
    from xrd_finder.instrument.models import InstrumentProfile, RadiationProfile

    instrument = instrument_profile or InstrumentProfile(
        radiation=RadiationProfile.custom_monochromatic(context.primary_wavelength))
    has_structural_lines = any(line.intensity_origin=="cristma-structure" and
                               line.intrinsic_intensity is not None for line in lines.lines)
    geometry = CristmaPowderAdapter._geometry_from_profile(instrument, use_lp=True) if has_structural_lines else None
    radiation = CristmaPowderAdapter.radiation_from_profile(instrument)
    primary_weight = radiation.components[0].relative_weight / sum(c.relative_weight for c in radiation.components)
    wavelength = float(instrument.radiation.components[0].wavelength_angstrom)
    peaks = []
    cached_angles = math.isclose(context.primary_wavelength, CU_KA1_WAVELENGTH, abs_tol=1.e-4, rel_tol=0.)
    for line in lines.lines:
        structural = line.intensity_origin == "cristma-structure" and line.intrinsic_intensity is not None
        center = line.two_theta
        if structural or line.intensity_origin or not cached_angles:
            argument = wavelength / (2.*line.d)
            if not 0. < argument <= 1.:
                continue
            center = math.degrees(2.*math.asin(argument))
        if not context.two_theta_min <= center <= context.two_theta_max:
            continue
        if structural:
            lp = CristmaPowderAdapter._lorentz_polarization_factor(center, geometry)
            raw = float(line.intrinsic_intensity) * lp * primary_weight
            intensity = raw
        else:
            lp = 1.
            intensity = float(line.normalized_intensity or line.intensity)
            raw = float(line.raw_intensity or line.intensity)
        if not math.isfinite(intensity) or intensity <= 0. or not math.isfinite(raw):
            continue
        peaks.append(HKLPeak(line.h,line.k,line.l,line.d,center,intensity,line.multiplicity,
            lp=lp,raw_intensity=raw,intrinsic_intensity=line.intrinsic_intensity,intensity_origin=line.intensity_origin))
    maximum = max((p.intensity for p in peaks),default=0.)
    if maximum > 0.:
        for peak in peaks:
            peak.intensity *= 100./maximum
    return peaks
