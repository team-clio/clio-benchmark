"""LangChain-based qualitative evaluation of Clio analysis results."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from clio_benchmark.config import LLMJudgeConfig
from clio_benchmark.errors import EvaluationError
from clio_benchmark.result import NormalizedResult
from clio_benchmark.suite import BenchmarkCase, GroundTruth

_PROVIDER_DEFAULTS = {
    "openai": {
        "model": "gpt-4.1",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
        "structured_output_method": "json_schema",
    },
    "deepseek": {
        "model": "deepseek-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "structured_output_method": "json_mode",
    },
}


class JudgeDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=4)
    rationale: str = Field(min_length=1)


class LLMJudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause_accuracy: JudgeDimension
    explanation_quality: JudgeDimension
    solution_validity: JudgeDimension
    evidence_quality: JudgeDimension


class Judge(Protocol):
    @property
    def metadata(self) -> dict[str, object]: ...

    def evaluate(
        self,
        case: BenchmarkCase,
        ground_truth: GroundTruth,
        result: NormalizedResult,
        suite_path: Path,
    ) -> LLMJudgeResult: ...


class LangChainLLMJudge:
    """Evaluate qualitative dimensions using LangChain structured output."""

    def __init__(self, config: LLMJudgeConfig) -> None:
        self._config = config
        self._settings = _provider_settings(config)
        api_key_env = str(self._settings["api_key_env"])
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise EvaluationError(
                f"LLM Judge API key environment variable is not set: {api_key_env}"
            )
        kwargs: dict[str, object] = {
            "model": self._settings["model"],
            "api_key": api_key,
            "temperature": config.temperature,
            "timeout": config.timeout_seconds,
            "max_retries": config.max_retries,
        }
        if self._settings["base_url"] is not None:
            kwargs["base_url"] = self._settings["base_url"]
        model = ChatOpenAI(**kwargs)
        method = str(self._settings["structured_output_method"])
        structured_kwargs: dict[str, object] = {"method": method}
        if method == "json_schema":
            structured_kwargs["strict"] = True
        self._structured_model = model.with_structured_output(
            LLMJudgeResult, **structured_kwargs
        )

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "implementation": "langchain-openai-compatible",
            "provider": self._config.provider,
            "model": self._settings["model"],
            "baseUrl": self._settings["base_url"],
            "temperature": self._config.temperature,
            "timeoutSeconds": self._config.timeout_seconds,
            "maxRetries": self._config.max_retries,
            "promptVersion": self._config.prompt_version,
        }

    def evaluate(
        self,
        case: BenchmarkCase,
        ground_truth: GroundTruth,
        result: NormalizedResult,
        suite_path: Path,
    ) -> LLMJudgeResult:
        source = _read_source(suite_path, ground_truth.location.file)
        source = _source_excerpt(
            source, ground_truth.location.lines, self._config.max_source_chars
        )
        messages = [
            SystemMessage(content=_system_prompt(self._config.prompt_version)),
            HumanMessage(
                content=_evaluation_input(case, ground_truth, result, source)
            ),
        ]
        try:
            response = self._structured_model.invoke(messages)
            if isinstance(response, LLMJudgeResult):
                return response
            return LLMJudgeResult.model_validate(response)
        except Exception as exc:
            raise EvaluationError(f"LLM Judge evaluation failed: {exc}") from exc


def _read_source(suite_path: Path, relative_file: str) -> str:
    root = suite_path.resolve()
    source_path = (root / relative_file).resolve()
    if not source_path.is_relative_to(root):
        raise EvaluationError(f"Ground-truth source path escapes suite: {relative_file}")
    try:
        return source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvaluationError(f"Cannot read Judge source file {relative_file}: {exc}") from exc


def _source_excerpt(source: str, lines: tuple[int, int], max_chars: int) -> str:
    source_lines = source.splitlines()
    expected_start, expected_end = lines
    start = max(0, expected_start - 51)
    end = min(len(source_lines), expected_end + 50)
    numbered = "\n".join(
        f"{line_number:>6}: {text}"
        for line_number, text in enumerate(source_lines[start:end], start=start + 1)
    )
    return numbered[:max_chars]


def _provider_settings(config: LLMJudgeConfig) -> dict[str, object | None]:
    defaults = _PROVIDER_DEFAULTS[config.provider]
    return {
        "model": config.model or defaults["model"],
        "api_key_env": config.api_key_env or defaults["api_key_env"],
        "base_url": str(config.base_url) if config.base_url is not None else defaults["base_url"],
        "structured_output_method": defaults["structured_output_method"],
    }


def _system_prompt(version: str) -> str:
    return f"""You are an impartial software-analysis benchmark judge.
Prompt version: {version}

Score every dimension from 0 to 4 using only the supplied material:
0 = absent or entirely incorrect
1 = mostly incorrect, with major omissions
2 = partially correct, with material omissions
3 = substantially correct, with minor omissions
4 = fully correct, specific, and supported

Judge these dimensions independently:
- root_cause_accuracy: whether the actual cause is identified correctly.
- explanation_quality: whether the failure mechanism is clear and coherent.
- solution_validity: whether the proposed fix would resolve the underlying problem safely.
- evidence_quality: whether claims are grounded in the supplied source and execution facts.

Do not reward verbosity. Do not infer facts that are not in the supplied material.
Return only JSON matching this schema:
{LLMJudgeResult.model_json_schema()}"""


def _evaluation_input(
    case: BenchmarkCase,
    ground_truth: GroundTruth,
    result: NormalizedResult,
    source: str,
) -> str:
    return f"""## Bug report
{case.report.model_dump_json(indent=2)}

## Ground truth
{ground_truth.model_dump_json(indent=2)}

## Clio analysis result
{result.model_dump_json(indent=2)}

## Source file: {ground_truth.location.file}
```text
{source}
```"""
