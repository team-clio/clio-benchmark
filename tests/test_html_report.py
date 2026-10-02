import json
from pathlib import Path

import pytest

from clio_benchmark.config import BenchmarkConfig, LLMJudgeConfig, ReportLLMConfig, load_config
from clio_benchmark.html_report import case_anchor, generate_html_report
from clio_benchmark.manifest import RunStatus
from clio_benchmark.report_data import collect_report_data, duration_stats
from clio_benchmark.report_narrative import (
    LangChainReportNarrator,
    ReportNarrative,
    narrative_input,
)
from clio_benchmark.workspace import Workspace


def config() -> BenchmarkConfig:
    value = load_config(Path("benchmark.example.yaml"))
    value.reporting.llm.enabled = False
    return value


def make_run(tmp_path):
    settings = config()
    workspace = Workspace(tmp_path)
    manifest = workspace.create_run(settings)
    manifest.transition(RunStatus.COMPLETED_WITH_ERRORS)
    workspace.save_manifest(manifest)
    return settings, workspace, manifest


def save_case(workspace, manifest, case_id, status, judge_status="disabled", score=3):
    prefix = Path("cases/feature-flags") / case_id
    workspace.write_run_artifact(
        manifest.run_id,
        prefix / "input.json",
        {
            "id": case_id,
            "report": {
                "title": "<script>alert('x')</script>",
                "description": "증상",
                "steps_to_reproduce": ["실행"],
                "expected_behavior": "정상",
                "actual_behavior": "오류",
            },
        },
    )
    workspace.write_run_artifact(
        manifest.run_id,
        prefix / "metrics.json",
        {"case_id": case_id, "status": status, "duration_seconds": 10},
    )
    if status in {"completed", "evaluation_failed"}:
        workspace.write_run_artifact(
            manifest.run_id,
            prefix / "evaluation.json",
            {
                "deterministic": {"detected": True, "locationMatches": False},
                "llmJudge": {
                    "status": judge_status,
                    "result": {
                        key: {"score": score, "rationale": "근거"}
                        for key in [
                            "root_cause_accuracy",
                            "explanation_quality",
                            "solution_validity",
                            "evidence_quality",
                        ]
                    },
                },
            },
        )


def test_judge_failure_is_not_zero_score_and_missing_evaluation_is_not_a_mismatch(tmp_path):
    _, workspace, manifest = make_run(tmp_path)
    save_case(workspace, manifest, "A", "completed", "completed", 4)
    save_case(workspace, manifest, "B", "evaluation_failed", "failed")
    save_case(workspace, manifest, "C", "timeout")
    data = collect_report_data(workspace.runs / manifest.run_id, manifest)
    assert data["summary"]["processed_cases"] == 3
    assert data["summary"]["evaluated_cases"] == 2
    assert data["summary"]["detected_cases"] == 2
    assert data["summary"]["judge_scores"]["root_cause_accuracy"] == {"mean": 4, "count": 1}
    assert data["summary"]["status_counts"]["evaluation_failed"] == 1


def test_html_escapes_case_and_llm_text_and_preserves_execution_status(tmp_path):
    settings, workspace, manifest = make_run(tmp_path)
    save_case(workspace, manifest, "A", "completed")
    settings.reporting.llm.enabled = True

    class Writer:
        metadata = {"model": "fake"}

        def generate(self, payload):
            assert payload["summary"]["evaluated_cases"] == 1
            return ReportNarrative(
                summary=[{"text": "<script>LLM</script>", "evidence": ["feature-flags/A"]}],
                quality_analysis=[],
                findings=[],
                recommendations=[],
            )

    path = generate_html_report(settings, workspace, manifest, Writer())
    html = path.read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert f"href='#{case_anchor('feature-flags/A')}'" in html
    assert f"id='{case_anchor('feature-flags/A')}'" in html
    assert "completed_with_errors" in html
    assert workspace.load_manifest(manifest.run_id).status is RunStatus.COMPLETED_WITH_ERRORS
    generation = json.loads((path.parent / "report-generation.json").read_text())
    assert generation["narrative_status"] == "completed"
    assert (path.parent / "report-llm-input.json").exists()


