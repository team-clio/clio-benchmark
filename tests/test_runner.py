import json
from pathlib import Path

from clio_benchmark.config import SuiteConfig, load_config
from clio_benchmark.errors import ClioApiError
from clio_benchmark.runner import BenchmarkRunner
from clio_benchmark.suite import (
    BenchmarkCase,
    BugReport,
    BugsFile,
    CasesFile,
    GroundTruth,
    PreparedSuite,
    SourceLocation,
)
from clio_benchmark.workspace import Workspace


def _case(case_id: str) -> BenchmarkCase:
    return BenchmarkCase(
        id=case_id,
        report=BugReport(
            title="title",
            description="description",
            stepsToReproduce=["step"],
            expectedBehavior="expected",
            actualBehavior="actual",
        ),
    )


def _truth(case_id: str) -> GroundTruth:
    return GroundTruth(
        id=case_id,
        description="bug",
        location=SourceLocation(file="src/service.py", lines=(10, 12)),
        rootCause="cause",
    )


class FakeSuiteRepository:
    def __init__(self, prepared: PreparedSuite) -> None:
        self.prepared = prepared

    def prepare(self, config: SuiteConfig, destination: Path) -> PreparedSuite:
        return self.prepared


class FakeClient:
    def create_project(self, name: str, description: str) -> dict:
        return {"id": 1, "name": name}

    def register_repository(self, project_id: int, repository_url: str, revision: str) -> dict:
        return {"id": 2}

    def wait_for_repository(self, *args, **kwargs) -> dict:
        return {"id": 2, "syncStatus": "SYNCED"}

    def create_bug(self, project_id: int, case: BenchmarkCase) -> dict:
        if case.id == "BUG-FAIL":
            raise ClioApiError("temporary server error")
        return {"id": 3}

    def wait_for_bug(self, *args, **kwargs) -> dict:
        return {"id": 3, "issue_id": 4, "status": "TRIAGED"}

    def wait_for_analysis(self, *args, **kwargs) -> dict:
        return {
            "detected": True,
            "rootCause": "cause",
            "locations": [{"file": "src/service.py", "startLine": 11, "endLine": 11}],
        }


def test_runner_keeps_running_after_case_failure_and_writes_report(tmp_path: Path) -> None:
    config = load_config(Path("benchmark.example.yaml"))
    suite_config = config.suites[0]
    prepared = PreparedSuite(
        config=suite_config,
        path=tmp_path / "suite",
        commit_sha="abc123",
        cases=CasesFile(schemaVersion=1, cases=[_case("BUG-FAIL"), _case("BUG-OK")]),
        ground_truth=BugsFile(
            schemaVersion=1, bugs=[_truth("BUG-FAIL"), _truth("BUG-OK")]
        ),
    )
    workspace = Workspace(tmp_path / ".benchmark")
    manifest = workspace.create_run(config)
    runner = BenchmarkRunner(
        config,
        workspace,
        FakeClient(),  # type: ignore[arg-type]
        FakeSuiteRepository(prepared),  # type: ignore[arg-type]
    )

    summary = runner.execute(manifest)

    assert summary.total_cases == 2
    assert summary.completed_cases == 1
    assert summary.failed_cases == 1
    assert summary.location_matches == 1
    run_dir = workspace.runs / manifest.run_id
    assert (run_dir / "cases/feature-flags/BUG-OK/evaluation.json").exists()
    failed_metrics = json.loads(
        (run_dir / "cases/feature-flags/BUG-FAIL/metrics.json").read_text()
    )
    assert failed_metrics["status"] == "infra_error"
    assert (run_dir / "summary.json").exists()
    assert "pending LLM Judge" in (run_dir / "report.md").read_text()
