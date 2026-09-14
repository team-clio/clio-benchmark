import pytest

from clio_benchmark.config import EvaluationConfig
from clio_benchmark.errors import BenchmarkError
from clio_benchmark.evaluation import (
    Dimension,
    DimensionResult,
    EfficiencyMetrics,
    EvaluationMethod,
    aggregate_score,
)


def result(dimension: Dimension, value: float) -> DimensionResult:
    return DimensionResult(
        dimension=dimension,
        value=value,
        method=EvaluationMethod.DETERMINISTIC,
        rationale="test evidence",
    )


def test_aggregates_quality_and_keeps_efficiency_separate() -> None:
    config = EvaluationConfig(pass_threshold=70)
    dimensions = [result(dimension, 0.8) for dimension in Dimension]
    efficiency = EfficiencyMetrics(input_tokens=100, output_tokens=30, duration_seconds=2.5)

    report = aggregate_score(dimensions, config, efficiency)

    assert report.score == 80
    assert report.passed is True
    assert report.efficiency.total_tokens == 130


def test_requires_every_weighted_dimension() -> None:
    with pytest.raises(BenchmarkError, match="Missing required score dimensions"):
        aggregate_score([result(Dimension.VERDICT, 1)], EvaluationConfig())


def test_rejects_out_of_range_dimension_value() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        result(Dimension.VERDICT, 1.1)


def test_rejects_negative_efficiency_metrics() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        EfficiencyMetrics(input_tokens=-1)
