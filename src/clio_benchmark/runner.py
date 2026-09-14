"""Single-process benchmark execution pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clio_benchmark.clio_client import ClioClient
from clio_benchmark.config import BenchmarkConfig
from clio_benchmark.manifest import RunManifest
from clio_benchmark.suite import PreparedSuite, SuiteRepository
from clio_benchmark.workspace import Workspace


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

    def execute(self, manifest: RunManifest) -> int:
        completed_cases = 0
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

            for case in prepared.benchmark.cases:
                bug = self._client.create_bug(project_id, case)
                completed_bug = self._client.wait_for_bug(
                    project_id,
                    int(bug["id"]),
                    timeout_seconds=self._config.runtime.case_timeout_seconds,
                    poll_interval_seconds=self._config.runtime.poll_interval_seconds,
                )
                issue_id = completed_bug.get("issue_id")
                analysis = None
                if issue_id is not None:
                    analysis = self._client.wait_for_analysis(
                        project_id,
                        int(issue_id),
                        timeout_seconds=self._config.runtime.case_timeout_seconds,
                        poll_interval_seconds=self._config.runtime.poll_interval_seconds,
                    )
                self._write_case_result(
                    manifest, prepared, case.model_dump(mode="json"), completed_bug, analysis
                )
                completed_cases += 1
        return completed_cases

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

    def _write_case_result(
        self,
        manifest: RunManifest,
        suite: PreparedSuite,
        case: dict[str, Any],
        bug: dict[str, Any],
        analysis: dict[str, Any] | None,
    ) -> None:
        self._workspace.write_run_artifact(
            manifest.run_id,
            Path("cases") / suite.config.name / str(case["id"]) / "result.json",
            {"input": case, "bug": bug, "analysis": analysis},
        )
