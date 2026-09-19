"""Deterministic score aggregation for benchmark case evaluations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from clio_benchmark.config import EvaluationConfig
from clio_benchmark.errors import BenchmarkError
from clio_benchmark.result import NormalizedResult
from clio_benchmark.suite import GroundTruth


class Dimension(StrEnum):
    RECALL = "recall"
    PRECISION = "precision"
    LOCATION_ACCURACY = "location_accuracy"
    ROOT_CAUSE_ACCURACY = "root_cause_accuracy"
    EXPLANATION_QUALITY = "explanation_quality"
    SOLUTION_VALIDITY = "solution_validity"
    EXECUTION_RELIABILITY = "execution_reliability"


class EvaluationMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_JUDGE = "llm_judge"


@dataclass(frozen=True)
class DimensionResult:
    dimension: Dimension
    value: float
    method: EvaluationMethod
    rationale: str

    def __post_init__(self) -> None:
        if not 0 <= self.value <= 1:
            raise ValueError("dimension value must be between 0 and 1")
        if not self.rationale.strip():
            raise ValueError("dimension rationale must not be empty")


@dataclass(frozen=True)
class EfficiencyMetrics:
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_seconds: float | None = None
    model_calls: int | None = None
    tool_calls: int | None = None

    def __post_init__(self) -> None:
        values = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_seconds": self.duration_seconds,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
        }
        invalid = [name for name, value in values.items() if value is not None and value < 0]
        if invalid:
            raise ValueError(f"Efficiency metrics must not be negative: {', '.join(invalid)}")

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ScoreReport:
    score: float
    passed: bool
    dimensions: tuple[DimensionResult, ...]
    efficiency: EfficiencyMetrics


@dataclass(frozen=True)
class DeterministicEvaluation:
    detected: bool
    location_matches: bool
    matched_location: str | None


def evaluate_deterministic(
    result: NormalizedResult, ground_truth: GroundTruth
) -> DeterministicEvaluation:
    """Evaluate facts that do not require an LLM judge."""
    expected_path = _normalized_path(ground_truth.location.file)
    expected_start, expected_end = ground_truth.location.lines
    tolerance = ground_truth.location_tolerance

    for location in result.locations:
        if _normalized_path(location.file) != expected_path:
            continue
        if location.start_line is None:
            continue
        actual_start = location.start_line
        actual_end = location.end_line or actual_start
        overlaps = (
            actual_end >= expected_start - tolerance
            and actual_start <= expected_end + tolerance
        )
        if overlaps:
            return DeterministicEvaluation(
                detected=result.detected,
                location_matches=True,
                matched_location=f"{location.file}:{actual_start}-{actual_end}",
            )

    return DeterministicEvaluation(
        detected=result.detected,
        location_matches=False,
        matched_location=None,
    )


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def aggregate_score(
    results: Iterable[DimensionResult],
    config: EvaluationConfig,
    efficiency: EfficiencyMetrics | None = None,
) -> ScoreReport:
    """Aggregate normalized dimensions without mixing efficiency into quality."""
    materialized = tuple(results)
    by_dimension = {result.dimension: result for result in materialized}
    if len(by_dimension) != len(materialized):
        raise BenchmarkError("Each score dimension may be reported only once")

    weights = config.weights.as_dict()
    required = {Dimension(name) for name, weight in weights.items() if weight > 0}
    missing = required - set(by_dimension)
    if missing:
        names = ", ".join(sorted(item.value for item in missing))
        raise BenchmarkError(f"Missing required score dimensions: {names}")

    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise BenchmarkError("At least one evaluation weight must be greater than zero")

    weighted = sum(
        by_dimension[Dimension(name)].value * weight
        for name, weight in weights.items()
        if weight > 0
    )
    score = round(weighted / total_weight * 100, 2)
    return ScoreReport(
        score=score,
        passed=score >= config.pass_threshold,
        dimensions=materialized,
        efficiency=efficiency or EfficiencyMetrics(),
    )
