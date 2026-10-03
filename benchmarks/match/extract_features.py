from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from collections.abc import Mapping, Sequence
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
import math
import time

from benchmarks.match.generate_profiles import ReferenceLine, generate_profile
from benchmarks.match.scenarios import ScenarioDefinition
from xrd_finder.finder.fingerprint_matching import FingerprintMatchFeatures, fingerprint_match_score
from xrd_finder.services.geometric_fingerprint import peak_geometric_hashes, rank_fingerprint_candidates


@dataclass(frozen=True, slots=True)
class FeatureExtractionConfig:
    fingerprint_refine_limit: int = 40
    quick_refine_limit: int = 60
    detector_distance_scale: float = 1.0
    adaptive_line_tolerance: bool = False


@dataclass(frozen=True, slots=True)
class FeatureRow:
    query_id: str
    candidate_id: str
    candidate_family: str
    dominant_family: str
    true_families: tuple[str, ...]
    split: str
    stratum: str
    features: FingerprintMatchFeatures
    refined: bool = True


@dataclass(frozen=True, slots=True)
class QueryTiming:
    query_id: str
    candidate_count: int
    refined_count: int
    generation_seconds: float
    retrieval_seconds: float
    quick_seconds: float
    refine_seconds: float
    total_seconds: float


@dataclass(frozen=True, slots=True)
class FeatureMatrix:
    rows: tuple[FeatureRow, ...]
    timings: tuple[QueryTiming, ...] = ()

    def select_splits(self, splits: Iterable[str]) -> "FeatureMatrix":
        allowed = set(splits)
        rows = tuple(row for row in self.rows if row.split in allowed)
        query_ids = {row.query_id for row in rows}
        return FeatureMatrix(rows, tuple(item for item in self.timings if item.query_id in query_ids))

    def query_ids(self) -> tuple[str, ...]:
        return tuple(sorted({row.query_id for row in self.rows}))


def extract_match_features(
    references: Mapping[str, Sequence[ReferenceLine]],
    family_by_phase: Mapping[str, str],
    scenarios: Sequence[ScenarioDefinition],
    *,
    wavelength: float = 1.5406,
    max_reference_lines: int = 64,
    max_observed_lines: int = 48,
    line_tolerance_two_theta: float = 0.55,
    config: FeatureExtractionConfig = FeatureExtractionConfig(),
    progress: Callable[[int, int, QueryTiming], None] | None = None,
) -> FeatureMatrix:
    candidate_ids = tuple(sorted(references))
    candidate_hashes = {
        ("BENCHMARK", candidate_id): peak_geometric_hashes(references[candidate_id])
        for candidate_id in candidate_ids
    }
    rows = []
    timings = []
    for scenario in scenarios:
        query_started = time.perf_counter()
        generated = generate_profile(
            references,
            scenario,
            detector_distance_scale=config.detector_distance_scale,
        )
        generation_finished = time.perf_counter()
        dominant = max(scenario.components, key=lambda component: component.fraction)
        true_families = tuple(dict.fromkeys(component.family_id for component in scenario.components))
        stratum = f"phases={len(scenario.components)};fwhm={scenario.fwhm:.2f};noise={scenario.noise};overlap={scenario.overlap}"

        query_hashes = peak_geometric_hashes(generated.observed_records, expanded=True)
        fingerprint_order = rank_fingerprint_candidates(query_hashes, candidate_hashes)
        retrieval_finished = time.perf_counter()

        quick_results = {}
        for candidate_id in candidate_ids:
            quick_results[candidate_id] = fingerprint_match_score(
                references[candidate_id],
                list(generated.observed_records),
                wavelength=wavelength,
                max_reference_lines=max_reference_lines,
                max_observed_lines=max_observed_lines,
                line_tolerance_two_theta=line_tolerance_two_theta,
                refine_alignment=False,
                adaptive_line_tolerance=config.adaptive_line_tolerance,
            )
        quick_finished = time.perf_counter()
        refine_ids = {
            item.key[1]
            for item in fingerprint_order[: max(0, int(config.fingerprint_refine_limit))]
        }
        quick_order = sorted(
            candidate_ids,
            key=lambda candidate_id: (-quick_results[candidate_id].score, candidate_id),
        )
        refine_ids.update(quick_order[: max(0, int(config.quick_refine_limit))])

        for candidate_id in candidate_ids:
            refined = candidate_id in refine_ids
            result = quick_results[candidate_id]
            if refined:
                result = fingerprint_match_score(
                    references[candidate_id],
                    list(generated.observed_records),
                    wavelength=wavelength,
                    max_reference_lines=max_reference_lines,
                    max_observed_lines=max_observed_lines,
                    line_tolerance_two_theta=line_tolerance_two_theta,
                    refine_alignment=True,
                    adaptive_line_tolerance=config.adaptive_line_tolerance,
                )
            rows.append(
                FeatureRow(
                    query_id=scenario.scenario_id,
                    candidate_id=candidate_id,
                    candidate_family=family_by_phase[candidate_id],
                    dominant_family=dominant.family_id,
                    true_families=true_families,
                    split=scenario.split,
                    stratum=stratum,
                    features=result.features,
                    refined=refined,
                )
            )
        query_finished = time.perf_counter()
        timings.append(
            QueryTiming(
                query_id=scenario.scenario_id,
                candidate_count=len(candidate_ids),
                refined_count=len(refine_ids),
                generation_seconds=generation_finished - query_started,
                retrieval_seconds=retrieval_finished - generation_finished,
                quick_seconds=quick_finished - retrieval_finished,
                refine_seconds=query_finished - quick_finished,
                total_seconds=query_finished - query_started,
            )
        )
        if progress is not None:
            progress(len(timings), len(scenarios), timings[-1])
    return FeatureMatrix(tuple(rows), tuple(timings))


