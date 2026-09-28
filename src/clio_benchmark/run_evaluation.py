"""Evaluate completed runs and render human-readable reports."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from clio_benchmark.config import BenchmarkConfig
from clio_benchmark.errors import BenchmarkError
from clio_benchmark.manifest import RunManifest
from clio_benchmark.oracle import load_oracle
from clio_benchmark.scoring import report_as_dict, score_case
from clio_benchmark.workspace import Workspace


def evaluate_run(
    config: BenchmarkConfig, workspace: Workspace, manifest: RunManifest
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    project_ids: set[int] = set()
    for suite in config.suites:
        if suite.oracle is None:
            continue
        oracle = load_oracle(suite.oracle)
        oracle_by_id = {case.id: case for case in oracle.cases}
        unknown_ids = set(suite.case_ids) - set(oracle_by_id)
        if unknown_ids:
            raise BenchmarkError(f"Unknown oracle case_ids: {sorted(unknown_ids)}")
        selected_oracles = (
            [oracle_by_id[case_id] for case_id in suite.case_ids]
            if suite.case_ids
            else oracle.cases
        )
        for expected in selected_oracles:
            result_path = (
                workspace.runs
                / manifest.run_id
                / "cases"
                / suite.name
                / expected.id
                / "result.json"
            )
            result = _read_json(result_path)
            project = result.get("project") or {}
            project_id = project.get("id")
            if not isinstance(project_id, int) or project_id in project_ids:
                raise BenchmarkError(
                    f"Benchmark case is not isolated in a unique project: {expected.id}"
                )
            project_ids.add(project_id)
            _verify_profile(result, config.experiment.profile)
            report = score_case(result, expected, config.evaluation)
            serialized = report_as_dict(report)
            serialized.update({"suite": suite.name, "case_id": expected.id})
            workspace.write_run_artifact(
                manifest.run_id,
                Path("cases") / suite.name / expected.id / "score.json",
                serialized,
            )
            cases.append(serialized)
    if not cases:
        raise BenchmarkError("No oracle-backed benchmark cases were found")

    summary = _summarize(config, manifest, cases)
    workspace.write_run_artifact(manifest.run_id, Path("summary.json"), summary)
    workspace.write_run_text_artifact(manifest.run_id, Path("report.md"), render_report(summary))
    return summary


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        f"# Clio Benchmark — {summary['profile']}",
        "",
        f"- Run: `{summary['run_id']}`",
        f"- Repetition: {summary['repetition']}",
        f"- Cases: {summary['case_count']}",
        f"- Mean quality score: **{summary['mean_score']:.2f}/100**",
        f"- Pass rate: **{summary['pass_rate'] * 100:.1f}%**",
        "",
        "## Quality dimensions",
        "",
        "| Dimension | Mean |",
        "|---|---:|",
    ]
    for name, value in summary["dimensions"].items():
        lines.append(f"| {name} | {value * 100:.1f}% |")
    lines.extend(
        ["", "## Cases", "", "| Suite / case | Score | Result | Duration |", "|---|---:|---|---:|"]
    )
    for case in summary["cases"]:
        duration = case["efficiency"].get("duration_seconds")
        duration_text = f"{duration:.2f}s" if duration is not None else "N/A"
        verdict = "PASS" if case["passed"] else "FAIL"
        lines.append(
            f"| {case['suite']} / {case['case_id']} | {case['score']:.2f} | "
            f"{verdict} | {duration_text} |"
        )
    lines.extend(
        [
            "",
            "> Token, model-call and tool-call metrics remain N/A until Agent tracing "
            "is connected.",
        ]
    )
    return "\n".join(lines)


def render_comparison(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Clio Benchmark Comparison",
        "",
        "| Profile | Repetition | Cases | Mean score | Pass rate | Mean duration |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        duration = summary["efficiency"].get("mean_duration_seconds")
        duration_text = f"{duration:.2f}s" if duration is not None else "N/A"
        lines.append(
            f"| {summary['profile']} | {summary['repetition']} | "
            f"{summary['case_count']} | {summary['mean_score']:.2f} | "
            f"{summary['pass_rate'] * 100:.1f}% | {duration_text} |"
        )
    return "\n".join(lines)


def load_summary(workspace: Workspace, run_id: str) -> dict[str, Any]:
    return _read_json(workspace.runs / run_id / "summary.json")


def _summarize(
    config: BenchmarkConfig, manifest: RunManifest, cases: list[dict[str, Any]]
) -> dict[str, Any]:
    dimensions = {
        name: mean(
            result["value"]
            for case in cases
            for result in case["dimensions"]
            if result["dimension"] == name
        )
        for name in config.evaluation.weights.as_dict()
    }
    durations = [
        case["efficiency"]["duration_seconds"]
        for case in cases
        if case["efficiency"]["duration_seconds"] is not None
    ]
    return {
        "schema_version": 1,
        "run_id": manifest.run_id,
        "profile": config.experiment.profile,
        "repetition": config.experiment.repetition,
        "case_count": len(cases),
        "mean_score": mean(case["score"] for case in cases),
        "pass_rate": mean(1.0 if case["passed"] else 0.0 for case in cases),
        "dimensions": dimensions,
        "efficiency": {
            "mean_duration_seconds": mean(durations) if durations else None,
        },
        "cases": cases,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"Benchmark artifact not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"Invalid benchmark artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError(f"Benchmark artifact must be an object: {path}")
    return payload


def _verify_profile(result: dict[str, Any], expected: str) -> None:
    workflow = result.get("workflow") or {}
    snapshot = workflow.get("result_snapshot") or workflow.get("resultSnapshot") or {}
    actual = snapshot.get("analysis_profile")
    if actual is not None and actual != expected:
        raise BenchmarkError(
            f"Agent profile mismatch: expected {expected}, workflow reported {actual}"
        )
