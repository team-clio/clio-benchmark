import json
from pathlib import Path

from clio_benchmark.config import SuiteConfig, load_config
from clio_benchmark.errors import ClioApiError, EvaluationError
from clio_benchmark.llm_judge import JudgeDimension, LLMJudgeResult
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


class FakeJudge:
    @property
    def metadata(self) -> dict[str, object]:
        return {"model": "fake-judge", "promptVersion": "test"}

    def evaluate(self, *args, **kwargs) -> LLMJudgeResult:
        dimension = JudgeDimension(score=3, rationale="supported by the fixture")
        return LLMJudgeResult(
            root_cause_accuracy=dimension,
            explanation_quality=dimension,
            solution_validity=dimension,
            evidence_quality=dimension,
        )


class FailingJudge(FakeJudge):
    def evaluate(self, *args, **kwargs) -> LLMJudgeResult:
        raise EvaluationError("judge unavailable")


def test_runner_keeps_running_after_case_failure_and_writes_report(tmp_path: Path) -> None:
    config = load_config(Path("benchmark.example.yaml"))
    suite_config = config.suites[0]
    prepared = PreparedSuite(
        config=suite_config,
        path=tmp_path / "suite",
        commit_sha="abc123",
        cases=CasesFile(schemaVersion=1, cases=[_case("BUG-FAIL"), _case("BUG-OK")]),
        ground_truth=BugsFile(schemaVersion=1, bugs=[_truth("BUG-FAIL"), _truth("BUG-OK")]),
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
    failed_metrics = json.loads((run_dir / "cases/feature-flags/BUG-FAIL/metrics.json").read_text())
    assert failed_metrics["status"] == "infra_error"
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "suites/feature-flags/ground-truth.json").exists()
    assert (run_dir / "suites/feature-flags/cases.json").exists()
    assert (run_dir / "cases/feature-flags/BUG-OK/normalized-result.json").exists()
    evaluation = json.loads((run_dir / "cases/feature-flags/BUG-OK/evaluation.json").read_text())
    assert evaluation["llmJudge"]["status"] == "disabled"
    assert "pending score aggregation" in (run_dir / "report.md").read_text()


def test_runner_persists_structured_llm_judge_result(tmp_path: Path) -> None:
    config = load_config(Path("benchmark.example.yaml"))
    suite_config = config.suites[0]
    suite_path = tmp_path / "suite"
    suite_path.mkdir()
    prepared = PreparedSuite(
        config=suite_config,
        path=suite_path,
        commit_sha="abc123",
        cases=CasesFile(schemaVersion=1, cases=[_case("BUG-OK")]),
        ground_truth=BugsFile(schemaVersion=1, bugs=[_truth("BUG-OK")]),
    )
    workspace = Workspace(tmp_path / ".benchmark")
    manifest = workspace.create_run(config)
    runner = BenchmarkRunner(
        config,
        workspace,
        FakeClient(),  # type: ignore[arg-type]
        FakeSuiteRepository(prepared),  # type: ignore[arg-type]
        FakeJudge(),
    )

    summary = runner.execute(manifest)

    evaluation = json.loads(
        (
            workspace.runs / manifest.run_id / "cases/feature-flags/BUG-OK/evaluation.json"
        ).read_text()
    )
    assert summary.llm_evaluated_cases == 1
    assert evaluation["llmJudge"]["status"] == "completed"
    assert evaluation["llmJudge"]["metadata"]["model"] == "fake-judge"
    assert evaluation["llmJudge"]["result"]["root_cause_accuracy"]["score"] == 3


def test_runner_isolates_llm_judge_failure(tmp_path: Path) -> None:
    config = load_config(Path("benchmark.example.yaml"))
    suite_config = config.suites[0]
    suite_path = tmp_path / "suite"
    suite_path.mkdir()
    prepared = PreparedSuite(
        config=suite_config,
        path=suite_path,
        commit_sha="abc123",
        cases=CasesFile(schemaVersion=1, cases=[_case("BUG-OK")]),
        ground_truth=BugsFile(schemaVersion=1, bugs=[_truth("BUG-OK")]),
    )
    workspace = Workspace(tmp_path / ".benchmark")
    manifest = workspace.create_run(config)
    runner = BenchmarkRunner(
        config,
        workspace,
        FakeClient(),  # type: ignore[arg-type]
        FakeSuiteRepository(prepared),  # type: ignore[arg-type]
        FailingJudge(),
    )

    summary = runner.execute(manifest)

    run_dir = workspace.runs / manifest.run_id
    evaluation = json.loads((run_dir / "cases/feature-flags/BUG-OK/evaluation.json").read_text())
    metrics = json.loads((run_dir / "cases/feature-flags/BUG-OK/metrics.json").read_text())
    assert summary.llm_failed_cases == 1
    assert evaluation["llmJudge"]["status"] == "failed"
    assert metrics["status"] == "evaluation_failed"


