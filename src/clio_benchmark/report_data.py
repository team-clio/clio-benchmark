"""저장한 실행 자료에서 재현 가능한 보고서용 데이터를 구성한다."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from pydantic import ValidationError

from clio_benchmark.llm_judge import LLMJudgeResult
from clio_benchmark.manifest import RunManifest
from clio_benchmark.result import CaseExecutionResult, NormalizedResult, normalize_clio_result

DIMENSIONS = {
    "root_cause_accuracy": "근본 원인 정확성",
    "explanation_quality": "설명 품질",
    "solution_validity": "해결책 타당성",
    "evidence_quality": "근거 품질",
}


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) and value >= 0 else None
    return None


def duration_stats(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "median": None, "p90": None, "max": None}
    position = (len(ordered) - 1) * 0.9
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    p90 = ordered[low] + (ordered[high] - ordered[low]) * (position - low)
    return {"count": len(ordered), "median": median(ordered), "p90": p90, "max": ordered[-1]}


def aggregate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [
        case for case in cases if isinstance(case["evaluation"].get("deterministic"), dict)
    ]
    judge_counts: Counter[str] = Counter()
    scores: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        judge = case["evaluation"].get("llmJudge", {})
        status = judge.get("status", "unavailable")
        judge_counts[status] += 1
        if status == "completed":
            for key in DIMENSIONS:
                score = _number(judge.get("result", {}).get(key, {}).get("score"))
                if score is not None and score <= 4:
                    scores[key].append(score)
    durations: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        duration = _number(case["metrics"].get("duration_seconds"))
        if duration is not None:
            durations["completed" if case["status"] == "completed" else "other"].append(duration)
    return {
        "known_cases": len(cases),
        "processed_cases": sum(case["status"] not in {"not_run", "interrupted"} for case in cases),
        "status_counts": dict(Counter(case["status"] for case in cases)),
        "evaluated_cases": len(evaluated),
        "detected_cases": sum(
            case["evaluation"]["deterministic"].get("detected") is True for case in evaluated
        ),
        "location_matches": sum(
            case["evaluation"]["deterministic"].get("locationMatches") is True for case in evaluated
        ),
        "judge_counts": dict(judge_counts),
        "judge_scores": {
            key: {
                "mean": sum(scores[key]) / len(scores[key]) if scores[key] else None,
                "count": len(scores[key]),
            }
            for key in DIMENSIONS
        },
        "durations": {key: duration_stats(durations[key]) for key in ("completed", "other")},
    }


def collect_report_data(run_dir: Path, manifest: RunManifest) -> dict[str, Any]:
    warnings: list[str] = []
    artifacts: list[str] = []

    def read(path: str) -> dict[str, Any]:
        file = run_dir / path
        if not file.exists():
            return {}
        if not file.resolve().is_relative_to(run_dir.resolve()):
            warnings.append(f"실행 디렉터리 밖의 자료를 생략했습니다: {path}")
            return {}
        artifacts.append(path)
        try:
            value = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value
        except (OSError, ValueError) as exc:
            warnings.append(f"자료를 읽지 못했습니다: {path} ({exc})")
            return {}

    cases: list[dict[str, Any]] = []
    suites: list[dict[str, Any]] = []
    configured = {item["name"] for item in manifest.config.get("suites", [])}
    discovered = {path.name for path in (run_dir / "cases").glob("*") if path.is_dir()}
    for name in sorted(configured | discovered):
        # 설정 스키마를 통과한 suite/case 이름만 로컬 경로로 사용한다.
        if not _safe_name(name):
            warnings.append("유효하지 않은 suite 이름을 생략했습니다.")
            continue
        metadata = read(f"suites/{name}/metadata.json")
        snapshot = read(f"suites/{name}/cases.json")
        truth_snapshot = read(f"suites/{name}/ground-truth.json")
        planned = {item["id"]: item for item in snapshot.get("cases", [])}
        truths = {item["id"]: item for item in truth_snapshot.get("bugs", [])}
        ids = set(planned) | {
            path.name for path in (run_dir / "cases" / name).glob("*") if path.is_dir()
        }
        suite_cases = []
        for case_id in sorted(ids):
            if not _safe_name(case_id):
                warnings.append("유효하지 않은 case 이름을 생략했습니다.")
                continue
            prefix = f"cases/{name}/{case_id}"
            input_data = read(f"{prefix}/input.json")
            submitted = bool(input_data)
            metrics = read(f"{prefix}/metrics.json")
            if metrics:
                try:
                    CaseExecutionResult.model_validate(metrics)
                except ValidationError:
                    warnings.append(
                        f"{prefix}: metrics 스키마가 유효하지 않아 상태 집계에서 제외합니다."
                    )
                    metrics = {}
            raw = read(f"{prefix}/clio-result.json")
            normalized = read(f"{prefix}/normalized-result.json")
            if normalized:
                try:
                    NormalizedResult.model_validate(normalized)
                except ValidationError:
                    warnings.append(
                        f"{prefix}: 정규화 결과가 유효하지 않아 원시 응답으로 대체합니다."
                    )
                    normalized = {}
            normalization = "saved"
            if not normalized and raw:
                normalized = normalize_clio_result(raw).model_dump(mode="json")
                normalization = "recomputed-v1"
            evaluation = read(f"{prefix}/evaluation.json")
            deterministic = evaluation.get("deterministic")
            if deterministic is not None and (
                not isinstance(deterministic, dict)
                or not all(
                    isinstance(deterministic.get(key), bool)
                    for key in ("detected", "locationMatches")
                )
            ):
                warnings.append(f"{prefix}: 결정적 평가가 유효하지 않아 분모에서 제외합니다.")
                evaluation.pop("deterministic", None)
            judge = evaluation.get("llmJudge", {})
            if not isinstance(judge, dict):
                evaluation["llmJudge"] = {"status": "unavailable"}
                warnings.append(f"{prefix}: Judge 자료가 유효하지 않습니다.")
            elif judge.get("status") == "completed":
                try:
                    LLMJudgeResult.model_validate(judge.get("result"))
                except ValidationError:
                    evaluation["llmJudge"] = {"status": "unavailable"}
                    warnings.append(
                        f"{prefix}: Judge 점수 스키마가 유효하지 않아 평균에서 제외합니다."
                    )
            input_data = input_data or planned.get(case_id, {})
            if not isinstance(input_data.get("report", {}), dict):
                warnings.append(f"{prefix}: 입력 report가 유효하지 않습니다.")
                input_data = {"id": case_id}
            status = metrics.get("status") or ("interrupted" if submitted else "not_run")
            case = {
                "id": f"{name}/{case_id}",
                "suite": name,
                "case_id": case_id,
                "status": status,
                "input": input_data,
                "ground_truth": truths.get(case_id),
                "normalized": normalized,
                "normalization": normalization,
                "evaluation": evaluation,
                "metrics": metrics,
                "artifacts": [path for path in artifacts if path.startswith(prefix + "/")],
            }
            cases.append(case)
            suite_cases.append(case)
        suites.append(
            {
                "name": name,
                "metadata": metadata,
                "planned_cases": len(planned) if snapshot else None,
                "summary": aggregate_cases(suite_cases),
            }
        )
        if ids and not truth_snapshot:
            warnings.append(
                f"{name}: 실행 당시 정답 snapshot이 없어 정답 대조를 제공하지 않습니다."
            )

    collection = read("tool-call-collection.json")
    tool_groups: dict[str, dict[str, Any]] = {}
    tool_file = run_dir / "tool-calls.jsonl"
    if tool_file.exists() and tool_file.resolve().is_relative_to(run_dir.resolve()):
        artifacts.append("tool-calls.jsonl")
        with tool_file.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("Tool record must be a JSON object")
                    if not isinstance(record.get("tool"), str) or record.get("status") not in {
                        "success",
                        "failure",
                        "running",
                    }:
                        raise ValueError("invalid Tool record")
                    name = str(record["tool"])
                    group = tool_groups.setdefault(
                        name,
                        {"tool": name, "calls": 0, "failures": 0, "running": 0, "durations": []},
                    )
                    group["calls"] += 1
                    group["failures"] += record.get("status") == "failure"
                    group["running"] += record.get("status") == "running"
                    duration = _number(record.get("duration_seconds"))
                    if duration is not None and record.get("status") != "running":
                        group["durations"].append(duration)
                except (ValueError, KeyError, TypeError):
                    warnings.append(
                        f"Tool 로그 {line_number}행이 유효하지 않아 집계에서 제외했습니다."
                    )
    tools = [
        {**group, "durations": duration_stats(group["durations"])}
        for _, group in sorted(tool_groups.items())
    ]
    elapsed = None
    try:
        if manifest.execution_started_at and manifest.execution_finished_at:
            elapsed = (
                datetime.fromisoformat(manifest.execution_finished_at)
                - datetime.fromisoformat(manifest.execution_started_at)
            ).total_seconds()
            elapsed = elapsed if elapsed >= 0 else None
    except ValueError:
        warnings.append("실행 시간 경계를 해석하지 못했습니다.")
    read("summary.json")
    artifacts.append("manifest.json")
    known_planned = all(suite["planned_cases"] is not None for suite in suites)
    planned_count = sum(suite["planned_cases"] for suite in suites) if known_planned else None
    # 환경변수·비밀 키 이름·Tool 인자/반환값은 보고서 및 서술 LLM 입력에서 제외한다.
    return {
        "schema_version": 1,
        "renderer_version": "html-report-v1",
        "run": {
            "id": manifest.run_id,
            "status": manifest.status.value,
            "created_at": manifest.created_at.isoformat(),
            "updated_at": manifest.updated_at.isoformat(),
            "error": manifest.error,
            "started_at": manifest.execution_started_at,
            "finished_at": manifest.execution_finished_at,
            "elapsed_seconds": elapsed,
            "tool_log_status": manifest.tool_log_status,
        },
        "conditions": {
            key: manifest.config.get(key, {})
            for key in ("clio", "runtime", "evaluation", "reporting")
        },
        "summary": aggregate_cases(cases),
        "planned_cases": planned_count,
        "suites": suites,
        "cases": cases,
        "tools": tools,
        "collection": collection,
        "warnings": warnings,
        "artifacts": sorted(set(artifacts)),
    }


def _safe_name(value: str) -> bool:
    return (
        bool(value)
        and value[0].isalnum()
        and all(char.isascii() and (char.isalnum() or char in "._-") for char in value)
    )
