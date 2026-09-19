from pathlib import Path

import pytest

from clio_benchmark.config import LLMJudgeConfig
from clio_benchmark.errors import EvaluationError
from clio_benchmark.llm_judge import (
    JudgeDimension,
    LLMJudgeResult,
    _provider_settings,
    _read_source,
    _source_excerpt,
)


def test_llm_judge_result_requires_scores_from_zero_to_four() -> None:
    with pytest.raises(ValueError):
        JudgeDimension(score=5, rationale="too high")

    dimension = JudgeDimension(score=4, rationale="fully supported")
    result = LLMJudgeResult(
        root_cause_accuracy=dimension,
        explanation_quality=dimension,
        solution_validity=dimension,
        evidence_quality=dimension,
    )

    assert result.evidence_quality.score == 4


def test_judge_source_must_stay_inside_suite(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()

    with pytest.raises(EvaluationError, match="escapes suite"):
        _read_source(suite, "../secret.txt")


def test_source_excerpt_keeps_ground_truth_lines_and_line_numbers() -> None:
    source = "\n".join(f"line {number}" for number in range(1, 201))

    excerpt = _source_excerpt(source, (150, 152), 20_000)

    assert "   150: line 150" in excerpt
    assert "     1: line 1" not in excerpt


def test_deepseek_provider_uses_openai_compatible_defaults() -> None:
    settings = _provider_settings(LLMJudgeConfig(provider="deepseek"))

    assert settings["model"] == "deepseek-flash"
    assert settings["api_key_env"] == "DEEPSEEK_API_KEY"
    assert settings["base_url"] == "https://api.deepseek.com"
    assert settings["structured_output_method"] == "json_mode"


def test_provider_defaults_can_be_overridden() -> None:
    settings = _provider_settings(
        LLMJudgeConfig(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key_env="CUSTOM_KEY",
            base_url="https://gateway.example.com/v1",
        )
    )

    assert settings["model"] == "deepseek-v4-pro"
    assert settings["api_key_env"] == "CUSTOM_KEY"
    assert settings["base_url"] == "https://gateway.example.com/v1"
