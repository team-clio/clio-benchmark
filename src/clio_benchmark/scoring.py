"""Deterministic evaluation of persisted Clio benchmark results."""

from __future__ import annotations

import json
from typing import Any

from clio_benchmark.config import EvaluationConfig
from clio_benchmark.evaluation import (
    Dimension,
    DimensionResult,
    EfficiencyMetrics,
    EvaluationMethod,
    ScoreReport,
    aggregate_score,
)
from clio_benchmark.oracle import CaseOracle


def score_case(result: dict[str, Any], oracle: CaseOracle, config: EvaluationConfig) -> ScoreReport:
    analysis_wrapper = result.get("analysis") or {}
    analysis = analysis_wrapper.get("issueAnalysis") or {}
    bug = result.get("bug") or {}
    analysis_text = _flatten_text(analysis)
    evidence = analysis.get("evidence") or []
    evidence_text = _flatten_text(evidence)

    dimensions = (
        _score_verdict(bug, analysis, oracle),
        _score_root_cause(analysis_text, oracle),
        _score_locations(analysis_text, oracle),
        _score_evidence(evidence, evidence_text, oracle),
        _score_reproduction(analysis, oracle),
        _score_uncertainty(analysis, oracle),
    )
    efficiency_payload = result.get("efficiency") or {}
    efficiency = EfficiencyMetrics(
        input_tokens=efficiency_payload.get("input_tokens"),
        output_tokens=efficiency_payload.get("output_tokens"),
        duration_seconds=efficiency_payload.get("duration_seconds"),
        model_calls=efficiency_payload.get("model_calls"),
        tool_calls=efficiency_payload.get("tool_calls"),
    )
    return aggregate_score(dimensions, config, efficiency)


def report_as_dict(report: ScoreReport) -> dict[str, Any]:
    return {
        "score": report.score,
        "passed": report.passed,
        "dimensions": [
            {
                "dimension": result.dimension.value,
                "value": result.value,
                "method": result.method.value,
                "rationale": result.rationale,
            }
            for result in report.dimensions
        ],
        "efficiency": {
            "input_tokens": report.efficiency.input_tokens,
            "output_tokens": report.efficiency.output_tokens,
            "total_tokens": report.efficiency.total_tokens,
            "duration_seconds": report.efficiency.duration_seconds,
            "model_calls": report.efficiency.model_calls,
            "tool_calls": report.efficiency.tool_calls,
        },
    }


def _score_verdict(
    bug: dict[str, Any], analysis: dict[str, Any], oracle: CaseOracle
) -> DimensionResult:
    checks = [
        _same_status(analysis.get("status"), oracle.verdict.expected_analysis_status),
    ]
    if oracle.verdict.expected_bug_status is not None:
        checks.append(_same_status(bug.get("status"), oracle.verdict.expected_bug_status))
    return _result(Dimension.VERDICT, checks, "expected workflow verdicts")


def _score_root_cause(text: str, oracle: CaseOracle) -> DimensionResult:
    checks = [_contains_any(text, concept) for concept in oracle.root_cause.required_concepts]
    return _result(Dimension.ROOT_CAUSE, checks, "required root-cause concepts")


def _score_locations(text: str, oracle: CaseOracle) -> DimensionResult:
    checks: list[bool] = []
    for location in oracle.code_locations:
        checks.append(_contains(text, location.path))
        if location.symbols:
            checks.append(_contains_any(text, location.symbols))
    return _result(Dimension.CODE_LOCATION, checks, "expected files and symbols")


def _score_evidence(
    evidence: list[dict[str, Any]], text: str, oracle: CaseOracle
) -> DimensionResult:
    checks = [_contains(text, path) for path in oracle.evidence.required_paths]
    checks.append(len(evidence) >= oracle.evidence.minimum_citations)
    for citation in evidence:
        checks.append(bool(citation.get("source_type")))
        checks.append(bool(citation.get("location") or citation.get("file_path")))
        checks.append(
            bool(
                citation.get("commit")
                or citation.get("source_revision")
                or citation.get("knowledge_revision")
            )
        )
    return _result(Dimension.EVIDENCE_QUALITY, checks, "coverage and citation integrity")


def _score_reproduction(analysis: dict[str, Any], oracle: CaseOracle) -> DimensionResult:
    plan = analysis.get("resolution_plan") or {}
    text = _flatten_text(plan if oracle.reproduction.mode == "plan" else analysis)
    checks = [_contains_any(text, concept) for concept in oracle.reproduction.required_concepts]
    if not checks:
        checks = [bool(plan)]
    label = f"reproduction {oracle.reproduction.mode} evidence"
    return _result(Dimension.REPRODUCTION, checks, label)


def _score_uncertainty(analysis: dict[str, Any], oracle: CaseOracle) -> DimensionResult:
    expected = oracle.uncertainty
    checks = [_same_status(analysis.get("status"), expected.expected_analysis_status)]
    confidence = analysis.get("confidence")
    if expected.minimum_confidence is not None:
        checks.append(
            isinstance(confidence, int | float) and confidence >= expected.minimum_confidence
        )
    if expected.maximum_confidence is not None:
        checks.append(
            isinstance(confidence, int | float) and confidence <= expected.maximum_confidence
        )
    return _result(Dimension.UNCERTAINTY, checks, "review state and confidence calibration")


def _result(dimension: Dimension, checks: list[bool], label: str) -> DimensionResult:
    passed = sum(checks)
    total = len(checks)
    value = passed / total if total else 0.0
    return DimensionResult(
        dimension=dimension,
        value=value,
        method=EvaluationMethod.DETERMINISTIC,
        rationale=f"{passed}/{total} checks passed for {label}",
    )


def _flatten_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()


def _contains(text: str, term: str) -> bool:
    return term.casefold() in text


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(_contains(text, term) for term in terms)


def _same_status(actual: Any, expected: str) -> bool:
    return str(actual).casefold() == expected.casefold()