@pytest.mark.parametrize("failure", ["network", "invalid-evidence"])
def test_llm_failure_still_generates_numeric_report(tmp_path, failure):
    settings, workspace, manifest = make_run(tmp_path)
    save_case(workspace, manifest, "A", "completed")
    settings.reporting.llm.enabled = True

    class Writer:
        metadata = {}

        def generate(self, payload):
            if failure == "network":
                raise RuntimeError("provider unavailable")
            return ReportNarrative(
                summary=[{"text": "주장", "evidence": ["missing/case"]}],
                quality_analysis=[],
                findings=[],
                recommendations=[],
            )

    path = generate_html_report(settings, workspace, manifest, Writer())
    html = path.read_text()
    assert "LLM 서술 생성 실패" in html
    assert "1 / 1 (100.0%)" in html
    saved = json.loads((path.parent / "report-narrative.json").read_text())
    assert saved["status"] == "failed"
    assert saved["result"] is None


def test_resolves_judge_defaults_and_does_not_inherit_wrong_provider_endpoint():
    judge = LLMJudgeConfig(
        enabled=False,
        provider="deepseek",
        model="custom-model",
        api_key_env="CUSTOM_KEY",
        base_url="https://gateway.example.com/v1",
    )
    resolved = ReportLLMConfig().resolve(judge)
    assert resolved.enabled is True
    assert resolved.model == "custom-model"
    assert resolved.api_key_env == "CUSTOM_KEY"
    assert resolved.prompt_version == "report-v1"
    changed = ReportLLMConfig(provider="openai").resolve(judge)
    assert changed.model is None and changed.api_key_env is None and changed.base_url is None
    overridden = ReportLLMConfig(model="report-model", temperature=0.5).resolve(judge)
    assert overridden.model == "report-model" and overridden.temperature == 0.5


def test_saved_truth_survives_checkout_change_and_planned_case_is_not_run(tmp_path):
    settings, workspace, manifest = make_run(tmp_path)
    suite = Path("suites/feature-flags")
    workspace.write_run_artifact(
        manifest.run_id, suite / "cases.json", {"cases": [{"id": "A", "report": {"title": "예정"}}]}
    )
    workspace.write_run_artifact(
        manifest.run_id,
        suite / "ground-truth.json",
        {"bugs": [{"id": "A", "root_cause": "실행 당시 원인"}]},
    )
    changed = workspace.suites / "feature-flags"
    changed.mkdir(parents=True)
    (changed / "bugs.json").write_text('{"bugs": [{"id": "A", "root_cause": "변경"}]}')
    path = generate_html_report(settings, workspace, manifest)
    html = path.read_text()
    assert "실행 당시 원인" in html and "변경" not in html
    data = json.loads((path.parent / "report-data.json").read_text())
    assert data["planned_cases"] == 1
    assert data["summary"]["processed_cases"] == 0
    assert data["cases"][0]["status"] == "not_run"


def test_partial_tool_logs_and_corrupt_case_file_remain_visible(tmp_path):
    settings, workspace, manifest = make_run(tmp_path)
    save_case(workspace, manifest, "A", "completed")
    run = workspace.runs / manifest.run_id
    (run / "cases/feature-flags/A/evaluation.json").write_text("not json")
    (run / "tool-calls.jsonl").write_text(
        '{"tool":"search","status":"running"}\nnot json\n'
        '{"tool":"search","status":"failure","duration_seconds":2}\n'
    )
    workspace.write_run_artifact(
        manifest.run_id,
        Path("tool-call-collection.json"),
        {"status": "failed", "partial": True, "error": "incomplete range"},
    )
    manifest.tool_log_status = "failed"
    path = generate_html_report(settings, workspace, manifest)
    html = path.read_text()
    assert "incomplete range" in html
    assert "자료를 읽지 못했습니다" in html
    data = json.loads((path.parent / "report-data.json").read_text())
    assert data["tools"][0]["running"] == 1
    assert data["tools"][0]["failures"] == 1
    assert data["summary"]["evaluated_cases"] == 0


def test_empty_run_has_no_fake_zero_percent_and_does_not_call_llm(tmp_path):
    settings, workspace, manifest = make_run(tmp_path)
    settings.reporting.llm.enabled = True

    class Writer:
        def generate(self, payload):
            pytest.fail("empty run must not call LLM")

    path = generate_html_report(settings, workspace, manifest, Writer())
    html = path.read_text()
    assert "0 / 0 (—)" in html
    assert "사례가 없어 LLM 서술 생략" in html


