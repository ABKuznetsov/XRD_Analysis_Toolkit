from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import tomllib
from typing import Iterable

import numpy as np
from scipy.signal import find_peaks


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from xrd_finder.finder.fingerprint_matching import fingerprint_match_score
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    HKLPeak,
    calculated_profile_from_peaks,
)
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.gain_scoring import DEFAULT_GAIN_POLICY, GainStage


PORTABLE_FIXTURE_CACHE = APP_ROOT / "tests" / "fixtures" / "cod_benchmark.sqlite"
RUNTIME_CACHE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Sci"
    / "apps"
    / "xrd_phase_finder"
    / "data"
    / "cod_cache"
    / "index.sqlite"
)
DEFAULT_CACHE = PORTABLE_FIXTURE_CACHE if PORTABLE_FIXTURE_CACHE.is_file() else RUNTIME_CACHE
with (APP_ROOT.parent / "pyproject.toml").open("rb") as _project_stream:
    SOFTWARE_VERSION = str(tomllib.load(_project_stream)["project"]["version"])


def _trapezoid(values: np.ndarray, x: np.ndarray) -> float:
    integrator = getattr(np, "trapezoid", None)
    if integrator is None:
        integrator = np.trapz
    return float(integrator(values, x))


@dataclass(frozen=True, slots=True)
class Candidate:
    source: str
    entry_id: str
    formula: str
    name: str
    spacegroup: str
    family: str
    peaks: tuple[HKLPeak, ...]

    @property
    def key(self) -> str:
        return f"{self.source}:{self.entry_id}"

    def row(self) -> list[str]:
        return [
            self.source,
            self.entry_id,
            self.formula,
            self.name or self.formula,
            self.spacegroup,
            "",
            "",
            "",
        ]

    def mapping(self) -> dict[str, str]:
        return {
            "Source": self.source,
            "Entry": self.entry_id,
            "Formula": self.formula,
            "Phase": self.name or self.formula,
        }


@dataclass(frozen=True, slots=True)
class CaseDefinition:
    case_id: str
    kind: str
    components: tuple[str, ...]
    weights: tuple[float, ...]
    zero_shift: float
    fwhm: float
    eta: float
    noise_fraction: float
    texture_sigma: float
    halo_fraction: float
    overlap_class: str


@dataclass(slots=True)
class CaseResult:
    case_id: str
    kind: str
    component_keys: str
    component_families: str
    weights: str
    overlap_class: str
    zero_shift: float
    fwhm: float
    eta: float
    noise_fraction: float
    texture_sigma: float
    halo_fraction: float
    observed_lines: int
    dominant_exact_rank: int
    dominant_family_rank: int
    dominant_match: float
    all_true_families_match_top5: bool
    all_true_families_match_top10: bool
    gain_steps: int
    gain_family_top1_hits: int
    gain_family_top5_hits: int
    gain_family_detected_hits: int
    max_false_gain: float
    false_gain_ge_5: bool


def _formula_family(formula: str) -> str:
    tokens = re.findall(r"([A-Z][a-z]?)([0-9.]+)?", formula or "")
    if not tokens:
        return re.sub(r"[^a-z0-9]+", "", (formula or "").lower())
    normalized = []
    for element, amount in sorted(tokens):
        amount_text = amount.rstrip("0").rstrip(".") if amount else "1"
        normalized.append(f"{element.lower()}{amount_text or '1'}")
    return "".join(normalized)


