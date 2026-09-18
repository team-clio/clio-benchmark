import json
from pathlib import Path

from clio_benchmark.config import load_config
from clio_benchmark.errors import ClioApiError
from clio_benchmark.runner import BenchmarkRunner
from clio_benchmark.suite import BenchmarkCase, BenchmarkFile, BugReport, PreparedSuite
from clio_benchmark.workspace import Workspace


class FailingWorkflowClient:
    def create_project(self, **kwargs):
        return {"id": 1}

    def register_repository(self, *args):
        return {"id": 2}

    def wait_for_repository(self, *args, **kwargs):
        return {"id": 2, "syncStatus": "SYNCED"}

    def create_bug(self, *args):
        return {"id": 3}

    def wait_for_bug(self, *args, **kwargs):
        return {"id": 3, "issue_id": 4, "status": "TRIAGED"}

    def wait_for_analysis(self, *args, **kwargs):
        return {"workflowRunId": 5, "issueAnalysis": {"status": "COMPLETED"}}

    def get_workflow(self, *args):
        raise ClioApiError("workflow metadata is temporarily unavailable")


class StaticSuiteRepository:
    def __init__(self, suite: PreparedSuite) -> None:
        self.suite = suite

    def prepare(self, *args) -> PreparedSuite:
        return self.suite


def test_keeps_case_result_when_workflow_metadata_is_unavailable(tmp_path: Path) -> None:
    config = load_config(Path("benchmark.example.yaml"))
    case = BenchmarkCase(
        id="case-1",
        report=BugReport(
            title="title",
            description="description",
            steps_to_reproduce=["step"],
            expected_behavior="expected",
            actual_behavior="actual",
        ),
    )
    prepared = PreparedSuite(
        config=config.suites[0],
        path=tmp_path,
        commit_sha="abc123",
        benchmark=BenchmarkFile(schema_version=1, cases=[case]),
    )
    workspace = Workspace(tmp_path / ".benchmark")
    manifest = workspace.create_run(config)
    runner = BenchmarkRunner(
        config,
        workspace,
        FailingWorkflowClient(),
        StaticSuiteRepository(prepared),
    )

    assert runner.execute(manifest) == 1
    result_path = workspace.runs / manifest.run_id / "cases/feature-flags/case-1/result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert result["analysis"]["issueAnalysis"]["status"] == "COMPLETED"
    assert result["workflow"]["verification_status"] == "unavailable"
    assert "temporarily unavailable" in result["workflow"]["verification_error"]