def test_llm_input_budget_excludes_environment_and_tool_arguments(tmp_path):
    _, workspace, manifest = make_run(tmp_path)
    for index in range(12):
        save_case(workspace, manifest, str(index), "completed")
    manifest.config["environment"] = {"agent": {"TOKEN": "never-send"}}
    data = collect_report_data(workspace.runs / manifest.run_id, manifest)
    payload = narrative_input(data, ReportLLMConfig(max_input_chars=4000, max_case_chars=500))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert len(serialized) <= 4000
    assert payload["omitted_cases"] > 0
    assert "never-send" not in json.dumps(data)
    assert len(payload["cases"]) == payload["included_cases"]


def test_percentile_definition_and_missing_values():
    assert duration_stats([])["median"] is None
    assert duration_stats([10, 20])["p90"] == 19


def test_langchain_narrator_uses_resolved_provider_and_structured_output(monkeypatch):
    import clio_benchmark.report_narrative as module

    seen = {}

    class Model:
        def __init__(self, **kwargs):
            seen["client"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            seen["schema"] = schema
            seen["structured"] = kwargs
            return self

        def invoke(self, messages):
            seen["messages"] = messages
            return {
                "summary": [{"text": "완료", "evidence": ["run:summary"]}],
                "quality_analysis": [],
                "findings": [],
                "recommendations": [],
            }

    monkeypatch.setenv("TEST_REPORT_KEY", "test-only-key")
    monkeypatch.setattr(module, "ChatOpenAI", Model)
    writer = LangChainReportNarrator(
        LLMJudgeConfig(provider="deepseek", api_key_env="TEST_REPORT_KEY")
    )
    result = writer.generate({"run": "fixture"})
    assert result.summary[0].text == "완료"
    assert seen["client"]["base_url"] == "https://api.deepseek.com"
    assert seen["structured"] == {"method": "json_mode"}
    assert seen["schema"] is ReportNarrative
    assert "채점자가 아니다" in seen["messages"][0].content
    assert "test-only-key" not in json.dumps(writer.metadata)


def test_cli_report_missing_key_is_a_visible_fallback(monkeypatch, tmp_path):
    settings, workspace, manifest = make_run(tmp_path)
    save_case(workspace, manifest, "A", "completed")
    settings.reporting.llm.enabled = True
    settings.reporting.llm.api_key_env = "REPORT_NONEXISTENT_TEST_KEY"
    monkeypatch.delenv("REPORT_NONEXISTENT_TEST_KEY", raising=False)
    path = generate_html_report(settings, workspace, manifest)
    assert "LLM 키 환경 변수가 없습니다" in path.read_text()
    assert json.loads((path.parent / "report-generation.json").read_text())["status"] == "completed"


def test_malformed_evaluation_is_missing_not_an_incorrect_answer(tmp_path):
    settings, workspace, manifest = make_run(tmp_path)
    save_case(workspace, manifest, "A", "completed")
    workspace.write_run_artifact(
        manifest.run_id,
        Path("cases/feature-flags/A/evaluation.json"),
        {"deterministic": {}, "llmJudge": {"status": "completed", "result": {}}},
    )
    path = generate_html_report(settings, workspace, manifest)
    data = json.loads((path.parent / "report-data.json").read_text())
    assert data["summary"]["evaluated_cases"] == 0
    assert data["summary"]["judge_scores"]["root_cause_accuracy"]["mean"] is None
    assert "결정적 평가가 유효하지 않아" in path.read_text()


def test_interrupted_submission_does_not_count_as_finalized_case(tmp_path):
    settings, workspace, manifest = make_run(tmp_path)
    workspace.write_run_artifact(
        manifest.run_id,
        Path("cases/feature-flags/A/input.json"),
        {"id": "A", "report": {"title": "제출 후 취소"}},
    )
    manifest.transition(RunStatus.CANCELLED)
    path = generate_html_report(settings, workspace, manifest)
    data = json.loads((path.parent / "report-data.json").read_text())
    assert data["cases"][0]["status"] == "interrupted"
    assert data["summary"]["processed_cases"] == 0
    assert "cancelled" in path.read_text()
