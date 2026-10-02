"""고정 HTML 템플릿 렌더링과 독립적인 보고서 생성 상태를 관리한다."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import quote

from clio_benchmark.config import BenchmarkConfig
from clio_benchmark.manifest import RunManifest
from clio_benchmark.report_data import DIMENSIONS, collect_report_data
from clio_benchmark.report_narrative import (
    LangChainReportNarrator,
    Narrator,
    ReportNarrative,
    narrative_input,
)
from clio_benchmark.workspace import Workspace

STATUSES = {
    "completed": "절차 완료",
    "clio_failed": "Clio 결과 연결 실패",
    "evaluation_failed": "Judge 평가 실패",
    "infra_error": "API·인프라 오류",
    "timeout": "대기 시간 초과",
    "not_run": "미실행",
    "interrupted": "처리 중단",
}


def text(value: Any) -> str:
    return escape(str(value)) if value is not None else "—"


def number(value: Any) -> str:
    return "—" if value is None else f"{value:.2f}"


def ratio(numerator: int, denominator: int) -> str:
    rate = f"{numerator / denominator * 100:.1f}%" if denominator else "—"
    return f"{numerator} / {denominator} ({rate})"


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th scope='col'>{text(item)}</th>" for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{item}</td>" for item in row) + "</tr>" for row in rows)
    if not body:
        body = f"<tr><td class='empty' colspan='{len(headers)}'>확보된 자료가 없습니다.</td></tr>"
    return (
        f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def evidence(ids: list[str]) -> str:
    links = []
    for item in ids:
        target = {"run:summary": "overview", "run:execution": "execution"}.get(item)
        if target is None:
            target = case_anchor(item)
        links.append(f"<a href='#{target}'>{text(item)}</a>")
    return "<span class='caption'>근거: " + ", ".join(links) + "</span>"


def case_anchor(case_id: str) -> str:
    # percent encoding은 브라우저가 fragment에서 해제하므로 안전한 ASCII ID를 사용한다.
    return "case-" + case_id.encode("utf-8").hex()


def narratives(items: list[Any]) -> str:
    return "".join(
        f"<p class='text'>{text(item.text)}</p><p>{evidence(item.evidence)}</p>" for item in items
    )


def paragraph(label: str, value: Any) -> str:
    if isinstance(value, list):
        value = "\n".join(str(item) for item in value) or None
    return f"<p><strong>{text(label)}</strong></p><p class='text'>{text(value)}</p>"


def flag(value: Any, positive: str, negative: str) -> str:
    if value is None:
        return "—"
    return positive if value is True else negative


def case_details(case: dict[str, Any]) -> str:
    report = case["input"].get("report", {})
    truth = case["ground_truth"] or {}
    result = case["normalized"]
    source = truth.get("location", {})
    left = paragraph("입력 증상", report.get("description"))
    left += paragraph(
        "기대 / 실제 동작",
        f"{report.get('expected_behavior', '—')} / {report.get('actual_behavior', '—')}",
    )
    left += paragraph("재현 절차", report.get("steps_to_reproduce"))
    left += paragraph("정답 원인", truth.get("root_cause"))
    left += paragraph(
        "정답 위치 / 허용 오차",
        f"{source.get('file', '—')} "
        f"{source.get('lines', '—')} / {truth.get('location_tolerance', '—')}",
    )
    right = "".join(
        paragraph(label, result.get(key))
        for key, label in [
            ("root_cause", "Clio 원인"),
            ("explanation", "설명"),
            ("solution", "해결책"),
            ("evidence", "근거"),
        ]
    )
    locations = [
        f"{item.get('file')}: {item.get('start_line')}–{item.get('end_line')}"
        for item in result.get("locations", [])
    ]
    right += paragraph("코드 위치", locations)
    judge = case["evaluation"].get("llmJudge", {})
    reasons = []
    for key, label in DIMENSIONS.items():
        dimension = judge.get("result", {}).get(key, {})
        reasons.append(
            [text(label), text(dimension.get("score")), text(dimension.get("rationale"))]
        )
    body = f"<div class='columns'><div>{left}</div><div>{right}</div></div>"
    body += table(["Judge 항목", "점수 / 4", "판단 근거"], reasons)
    body += paragraph("Judge 상태", judge.get("status", "미확보"))
    if case["metrics"].get("error") or judge.get("error"):
        body += paragraph("오류", case["metrics"].get("error") or judge.get("error"))
    if not truth:
        body += (
            "<p class='caption'>실행 당시 정답 snapshot 미확보. "
            "현재 checkout으로 대체하지 않았습니다.</p>"
        )
    if case["normalization"] == "recomputed-v1":
        body += (
            "<p class='caption'>과거 실행: 원시 응답을 현재 정규화 함수(v1)로 다시 읽었습니다.</p>"
        )
    body += "<p>" + " · ".join(artifact_link(path) for path in case["artifacts"]) + "</p>"
    return (
        f"<details id='{case_anchor(case['id'])}'><summary>{text(case['id'])} · "
        f"{text(report.get('title'))} · {text(STATUSES.get(case['status'], case['status']))}"
        f"</summary>{body}</details>"
    )


def artifact_link(path: str) -> str:
    return f"<a href='{quote(path, safe='/')}'>{text(path)}</a>"


def render_html(
    data: dict[str, Any], narrative: ReportNarrative | None, generation: dict[str, Any]
) -> str:
    summary = data["summary"]
    run = data["run"]
    evaluated = summary["evaluated_cases"]
    judge_counts = summary["judge_counts"]
    stats = [
        (
            "절차 완료 / 처리 사례",
            f"{summary['status_counts'].get('completed', 0)} / {summary['processed_cases']}",
        ),
        ("탐지 신호 / 결정적 평가 사례", ratio(summary["detected_cases"], evaluated)),
        ("위치 일치 / 결정적 평가 사례", ratio(summary["location_matches"], evaluated)),
        (
            "Judge 완료 / 처리 사례",
            f"{judge_counts.get('completed', 0)} / {summary['processed_cases']}",
        ),
    ]
    overview = (
        narratives(narrative.summary)
        if narrative
        else "<p>관측된 집계 결과를 아래에 표시합니다.</p>"
    )
    overview += (
        "<div class='stats'>"
        + "".join(
            f"<div class='stat'><span>{text(label)}</span><strong>{text(value)}</strong></div>"
            for label, value in stats
        )
        + "</div>"
    )
    overview += (
        "<p class='caption'>절차 완료는 정답 여부와 별도입니다. 결정적 평가 분모는 평가 자료가 "
        "있는 사례이며 Judge 실패 사례도 포함할 수 있습니다. 표본 0은 0%로 표시하지 않습니다.</p>"
    )
    note = {
        "completed": "LLM 서술 생성 완료",
        "disabled": "LLM 서술 비활성화",
        "skipped": "사례가 없어 LLM 서술 생략",
        "failed": "LLM 서술 생성 실패",
    }
    overview += f"<div class='notice'>{text(note[generation['narrative_status']])}"
    if generation.get("error"):
        overview += f"<p class='text'>{text(generation['error'])}</p>"
    overview += (
        "<p>종합 품질 점수: 미집계. "
        "Judge 실패·timeout·실행 오류는 분석 오답과 구분합니다.</p></div>"
    )
    for warning in data["warnings"]:
        overview += f"<p class='text'>{text(warning)}</p>"
    if not data["cases"]:
        overview += "<p>확보된 케이스가 없습니다. 실행 상태·오류와 평가 조건만 제공됩니다.</p>"
    quality_rows = []
    for suite in data["suites"]:
        item = suite["summary"]
        quality_rows.append(
            [
                text(suite["name"]),
                text(suite["planned_cases"]),
                text(item["processed_cases"]),
                text(item["evaluated_cases"]),
                ratio(item["detected_cases"], item["evaluated_cases"]),
                ratio(item["location_matches"], item["evaluated_cases"]),
            ]
        )
    quality = table(
        ["Suite", "예정", "처리", "결정적 평가", "탐지 신호", "위치 일치"], quality_rows
    )
    quality += "<h3>LLM Judge 항목별 평가</h3>" + table(
        ["항목", "평균 / 4", "표본 수"],
        [
            [
                text(label),
                number(summary["judge_scores"][key]["mean"]),
                text(summary["judge_scores"][key]["count"]),
            ]
            for key, label in DIMENSIONS.items()
        ],
    )
    quality += (
        f"<p>Judge 실패 {judge_counts.get('failed', 0)}건 · 비활성 "
        f"{judge_counts.get('disabled', 0)}건 · 미확보 {judge_counts.get('unavailable', 0)}건</p>"
    )
    quality += (
        "<p class='caption'>평균은 유효한 Judge 점수가 있는 사례만 사용합니다. "
        "실패·비활성은 0점이 아닙니다.</p>"
    )
    if narrative:
        quality += narratives(narrative.quality_analysis)
    execution = table(
        ["절차 상태", "건수"],
        [
            [text(label), text(summary["status_counts"].get(key, 0))]
            for key, label in STATUSES.items()
        ],
    )
    execution += table(
        ["분석·평가 포함 시간", "표본", "중앙값(초)", "P90(초)", "최대(초)"],
        [
            [
                label,
                text(summary["durations"][key]["count"]),
                *[number(summary["durations"][key][field]) for field in ("median", "p90", "max")],
            ]
            for key, label in [("completed", "절차 완료"), ("other", "실패·중단")]
        ],
    )
    execution += (
        f"<p>전체 경계 구간: {number(run['elapsed_seconds'])}초 · "
        f"Tool 수집: {text(run['tool_log_status'])}</p>"
        "<p class='caption'>케이스 시간에는 Judge가 포함됩니다. 전체 경계 구간은 suite 준비를 "
        "포함하고 종료 로그 다운로드는 제외합니다. P90은 선형 보간입니다.</p>"
    )
    if run["error"]:
        execution += paragraph("실행 오류", run["error"])
    if data["collection"].get("error"):
        execution += paragraph("로그 수집 오류", data["collection"]["error"])
    execution += table(
        ["Tool", "호출", "오류", "미완료", "완료 호출 중앙값(초)"],
        [
            [
                text(tool["tool"]),
                text(tool["calls"]),
                text(tool["failures"]),
                text(tool["running"]),
                number(tool["durations"]["median"]),
            ]
            for tool in data["tools"]
        ],
    )
    execution += (
        "<p class='caption'>Tool 호출은 실행 시간 경계 기준이며 다른 요청이 포함될 수 있습니다. "
        "수집 실패 시 부분 로그입니다. 토큰·모델 호출 수·비용은 표준 지표로 미수집입니다.</p>"
    )
    case_rows = []
    for case in data["cases"]:
        deterministic = case["evaluation"].get("deterministic", {})
        judge = case["evaluation"].get("llmJudge", {}).get("result", {})
        case_rows.append(
            [
                evidence([case["id"]]),
                text(case["input"].get("report", {}).get("title")),
                text(STATUSES.get(case["status"], case["status"])),
                flag(deterministic.get("detected"), "있음", "없음"),
                flag(deterministic.get("locationMatches"), "일치", "불일치"),
                " / ".join(text(judge.get(key, {}).get("score")) for key in DIMENSIONS),
                number(case["metrics"].get("duration_seconds")),
            ]
        )
    cases = table(
        ["Case", "제목", "절차 상태", "탐지", "위치", "Judge 4항목", "시간(초)"], case_rows
    )
    cases += (
        "<p class='caption'>Judge 순서: 원인 / 설명 / 해결책 / 근거. "
        "상세 영역을 펼쳐 정답과 분석을 대조합니다.</p>"
    )
    cases += "".join(case_details(case) for case in data["cases"])
    actions = (
        narratives(narrative.findings)
        if narrative
        else "<p>LLM 서술이 없어 개선 제안을 제공하지 않습니다.</p>"
    )
    if narrative:
        actions += table(
            ["제안", "관측 근거", "근거 사례", "검증 방법"],
            [
                [
                    text(item.action),
                    text(item.observation),
                    evidence(item.evidence),
                    text(item.verification),
                ]
                for item in narrative.recommendations
            ],
        )
    method = (
        "<p>확인된 suite commit과 서비스 설정 revision을 구분합니다. "
        "실제 실행 서비스 SHA·모델은 자동 검증하지 않습니다.</p>"
    )
    method += table(
        ["Suite", "저장소", "확인된 SHA"],
        [
            [
                text(suite["name"]),
                text(suite["metadata"].get("repository")),
                text(suite["metadata"].get("commit_sha")),
            ]
            for suite in data["suites"]
        ],
    )
    method += (
        "<details><summary>평가 정의와 한계</summary><ul>"
        "<li>탐지 신호는 detected이며, 명시 판정이 없으면 "
        "원인·설명·위치 존재로 추론할 수 있습니다.</li>"
        "<li>위치 일치는 동일 파일에서 정답 허용 범위와 "
        "하나 이상의 예측 범위가 겹치는 기준입니다.</li>"
        "<li>Judge 0~4점: 없음/오답, 대부분 부정확, 부분 정확, "
        "대부분 정확, 정확하고 근거 있음.</li>"
        "<li>Precision·F1은 정상 사례 라벨이 없어 산출하지 않습니다. "
        "재현·수정 테스트도 실행하지 않습니다.</li>"
        "<li>suite 내 프로젝트·Issue 공유 가능성이 있으며 최신 분석은 "
        "해당 Bug만의 독립 snapshot을 보장하지 않습니다.</li>"
        "<li>서비스 실행·격리는 자동 검증되지 않습니다. "
        "timeout은 Bug 대기와 분석 대기에 각각 적용됩니다.</li>"
        "<li>예정 수가 없으면 전체 coverage는 확인 불가입니다. "
        "단일 실행으로 개선 추세를 주장하지 않습니다.</li>"
        "</ul></details>"
    )
    method += (
        "<details><summary>실행·평가·서술 설정</summary><pre>"
        + text(
            json.dumps(
                {
                    "conditions": data["conditions"],
                    "narrative": generation.get("metadata", {}),
                    "planned_cases": data["planned_cases"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        + "</pre></details>"
    )
    method += (
        "<details><summary>원시 자료</summary><ul>"
        + "".join(f"<li>{artifact_link(path)}</li>" for path in data["artifacts"])
        + "</ul></details>"
    )
    template = Template(
        files("clio_benchmark").joinpath("templates/report.html").read_text(encoding="utf-8")
    )
    header = f"<p><span class='tag'>{text(run['status'])}</span> Run: {text(run['id'])}</p>"
    header += f"<p class='muted'>UTC: {text(run['started_at'])} → {text(run['finished_at'])}</p>"
    return template.substitute(
        title=text(run["id"]),
        header=header,
        overview=overview,
        quality=quality,
        execution=execution,
        cases=cases,
        actions=actions,
        method=method,
    )


def generate_html_report(
    config: BenchmarkConfig,
    workspace: Workspace,
    manifest: RunManifest,
    narrator: Narrator | None = None,
) -> Path | None:
    if not config.reporting.enabled:
        return None
    run_dir = workspace.runs / manifest.run_id
    data = collect_report_data(run_dir, manifest)
    narrative = None
    generation: dict[str, Any] = {
        "status": "creating",
        "narrative_status": "disabled",
        "generated_at": datetime.now(UTC).isoformat(),
        "template_version": "html-report-v1",
        "error": None,
        "metadata": {},
    }
    llm = config.reporting.llm
    if llm.enabled and data["cases"]:
        try:
            resolved = llm.resolve(config.evaluation.llm_judge)
            settings = {"config": resolved.model_dump(mode="json", exclude={"api_key_env"})}
            generation["metadata"] = settings
            payload = narrative_input(data, llm)
            workspace.write_run_artifact(manifest.run_id, Path("report-llm-input.json"), payload)
            data["artifacts"].append("report-llm-input.json")
            writer = narrator or LangChainReportNarrator(resolved)
            generation["metadata"] = {
                **settings,
                **writer.metadata,
                "includedCases": payload["included_cases"],
                "omittedCases": payload["omitted_cases"],
            }
            narrative = ReportNarrative.model_validate(writer.generate(payload))
            narrative.validate_evidence(set(payload["evidence_ids"]))
            generation["narrative_status"] = "completed"
        except Exception as exc:
            narrative = None
            generation["narrative_status"] = "failed"
            generation["error"] = str(exc)
    elif llm.enabled:
        generation["narrative_status"] = "skipped"
    data["artifacts"].extend(
        ["report-data.json", "report-narrative.json", "report-generation.json"]
    )
    workspace.write_run_artifact(manifest.run_id, Path("report-data.json"), data)
    workspace.write_run_artifact(
        manifest.run_id,
        Path("report-narrative.json"),
        {
            "status": generation["narrative_status"],
            "error": generation["error"],
            "metadata": generation["metadata"],
            "result": narrative.model_dump() if narrative else None,
        },
    )
    destination = workspace.write_run_text(
        manifest.run_id, Path("report.html"), render_html(data, narrative, generation)
    )
    generation["status"] = "completed"
    workspace.write_run_artifact(manifest.run_id, Path("report-generation.json"), generation)
    return destination
