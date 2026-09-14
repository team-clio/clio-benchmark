"""Deterministic score aggregation for benchmark case evaluations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from clio_benchmark.config import EvaluationConfig
from clio_benchmark.errors import BenchmarkError


class Dimension(StrEnum):
    VERDICT = "verdict"
    ROOT_CAUSE = "root_cause"
    CODE_LOCATION = "code_location"
    EVIDENCE_QUALITY = "evidence_quality"
    REPRODUCTION = "reproduction"
    UNCERTAINTY = "uncertainty"


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