def extract_match_features_parallel(
    references: Mapping[str, Sequence[ReferenceLine]],
    family_by_phase: Mapping[str, str],
    scenarios: Sequence[ScenarioDefinition],
    *,
    workers: int,
    wavelength: float = 1.5406,
    max_reference_lines: int = 64,
    max_observed_lines: int = 48,
    line_tolerance_two_theta: float = 0.55,
    config: FeatureExtractionConfig = FeatureExtractionConfig(),
) -> FeatureMatrix:
    worker_count = max(1, min(int(workers), len(scenarios))) if scenarios else 1
    if worker_count == 1:
        return extract_match_features(
            references,
            family_by_phase,
            scenarios,
            wavelength=wavelength,
            max_reference_lines=max_reference_lines,
            max_observed_lines=max_observed_lines,
            line_tolerance_two_theta=line_tolerance_two_theta,
            config=config,
        )
    chunk_size = int(math.ceil(len(scenarios) / worker_count))
    chunks = tuple(
        tuple(scenarios[start : start + chunk_size])
        for start in range(0, len(scenarios), chunk_size)
    )
    arguments = [
        (
            references,
            family_by_phase,
            chunk,
            wavelength,
            max_reference_lines,
            max_observed_lines,
            line_tolerance_two_theta,
            config,
        )
        for chunk in chunks
    ]
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        matrices = list(executor.map(_extract_feature_chunk, arguments))
    return FeatureMatrix(
        tuple(row for matrix in matrices for row in matrix.rows),
        tuple(item for matrix in matrices for item in matrix.timings),
    )


def _extract_feature_chunk(arguments) -> FeatureMatrix:
    (
        references,
        family_by_phase,
        scenarios,
        wavelength,
        max_reference_lines,
        max_observed_lines,
        line_tolerance_two_theta,
        config,
    ) = arguments
    return extract_match_features(
        references,
        family_by_phase,
        scenarios,
        wavelength=wavelength,
        max_reference_lines=max_reference_lines,
        max_observed_lines=max_observed_lines,
        line_tolerance_two_theta=line_tolerance_two_theta,
        config=config,
    )


__all__ = [
    "FeatureExtractionConfig",
    "FeatureMatrix",
    "FeatureRow",
    "QueryTiming",
    "extract_match_features",
    "extract_match_features_parallel",
]
