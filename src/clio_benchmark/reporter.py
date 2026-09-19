"""Human-readable benchmark report generation."""

from __future__ import annotations

from typing import Protocol


class Summary(Protocol):
    total_cases: int
    completed_cases: int
    failed_cases: int
    detected_cases: int
    location_matches: int
    llm_evaluated_cases: int
    llm_failed_cases: int


def render_markdown_report(run_id: str, summary: Summary) -> str:
    completion_rate = (
        summary.completed_cases / summary.total_cases * 100 if summary.total_cases else 100.0
    )
    detection_rate = (
        summary.detected_cases / summary.total_cases * 100 if summary.total_cases else 0.0
    )
    location_rate = (
        summary.location_matches / summary.total_cases * 100 if summary.total_cases else 0.0
    )
    return f"""# Clio Benchmark Report

- Run ID: `{run_id}`
- Total cases: {summary.total_cases}
- Completed cases: {summary.completed_cases}
- Failed cases: {summary.failed_cases}
- Completion rate: {completion_rate:.1f}%

## Deterministic evaluation

- Bug detected: {summary.detected_cases}/{summary.total_cases} ({detection_rate:.1f}%)
- Location matched: {summary.location_matches}/{summary.total_cases} ({location_rate:.1f}%)

## Quality score

- LLM Judge completed: {summary.llm_evaluated_cases}/{summary.total_cases}
- LLM Judge failed: {summary.llm_failed_cases}/{summary.total_cases}

The final quality score is pending score aggregation. Efficiency metrics and qualitative scores
are intentionally not combined until every required evaluation dimension is available.
"""
