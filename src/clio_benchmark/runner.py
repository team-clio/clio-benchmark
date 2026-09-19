"""Single-process benchmark execution and evaluation pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clio_benchmark.clio_client import ClioClient
from clio_benchmark.config import BenchmarkConfig
from clio_benchmark.errors import BenchmarkError, BenchmarkTimeout, ClioAnalysisError
from clio_benchmark.evaluation import DeterministicEvaluation, evaluate_deterministic
from clio_benchmark.manifest import RunManifest
from clio_benchmark.reporter import render_markdown_report
from clio_benchmark.result import (
    CaseExecutionResult,
    CaseStatus,
    normalize_clio_result,
)
from clio_benchmark.suite import BenchmarkCase, PreparedSuite, SuiteRepository
from clio_benchmark.workspace import Workspace


@dataclass(frozen=True)
class ExecutionSummary:
    total_cases: int
    completed_cases: int
    failed_cases: int
    detected_cases: int
    location_matches: int


class BenchmarkRunner:
    def __init__(
        self,
        config: BenchmarkConfig,
        workspace: Workspace,
        client: ClioClient,
        suite_repository: SuiteRepository | None = None,
    ) -> None:
        self._config = config
        self._workspace = workspace
        self._client = client
        self._suite_repository = suite_repository or SuiteRepository()

    def execute(self, manifest: RunManifest) -> ExecutionSummary:
        results: list[CaseExecutionResult] = []
        detected_cases = 0
        location_matches = 0

        for suite_config in self._config.suites:
            prepared = self._suite_repository.prepare(
                suite_config, self._workspace.suites / suite_config.name
            )
            project = self._client.create_project(
                name=f"benchmark-{manifest.run_id}-{suite_config.name}"[:120],
                description=f"Clio Benchmark run {manifest.run_id}",
            )
            project_id = int(project["id"])
            repository = self._client.register_repository(
                project_id, str(suite_config.repository), suite_config.revision
            )
            synced_repository = self._client.wait_for_repository(
                project_id,
                int(repository["id"]),
                timeout_seconds=self._config.runtime.startup_timeout_seconds,
                poll_interval_seconds=self._config.runtime.poll_interval_seconds,
            )
            self._write_suite_metadata(manifest, prepared, project, synced_repository)

            for case in prepared.cases.cases:
                result, detected, location_match = self._execute_case(
                    manifest, prepared, project_id, case
                )
                results.append(result)
                detected_cases += int(detected)
                location_matches += int(location_match)

        completed = sum(result.status is CaseStatus.COMPLETED for result in results)
        summary = ExecutionSummary(
            total_cases=len(results),
            completed_cases=completed,
            failed_cases=len(results) - completed,
            detected_cases=detected_cases,
            location_matches=location_matches,
        )
        self._workspace.write_run_artifact(
            manifest.run_id,
            Path("summary.json"),
            {
                "totalCases": summary.total_cases,
                "completedCases": summary.completed_cases,
                "failedCases": summary.failed_cases,
                "detectedCases": summary.detected_cases,
                "locationMatches": summary.location_matches,
                "qualityScore": None,
                "qualityScoreStatus": "pending_llm_evaluation",
            },
        )
        self._workspace.write_run_text(
            manifest.run_id,
            Path("report.md"),
            render_markdown_report(manifest.run_id, summary),
        )
        return summary

    def _execute_case(
        self,
        manifest: RunManifest,
        suite: PreparedSuite,
        project_id: int,
        case: BenchmarkCase,
    ) -> tuple[CaseExecutionResult, bool, bool]:
        started = time.monotonic()
        case_path = Path("cases") / suite.config.name / case.id
        self._workspace.write_run_artifact(
            manifest.run_id, case_path / "input.json", case.model_dump(mode="json")
        )

        try:
            bug = self._client.create_bug(project_id, case)
            completed_bug = self._client.wait_for_bug(
                project_id,
                int(bug["id"]),
                timeout_seconds=self._config.runtime.case_timeout_seconds,
                poll_interval_seconds=self._config.runtime.poll_interval_seconds,
            )
            issue_id = completed_bug.get("issue_id")
            if issue_id is None:
                raise ClioAnalysisError(
                    f"Clio completed bug {completed_bug.get('id')} without an issue id"
                )
            analysis = self._client.wait_for_analysis(
                project_id,
                int(issue_id),
                timeout_seconds=self._config.runtime.case_timeout_seconds,
                poll_interval_seconds=self._config.runtime.poll_interval_seconds,
            )

            raw_result = {"bug": completed_bug, "analysis": analysis}
            normalized = normalize_clio_result(raw_result)
            evaluation = evaluate_deterministic(normalized, suite.truth_for(case.id))
            duration = time.monotonic() - started
            execution = CaseExecutionResult(
                case_id=case.id,
                status=CaseStatus.COMPLETED,
                duration_seconds=duration,
                normalized=normalized,
            )
            self._write_success_artifacts(
                manifest, case_path, raw_result, execution, evaluation
            )
            return execution, evaluation.detected, evaluation.location_matches
        except BenchmarkTimeout as exc:
            execution = self._write_failure_artifacts(
                manifest, case_path, case.id, CaseStatus.TIMEOUT, exc, started
            )
        except ClioAnalysisError as exc:
            execution = self._write_failure_artifacts(
                manifest, case_path, case.id, CaseStatus.CLIO_FAILED, exc, started
            )
        except BenchmarkError as exc:
            execution = self._write_failure_artifacts(
                manifest, case_path, case.id, CaseStatus.INFRA_ERROR, exc, started
            )
        return execution, False, False

    def _write_success_artifacts(
        self,
        manifest: RunManifest,
        case_path: Path,
        raw_result: dict[str, Any],
        execution: CaseExecutionResult,
        evaluation: DeterministicEvaluation,
    ) -> None:
        self._workspace.write_run_artifact(
            manifest.run_id, case_path / "clio-result.json", raw_result
        )
        self._workspace.write_run_artifact(
            manifest.run_id,
            case_path / "evaluation.json",
            {
                "deterministic": {
                    "detected": evaluation.detected,
                    "locationMatches": evaluation.location_matches,
                    "matchedLocation": evaluation.matched_location,
                },
                "llmJudge": {"status": "pending"},
            },
        )
        self._workspace.write_run_artifact(
            manifest.run_id,
            case_path / "metrics.json",
            execution.model_dump(mode="json", exclude={"normalized"}),
        )

    def _write_failure_artifacts(
        self,
        manifest: RunManifest,
        case_path: Path,
        case_id: str,
        status: CaseStatus,
        error: Exception,
        started: float,
    ) -> CaseExecutionResult:
        execution = CaseExecutionResult(
            case_id=case_id,
            status=status,
            duration_seconds=time.monotonic() - started,
            error=str(error),
        )
        self._workspace.write_run_artifact(
            manifest.run_id,
            case_path / "metrics.json",
            execution.model_dump(mode="json"),
        )
        return execution

    def _write_suite_metadata(
        self,
        manifest: RunManifest,
        suite: PreparedSuite,
        project: dict[str, Any],
        repository: dict[str, Any],
    ) -> None:
        self._workspace.write_run_artifact(
            manifest.run_id,
            Path("suites") / suite.config.name / "metadata.json",
            {
                "suite": suite.config.name,
                "repository": str(suite.config.repository),
                "commit_sha": suite.commit_sha,
                "project": project,
                "clio_repository": repository,
            },
        )