def test_runner_isolates_case_projects_and_evaluates_review_outcomes(tmp_path: Path) -> None:
    class ReviewClient(FakeClient):
        def __init__(self) -> None:
            self.projects = []
            self.submitted = []

        def create_project(self, name: str, description: str) -> dict:
            self.projects.append(name)
            return {"id": len(self.projects), "name": name}

        def create_bug(self, project_id: int, case: BenchmarkCase) -> dict:
            self.submitted.append(project_id)
            return {"id": project_id}

        def wait_for_bug(self, *args, **kwargs) -> dict:
            return {"id": 1, "issue_id": None, "status": "TRIAGED"}

        def wait_for_analysis(self, *args, **kwargs) -> dict:
            raise AssertionError("A review outcome has no issue analysis")

    config = load_config(Path("benchmark.example.yaml"))
    suite_config = config.suites[0]
    prepared = PreparedSuite(
        config=suite_config,
        path=tmp_path,
        commit_sha="abc123",
        cases=CasesFile(schemaVersion=1, cases=[_case("REVIEW-1"), _case("REVIEW-2")]),
        ground_truth=BugsFile(schemaVersion=1, bugs=[_truth("REVIEW-1"), _truth("REVIEW-2")]),
    )
    workspace = Workspace(tmp_path / ".benchmark")
    manifest = workspace.create_run(config)
    config.runtime.max_parallel_cases = 1
    client = ReviewClient()
    summary = BenchmarkRunner(
        config, workspace, client, FakeSuiteRepository(prepared), FakeJudge()
    ).execute(manifest)
    assert client.submitted == [1, 2]
    assert len(set(client.projects)) == 2
    assert summary.completed_cases == 2
    assert summary.detected_cases == 0
    assert summary.llm_evaluated_cases == 2


def test_runner_bounds_parallelism_and_isolates_setup_failure(tmp_path: Path) -> None:
    from threading import Barrier, Lock

    class ParallelClient(FakeClient):
        def __init__(self):
            self.barrier = Barrier(2)
            self.lock = Lock()
            self.active = 0
            self.peak = 0
            self.next_id = 0

        def create_project(self, name, description):
            with self.lock:
                self.next_id += 1
                project_id = self.next_id
            return {"id": project_id, "name": name}

        def wait_for_repository(self, *args, **kwargs):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                self.barrier.wait(timeout=10)
                if args[0] == 1:
                    raise ClioApiError("sync failed")
                return {"id": 2, "syncStatus": "SYNCED"}
            finally:
                with self.lock:
                    self.active -= 1

    config = load_config(Path("benchmark.example.yaml"))
    config.runtime.max_parallel_cases = 2
    cases = [_case(f"CASE-{i}") for i in range(4)]
    prepared = PreparedSuite(
        config=config.suites[0], path=tmp_path, commit_sha="abc123",
        cases=CasesFile(schemaVersion=1, cases=cases),
        ground_truth=BugsFile(schemaVersion=1, bugs=[_truth(c.id) for c in cases]),
    )
    workspace = Workspace(tmp_path / ".benchmark")
    manifest = workspace.create_run(config)
    client = ParallelClient()
    summary = BenchmarkRunner(
        config, workspace, client, FakeSuiteRepository(prepared)
    ).execute(manifest)
    assert client.peak == 2
    assert summary.total_cases == 4
    assert summary.completed_cases == 3
    assert summary.failed_cases == 1
    run = workspace.runs / manifest.run_id
    for case in cases:
        assert (run / "cases" / config.suites[0].name / case.id / "metrics.json").exists()
    metadata = json.loads((run / "suites" / config.suites[0].name / "metadata.json").read_text())
    assert metadata["commit_sha"] == "abc123"
    assert "project" not in metadata


def test_parallel_case_limit_requires_positive_integer():
    import pytest
    from pydantic import ValidationError

    from clio_benchmark.config import RuntimeConfig

    assert RuntimeConfig().max_parallel_cases == 1
    for value in (0, -1, 1.5, True):
        with pytest.raises(ValidationError):
            RuntimeConfig(max_parallel_cases=value)