def _load_candidates(index_path: Path) -> list[Candidate]:
    if not index_path.exists():
        raise FileNotFoundError(f"COD cache not found: {index_path}")
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            select source, entry_id, formula, name, spacegroup, peaks_json
            from phases
            where peaks_json != ''
            order by source, entry_id
            """
        ).fetchall()
    finally:
        connection.close()
    candidates = []
    for row in rows:
        peaks = _decode_peaks(row["peaks_json"])
        if len(peaks) < 4:
            continue
        candidates.append(
            Candidate(
                source=str(row["source"]),
                entry_id=str(row["entry_id"]),
                formula=str(row["formula"] or ""),
                name=str(row["name"] or ""),
                spacegroup=str(row["spacegroup"] or ""),
                family=_formula_family(str(row["formula"] or "")),
                peaks=tuple(peaks),
            )
        )
    if len(candidates) < 20:
        raise RuntimeError(f"At least 20 peak-indexed candidates are required; found {len(candidates)}")
    return candidates


def _decode_peaks(payload: str) -> list[HKLPeak]:
    try:
        rows = json.loads(payload)
    except Exception:
        return []
    peaks = []
    for item in rows:
        try:
            two_theta = float(item.get("two_theta", 0.0))
            intensity = float(item.get("intensity", 0.0))
            if not 5.0 <= two_theta <= 120.0 or intensity < 0.5:
                continue
            peaks.append(
                HKLPeak(
                    h=int(item.get("h", 0)),
                    k=int(item.get("k", 0)),
                    l=int(item.get("l", 0)),
                    d=float(item.get("d", 0.0)),
                    two_theta=two_theta,
                    intensity=intensity,
                    multiplicity=int(item.get("multiplicity", 1) or 1),
                    raw_intensity=float(item.get("raw_intensity", 0.0) or 0.0),
                )
            )
        except Exception:
            continue
    return peaks


def _representatives(candidates: list[Candidate]) -> list[Candidate]:
    groups: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.family, []).append(candidate)
    representatives = []
    for family, entries in sorted(groups.items()):
        representatives.append(
            max(
                entries,
                key=lambda item: (
                    len(item.peaks),
                    sum(peak.intensity >= 5.0 for peak in item.peaks),
                    item.entry_id,
                ),
            )
        )
    return representatives


def _peak_records(candidate: Candidate) -> list[tuple[float, float]]:
    peaks = sorted(candidate.peaks, key=lambda item: item.intensity, reverse=True)[:80]
    return [(float(peak.two_theta), float(peak.intensity)) for peak in peaks]


def _family_overlap(left: Candidate, right: Candidate) -> float:
    left_to_right = fingerprint_match_score(
        left.peaks,
        _peak_records(right),
        wavelength=CU_KA1_WAVELENGTH,
    ).score
    right_to_left = fingerprint_match_score(
        right.peaks,
        _peak_records(left),
        wavelength=CU_KA1_WAVELENGTH,
    ).score
    return 0.5 * (left_to_right + right_to_left)


def _build_cases(representatives: list[Candidate], seed: int) -> list[CaseDefinition]:
    rng = np.random.default_rng(seed)
    ordered = list(representatives)
    rng.shuffle(ordered)
    by_key = {candidate.key: candidate for candidate in ordered}

    overlap_pairs = []
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            overlap_pairs.append((_family_overlap(left, right), left.key, right.key))
    overlap_pairs.sort(reverse=True)
    high_overlap_pairs = [(left, right) for _score, left, right in overlap_pairs[:12]]

    cases: list[CaseDefinition] = []
    for index in range(20):
        candidate = ordered[index % len(ordered)]
        cases.append(
            _case(
                rng,
                case_id=f"S{index + 1:02d}",
                kind="single",
                components=(candidate.key,),
                weights=(1.0,),
                overlap_class="single",
            )
        )

    used_pairs: set[tuple[str, str]] = set()
    for index in range(20):
        if index < 8:
            left, right = high_overlap_pairs[index]
            overlap_class = "high"
        else:
            left = ordered[(index * 3 + 2) % len(ordered)].key
            right = ordered[(index * 7 + 9) % len(ordered)].key
            if left == right:
                right = ordered[(index * 7 + 10) % len(ordered)].key
            overlap_class = "mixed"
        pair = tuple(sorted((left, right)))
        if pair in used_pairs:
            alternatives = [candidate.key for candidate in ordered if candidate.key not in pair]
            right = alternatives[index % len(alternatives)]
            pair = tuple(sorted((left, right)))
        used_pairs.add(pair)
        major = float(rng.uniform(0.62, 0.84))
        cases.append(
            _case(
                rng,
                case_id=f"B{index + 1:02d}",
                kind="binary",
                components=(left, right),
                weights=(major, 1.0 - major),
                overlap_class=overlap_class,
            )
        )

    for index in range(10):
        left, right = high_overlap_pairs[(index + 2) % len(high_overlap_pairs)]
        third = ordered[(index * 5 + 4) % len(ordered)].key
        if third in {left, right}:
            third = next(key for key in by_key if key not in {left, right})
        major = float(rng.uniform(0.52, 0.68))
        minor = float(rng.uniform(0.18, min(0.30, 0.92 - major)))
        trace = 1.0 - major - minor
        cases.append(
            _case(
                rng,
                case_id=f"T{index + 1:02d}",
                kind="ternary",
                components=(left, right, third),
                weights=(major, minor, trace),
                overlap_class="high+mixed",
            )
        )
    return cases


def _case(
    rng: np.random.Generator,
    *,
    case_id: str,
    kind: str,
    components: tuple[str, ...],
    weights: tuple[float, ...],
    overlap_class: str,
) -> CaseDefinition:
    return CaseDefinition(
        case_id=case_id,
        kind=kind,
        components=components,
        weights=weights,
        zero_shift=float(rng.uniform(-0.16, 0.16)),
        fwhm=float(rng.uniform(0.12, 0.34)),
        eta=float(rng.uniform(0.0, 0.45)),
        noise_fraction=float(rng.uniform(0.004, 0.018)),
        texture_sigma=float(rng.uniform(0.10, 0.48)),
        halo_fraction=float(rng.uniform(0.0, 0.10)),
        overlap_class=overlap_class,
    )


def _distorted_peaks(
    peaks: Iterable[HKLPeak],
    *,
    zero_shift: float,
    texture_sigma: float,
    rng: np.random.Generator,
) -> list[HKLPeak]:
    distorted = []
    for peak in peaks:
        texture = float(np.exp(rng.normal(0.0, texture_sigma)))
        distorted.append(
            HKLPeak(
                h=int(peak.h),
                k=int(peak.k),
                l=int(peak.l),
                d=float(peak.d),
                two_theta=float(peak.two_theta) + zero_shift,
                intensity=max(float(peak.intensity) * texture, 0.0),
                multiplicity=int(peak.multiplicity),
                f2=float(getattr(peak, "f2", 0.0) or 0.0),
                lp=float(getattr(peak, "lp", 1.0) or 1.0),
                raw_intensity=float(getattr(peak, "raw_intensity", 0.0) or 0.0),
            )
        )
    maximum = max((peak.intensity for peak in distorted), default=1.0)
    if maximum <= 0.0:
        return distorted
    return [
        HKLPeak(
            h=peak.h,
            k=peak.k,
            l=peak.l,
            d=peak.d,
            two_theta=peak.two_theta,
            intensity=100.0 * peak.intensity / maximum,
            multiplicity=peak.multiplicity,
            f2=peak.f2,
            lp=peak.lp,
            raw_intensity=peak.raw_intensity,
        )
        for peak in distorted
    ]


def _synthetic_profile(
    definition: CaseDefinition,
    candidates: dict[str, Candidate],
    x: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray], np.ndarray]:
    mixture = np.zeros_like(x)
    component_profiles: list[np.ndarray] = []
    for component_key, fraction in zip(definition.components, definition.weights, strict=True):
        candidate = candidates[component_key]
        peaks = _distorted_peaks(
            candidate.peaks,
            zero_shift=definition.zero_shift,
            texture_sigma=definition.texture_sigma,
            rng=rng,
        )
        _grid, profile = calculated_profile_from_peaks(
            peaks,
            x,
            fwhm=definition.fwhm,
            eta=definition.eta,
            wavelength=CU_KA1_WAVELENGTH,
            include_kalpha2=True,
        )
        profile = np.clip(np.asarray(profile, dtype=float), 0.0, None)
        area = _trapezoid(profile, x)
        if area > 0.0:
            component_profile = float(fraction) * profile / area
            mixture += component_profile
            component_profiles.append(component_profile)
        else:
            component_profiles.append(np.zeros_like(x))

    maximum = max(float(np.nanmax(mixture)), 1.0e-12)
    intensity_scale = 2400.0 / maximum
    component_profiles = [profile * intensity_scale for profile in component_profiles]
    crystalline = mixture * intensity_scale
    halo = np.zeros_like(x)
    if definition.halo_fraction > 0.0:
        center = float(rng.uniform(20.0, 34.0))
        width = float(rng.uniform(3.5, 8.0))
        halo = (
            definition.halo_fraction
            * float(np.nanmax(crystalline))
            * np.exp(-0.5 * ((x - center) / width) ** 2)
        )
    clean = crystalline + halo
    sigma = definition.noise_fraction * max(float(np.nanmax(clean)), 1.0)
    gaussian_noise = rng.normal(0.0, sigma, len(x))
    counting_sigma = np.sqrt(np.clip(clean, 0.0, None)) * 0.35
    counting_noise = rng.normal(0.0, counting_sigma)
    observed = np.clip(clean + gaussian_noise + counting_noise, 0.0, None)
    effective_sigma = np.sqrt(sigma * sigma + counting_sigma * counting_sigma)
    return observed, clean, component_profiles, effective_sigma


def _component_line_significance(
    x: np.ndarray,
    component_profile: np.ndarray,
    selected_profile: np.ndarray,
    effective_sigma: np.ndarray,
    fwhm: float,
) -> dict[str, float | int]:
    component = np.clip(np.asarray(component_profile, dtype=float), 0.0, None)
    selected = np.clip(np.asarray(selected_profile, dtype=float), 0.0, None)
    sigma = np.maximum(np.asarray(effective_sigma, dtype=float), 1.0e-9)
    if len(component) != len(x) or float(np.nanmax(component)) <= 0.0:
        return {
            "max_line_snr": 0.0,
            "second_line_snr": 0.0,
            "max_independent_line_snr": 0.0,
            "second_independent_line_snr": 0.0,
            "independent_lines_snr_ge_3": 0,
        }
    step = max(float(np.nanmedian(np.diff(x))), 1.0e-6)
    peak_indices, _properties = find_peaks(
        component,
        prominence=max(float(np.nanmax(component)) * 0.003, 1.0e-9),
        distance=max(2, int(round(max(float(fwhm), 0.08) / step * 0.45))),
    )
    if not len(peak_indices):
        peak_indices = np.asarray([int(np.nanargmax(component))], dtype=int)
    line_snr = component[peak_indices] / sigma[peak_indices]
    order = np.argsort(line_snr)[::-1]
    sorted_snr = line_snr[order]
    independent_mask = selected[peak_indices] <= np.maximum(component[peak_indices] * 0.50, sigma[peak_indices] * 0.50)
    independent_snr = np.sort(line_snr[independent_mask])[::-1]
    return {
        "max_line_snr": float(sorted_snr[0]) if len(sorted_snr) else 0.0,
        "second_line_snr": float(sorted_snr[1]) if len(sorted_snr) > 1 else 0.0,
        "max_independent_line_snr": float(independent_snr[0]) if len(independent_snr) else 0.0,
        "second_independent_line_snr": float(independent_snr[1]) if len(independent_snr) > 1 else 0.0,
        "independent_lines_snr_ge_3": int(np.count_nonzero(independent_snr >= 3.0)),
    }


def _make_harness(
    peak_map: dict[str, tuple[HKLPeak, ...]],
    x: np.ndarray,
    observed: np.ndarray,
    case_id: str,
    fwhm: float,
    gain_baseline_mode: str,
) -> PhaseFinderWindow:
    harness = PhaseFinderWindow.__new__(PhaseFinderWindow)
    harness._candidate_json_peak_cache = {}
    harness._candidate_probability_cache = {}
    harness._candidate_gain_profile_cache = {}
    harness._candidate_hidden_match_by_key = {}
    harness._gain_overlap_locked = False
    harness.match_zero_shifts = {}
    harness.match_cell_scales = {}
    harness.match_candidates = []
    harness._scoring_source = "Auto"
    harness._last_match_profile_fwhm = float(fwhm)
    harness._last_match_profile_eta = 0.0
    harness._active_wavelength = lambda: CU_KA1_WAVELENGTH
    harness._active_pattern = lambda: None
    harness._active_scoring_observed_data = lambda: np.column_stack((x, observed))
    harness._pattern_finder_background_data = lambda _pattern: None
    harness._pattern_scoring_background_removed = lambda _pattern: True
    harness._active_probability_context_key = lambda: ("benchmark", case_id)
    harness._candidate_cached_json_peaks = lambda candidate: list(
        peak_map.get(f"{candidate.get('Source', '')}:{candidate.get('Entry', '')}", ())
    )
    harness._candidate_cif_peaks_for_gain = lambda _candidate: []
    if gain_baseline_mode != "current":
        harness._gain_target_baseline = lambda values: _gain_target_baseline(
            values,
            mode=gain_baseline_mode,
        )
    return harness


def _gain_target_baseline(values: np.ndarray, *, mode: str) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return 0.0
    median = float(np.nanmedian(finite))
    mad = float(np.nanmedian(np.abs(finite - median)))
    robust_sigma = 1.4826 * mad
    if mode.startswith("sigma-"):
        multiplier = float(mode.removeprefix("sigma-"))
        return max(
            median + multiplier * robust_sigma,
            float(np.nanpercentile(finite, 20)),
        )
    if mode == "low-baseline":
        return max(
            float(np.nanpercentile(finite, 12)),
            median - 1.5 * robust_sigma,
            0.0,
        )
    raise ValueError(f"Unknown Gain baseline mode: {mode}")


def _rank_match(
    candidates: list[Candidate],
    records,
) -> list[tuple[float, Candidate]]:
    ranking = [
        (
            fingerprint_match_score(
                candidate.peaks,
                records,
                wavelength=CU_KA1_WAVELENGTH,
            ).score,
            candidate,
        )
        for candidate in candidates
    ]
    ranking.sort(key=lambda item: (-item[0], item[1].key))
    return ranking


def _rank_gain(
    harness: PhaseFinderWindow,
    candidates: list[Candidate],
    selected: list[Candidate],
    zero_shift: float,
):
    harness.match_candidates = [candidate.mapping() for candidate in selected]
    harness.match_zero_shifts = {candidate.key: float(zero_shift) for candidate in selected}
    context = harness._candidate_gain_context()
    if context is None:
        return [], "", {}
    stage = harness._gain_stage_for_context(context)
    selected_keys = {candidate.key for candidate in selected}
    selected_families = {candidate.family for candidate in selected}

    def rank_for_stage(active_stage: str) -> list[tuple[float, Candidate]]:
        context["gain_stage"] = active_stage
        context["gain_evidence_by_key"] = {}
        stage_ranking = []
        for candidate in candidates:
            if candidate.key in selected_keys or candidate.family in selected_families:
                continue
            score = float(harness._candidate_row_integral_gain(candidate.row(), context))
            stage_ranking.append((score, candidate))
        stage_ranking.sort(key=lambda item: (-item[0], item[1].key))
        return stage_ranking

    ranking = rank_for_stage(stage)
    if (
        stage == str(GainStage.DIRECT)
        and not any(score > 0.0 for score, _candidate in ranking)
        and len(harness._gain_stage_records(context, GainStage.OVERLAP, limit=24))
        >= DEFAULT_GAIN_POLICY.minimum_stage_records
    ):
        stage = str(GainStage.OVERLAP)
        harness._gain_overlap_locked = True
        ranking = rank_for_stage(stage)
    return ranking, stage, dict(context.get("gain_evidence_by_key", {}))


def _rank_of_key(
    ranking: list[tuple[float, Candidate]],
    key: str,
    *,
    positive_only: bool = False,
) -> int:
    for index, (_score, candidate) in enumerate(ranking, start=1):
        if positive_only and _score <= 0.0:
            return 0
        if candidate.key == key:
            return index
    return 0


def _rank_of_family(
    ranking: list[tuple[float, Candidate]],
    family: str,
    *,
    positive_only: bool = False,
) -> int:
    for index, (_score, candidate) in enumerate(ranking, start=1):
        if positive_only and _score <= 0.0:
            return 0
        if candidate.family == family:
            return index
    return 0


def _score_for_key(ranking: list[tuple[float, Candidate]], key: str) -> float:
    for score, candidate in ranking:
        if candidate.key == key:
            return float(score)
    return 0.0


def _score_for_family(ranking: list[tuple[float, Candidate]], family: str) -> float:
    return max(
        (float(score) for score, candidate in ranking if candidate.family == family),
        default=0.0,
    )


def _write_pattern(
    path: Path,
    x: np.ndarray,
    observed: np.ndarray,
    clean: np.ndarray,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["2theta_deg", "observed_corrected", "clean_corrected"])
        writer.writerows(zip(x, observed, clean, strict=True))


def _run_case(
    definition: CaseDefinition,
    candidates: list[Candidate],
    by_key: dict[str, Candidate],
    output_dir: Path,
    seed: int,
    gain_baseline_mode: str,
) -> tuple[CaseResult, list[dict[str, object]]]:
    rng = np.random.default_rng(seed)
    x = np.arange(10.0, 80.0001, 0.025)
    observed, clean, component_profiles, effective_sigma = _synthetic_profile(
        definition,
        by_key,
        x,
        rng,
    )
    _write_pattern(output_dir / "patterns" / f"{definition.case_id}.csv", x, observed, clean)

    peak_map = {candidate.key: candidate.peaks for candidate in candidates}
    harness = _make_harness(
        peak_map,
        x,
        observed,
        definition.case_id,
        definition.fwhm,
        gain_baseline_mode,
    )
    observed_records = harness._observed_peak_records(x, observed, limit=80)
    match_ranking = _rank_match(candidates, observed_records)

    true_candidates = [by_key[key] for key in definition.components]
    dominant = true_candidates[0]
    true_families = {candidate.family for candidate in true_candidates}
    family_match_ranks = {
        family: _rank_of_family(match_ranking, family)
        for family in true_families
    }

    gain_details: list[dict[str, object]] = []
    selected = [dominant]
    top1_hits = 0
    top5_hits = 0
    detected_hits = 0
    max_false_gain = 0.0
    for expected_index, expected in enumerate(true_candidates[1:], start=1):
        selected_true_profile = np.sum(component_profiles[:expected_index], axis=0)
        significance = _component_line_significance(
            x,
            component_profiles[expected_index],
            selected_true_profile,
            effective_sigma,
            definition.fwhm,
        )
        gain_ranking, stage, evidence_by_key = _rank_gain(
            harness,
            candidates,
            selected,
            definition.zero_shift,
        )
        evidence = evidence_by_key.get(expected.key)
        family_rank = _rank_of_family(
            gain_ranking,
            expected.family,
            positive_only=True,
        )
        exact_rank = _rank_of_key(
            gain_ranking,
            expected.key,
            positive_only=True,
        )
        exact_score = _score_for_key(gain_ranking, expected.key)
        expected_score = _score_for_family(gain_ranking, expected.family)
        positive_ranking = [item for item in gain_ranking if item[0] > 0.0]
        top1_hits += int(family_rank == 1)
        top5_hits += int(0 < family_rank <= 5)
        detected_hits += int(expected_score > 0.0)
        gain_details.append(
            {
                "case_id": definition.case_id,
                "step": len(selected),
                "stage": stage,
                "selected_keys": ";".join(candidate.key for candidate in selected),
                "expected_key": expected.key,
                "expected_family": expected.family,
                "expected_gain": round(expected_score, 6),
                "exact_entry_gain": round(exact_score, 6),
                "exact_rank": exact_rank,
                "family_rank": family_rank,
                "positive_candidates": len(positive_ranking),
                "evidence_accepted": bool(getattr(evidence, "accepted", False)),
                "evidence_factor": round(float(getattr(evidence, "factor", 0.0)), 6),
                "evidence_delta_bic": round(float(getattr(evidence, "delta_bic", 0.0)), 6),
                "evidence_testable_lines": int(getattr(evidence, "testable_lines", 0)),
                "evidence_supported_lines": int(getattr(evidence, "supported_lines", 0)),
                "evidence_independent_lines": int(getattr(evidence, "independent_lines", 0)),
                "evidence_missing_lines": int(getattr(evidence, "missing_lines", 0)),
                "evidence_strongest_independent_snr": round(
                    float(getattr(evidence, "strongest_independent_snr", 0.0)),
                    6,
                ),
                **{key: round(value, 6) if isinstance(value, float) else value for key, value in significance.items()},
                "top5": ";".join(
                    f"{candidate.key}:{score:.3f}"
                    for score, candidate in positive_ranking[:5]
                ),
            }
        )
        selected.append(expected)

    final_gain_ranking, final_stage, final_evidence = _rank_gain(
        harness,
        candidates,
        selected,
        definition.zero_shift,
    )
    strongest_false = final_gain_ranking[0][1] if final_gain_ranking else None
    strongest_false_evidence = (
        final_evidence.get(strongest_false.key)
        if strongest_false is not None
        else None
    )
    if final_gain_ranking:
        max_false_gain = max(score for score, _candidate in final_gain_ranking)
    gain_details.append(
        {
            "case_id": definition.case_id,
            "step": len(selected),
            "stage": final_stage,
            "selected_keys": ";".join(candidate.key for candidate in selected),
            "expected_key": "",
            "expected_family": "",
            "expected_gain": 0.0,
            "exact_entry_gain": 0.0,
            "exact_rank": 0,
            "family_rank": 0,
            "positive_candidates": sum(score > 0.0 for score, _candidate in final_gain_ranking),
            "evidence_accepted": bool(getattr(strongest_false_evidence, "accepted", False)),
            "evidence_factor": round(float(getattr(strongest_false_evidence, "factor", 0.0)), 6),
            "evidence_delta_bic": round(float(getattr(strongest_false_evidence, "delta_bic", 0.0)), 6),
            "evidence_testable_lines": int(getattr(strongest_false_evidence, "testable_lines", 0)),
            "evidence_supported_lines": int(getattr(strongest_false_evidence, "supported_lines", 0)),
            "evidence_independent_lines": int(getattr(strongest_false_evidence, "independent_lines", 0)),
            "evidence_missing_lines": int(getattr(strongest_false_evidence, "missing_lines", 0)),
            "evidence_strongest_independent_snr": round(
                float(getattr(strongest_false_evidence, "strongest_independent_snr", 0.0)),
                6,
            ),
            "max_line_snr": "",
            "second_line_snr": "",
            "max_independent_line_snr": "",
            "second_independent_line_snr": "",
            "independent_lines_snr_ge_3": "",
            "top5": ";".join(
                f"{candidate.key}:{score:.3f}"
                for score, candidate in [
                    item for item in final_gain_ranking if item[0] > 0.0
                ][:5]
            ),
        }
    )

    result = CaseResult(
        case_id=definition.case_id,
        kind=definition.kind,
        component_keys=";".join(definition.components),
        component_families=";".join(candidate.family for candidate in true_candidates),
        weights=";".join(f"{weight:.6f}" for weight in definition.weights),
        overlap_class=definition.overlap_class,
        zero_shift=definition.zero_shift,
        fwhm=definition.fwhm,
        eta=definition.eta,
        noise_fraction=definition.noise_fraction,
        texture_sigma=definition.texture_sigma,
        halo_fraction=definition.halo_fraction,
        observed_lines=len(observed_records),
        dominant_exact_rank=_rank_of_key(match_ranking, dominant.key),
        dominant_family_rank=_rank_of_family(match_ranking, dominant.family),
        dominant_match=_score_for_key(match_ranking, dominant.key),
        all_true_families_match_top5=all(
            0 < rank <= 5 for rank in family_match_ranks.values()
        ),
        all_true_families_match_top10=all(
            0 < rank <= 10 for rank in family_match_ranks.values()
        ),
        gain_steps=max(0, len(true_candidates) - 1),
        gain_family_top1_hits=top1_hits,
        gain_family_top5_hits=top5_hits,
        gain_family_detected_hits=detected_hits,
        max_false_gain=max_false_gain,
        false_gain_ge_5=max_false_gain >= 5.0,
    )
    return result, gain_details


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _summarize(
    candidates: list[Candidate],
    representatives: list[Candidate],
    cases: list[CaseDefinition],
    results: list[CaseResult],
) -> dict[str, object]:
    multi = [result for result in results if result.gain_steps > 0]
    gain_steps = sum(result.gain_steps for result in results)
    singles = [result for result in results if result.kind == "single"]
    return {
        "benchmark": "XRD Phase Finder Match/Gain synthetic closed-world benchmark",
        "software_version": SOFTWARE_VERSION,
        "cases": len(cases),
        "candidate_entries": len(candidates),
        "candidate_families": len({candidate.family for candidate in candidates}),
        "generator_representatives": len(representatives),
        "case_distribution": {
            kind: sum(case.kind == kind for case in cases)
            for kind in ("single", "binary", "ternary")
        },
        "match": {
            "dominant_exact_top1": sum(result.dominant_exact_rank == 1 for result in results),
            "dominant_exact_top5": sum(0 < result.dominant_exact_rank <= 5 for result in results),
            "dominant_family_top1": sum(result.dominant_family_rank == 1 for result in results),
            "dominant_family_top5": sum(0 < result.dominant_family_rank <= 5 for result in results),
            "all_true_families_top5": sum(result.all_true_families_match_top5 for result in results),
            "all_true_families_top10": sum(result.all_true_families_match_top10 for result in results),
            "median_dominant_score": float(np.median([result.dominant_match for result in results])),
        },
        "gain": {
            "multi_phase_cases": len(multi),
            "expected_steps": gain_steps,
            "family_top1": sum(result.gain_family_top1_hits for result in results),
            "family_top5": sum(result.gain_family_top5_hits for result in results),
            "positive_expected_gain": sum(result.gain_family_detected_hits for result in results),
            "single_phase_false_gain_ge_5": sum(result.false_gain_ge_5 for result in singles),
            "single_phase_cases": len(singles),
            "all_true_selected_false_gain_ge_5": sum(result.false_gain_ge_5 for result in results),
            "median_max_false_gain": float(np.median([result.max_false_gain for result in results])),
        },
        "scope": (
            "Closed-world synthetic benchmark. Source profiles and candidate pool use the same "
            "local peak-indexed COD entries. Results test ranking under controlled distortions, "
            "not real-sample detection limits or quantitative phase accuracy."
        ),
    }


def _summary_markdown(summary: dict[str, object]) -> str:
    match = summary["match"]
    gain = summary["gain"]
    distribution = summary["case_distribution"]
    return "\n".join(
        [
            f"# Match/Gain v{summary['software_version']} synthetic benchmark",
            "",
            f"- Cases: {summary['cases']} "
            f"({distribution['single']} single, {distribution['binary']} binary, "
            f"{distribution['ternary']} ternary)",
            f"- Candidate pool: {summary['candidate_entries']} COD entries, "
            f"{summary['candidate_families']} formula families",
            f"- Dominant exact entry: top-1 {match['dominant_exact_top1']}/{summary['cases']}, "
            f"top-5 {match['dominant_exact_top5']}/{summary['cases']}",
            f"- Dominant formula family: top-1 {match['dominant_family_top1']}/{summary['cases']}, "
            f"top-5 {match['dominant_family_top5']}/{summary['cases']}",
            f"- All true families present in Match: top-5 "
            f"{match['all_true_families_top5']}/{summary['cases']}, "
            f"top-10 {match['all_true_families_top10']}/{summary['cases']}",
            f"- Conditional Gain steps: family top-1 {gain['family_top1']}/{gain['expected_steps']}, "
            f"top-5 {gain['family_top5']}/{gain['expected_steps']}, "
            f"positive score {gain['positive_expected_gain']}/{gain['expected_steps']}",
            f"- Closed single-phase false Gain >= 5%: "
            f"{gain['single_phase_false_gain_ge_5']}/{gain['single_phase_cases']}",
            f"- Median maximum false Gain after all true phases: "
            f"{gain['median_max_false_gain']:.2f}%",
            "",
            str(summary["scope"]),
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and evaluate 50 synthetic XRD Match/Gain cases."
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--output",
        type=Path,
        default=APP_ROOT / "benchmark_results" / "match_gain_v1_2_0",
    )
    parser.add_argument("--seed", type=int, default=1200)
    parser.add_argument(
        "--gain-baseline-mode",
        choices=("current", "sigma-2.5", "sigma-2.0", "sigma-1.5", "low-baseline"),
        default="current",
        help="Ablation mode for the baseline removed before residual Gain scoring.",
    )
    args = parser.parse_args()

    output_dir = args.output.resolve()
    (output_dir / "patterns").mkdir(parents=True, exist_ok=True)
    candidates = _load_candidates(args.cache.expanduser().resolve())
    representatives = _representatives(candidates)
    cases = _build_cases(representatives, args.seed)
    by_key = {candidate.key: candidate for candidate in candidates}

    results: list[CaseResult] = []
    gain_details: list[dict[str, object]] = []
    for index, definition in enumerate(cases, start=1):
        result, details = _run_case(
            definition,
            candidates,
            by_key,
            output_dir,
            seed=args.seed * 1000 + index,
            gain_baseline_mode=args.gain_baseline_mode,
        )
        results.append(result)
        gain_details.extend(details)
        print(
            f"[{index:02d}/{len(cases)}] {definition.case_id} "
            f"Match family rank={result.dominant_family_rank} "
            f"Gain top5={result.gain_family_top5_hits}/{result.gain_steps}",
            flush=True,
        )

    result_rows = [asdict(result) for result in results]
    case_rows = [asdict(case) for case in cases]
    _write_csv(output_dir / "cases.csv", case_rows)
    _write_csv(output_dir / "results.csv", result_rows)
    _write_csv(output_dir / "gain_steps.csv", gain_details)
    summary = _summarize(candidates, representatives, cases, results)
    summary["gain_baseline_mode"] = args.gain_baseline_mode
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        _summary_markdown(summary),
        encoding="utf-8",
    )
    print()
    print(_summary_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
