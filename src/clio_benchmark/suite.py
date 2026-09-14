"""Benchmark suite checkout and bug report contract."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from clio_benchmark.config import StrictModel, SuiteConfig
from clio_benchmark.errors import SuiteError


class BugReport(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    steps_to_reproduce: list[str] = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    actual_behavior: str = Field(min_length=1)
    reproduction_command: str | None = None

    def as_bug_description(self) -> str:
        steps = "\n".join(
            f"{index}. {step}" for index, step in enumerate(self.steps_to_reproduce, start=1)
        )
        return (
            f"{self.description}\n\n"
            f"재현 절차:\n{steps}\n\n"
            f"기대 동작: {self.expected_behavior}\n"
            f"실제 동작: {self.actual_behavior}"
        )


class BenchmarkCase(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    report: BugReport


class BenchmarkFile(StrictModel):
    schema_version: Literal[1]
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_must_be_unique(self) -> BenchmarkFile:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case ids must be unique")
        return self


class PreparedSuite(StrictModel):
    config: SuiteConfig
    path: Path
    commit_sha: str
    benchmark: BenchmarkFile


class SuiteRepository:
    def prepare(self, config: SuiteConfig, destination: Path) -> PreparedSuite:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not (destination / ".git").is_dir():
            raise SuiteError(f"Suite path exists but is not a git repository: {destination}")

        if not destination.exists():
            self._run("git", "clone", str(config.repository), str(destination))
        else:
            self._run("git", "remote", "set-url", "origin", str(config.repository), cwd=destination)

        self._run("git", "fetch", "--prune", "origin", config.revision, cwd=destination)
        self._run("git", "checkout", "--detach", "FETCH_HEAD", cwd=destination)
        commit_sha = self._run("git", "rev-parse", "HEAD", cwd=destination).strip()
        return PreparedSuite(
            config=config,
            path=destination,
            commit_sha=commit_sha,
            benchmark=load_benchmark_file(destination / "benchmark.json"),
        )

    @staticmethod
    def _run(*command: str, cwd: Path | None = None) -> str:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = (
                exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            )
            raise SuiteError(f"Command failed ({' '.join(command)}): {detail}") from exc
        return completed.stdout


def load_benchmark_file(path: Path) -> BenchmarkFile:
    try:
        return BenchmarkFile.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuiteError(f"benchmark.json not found: {path}") from exc
    except ValidationError as exc:
        raise SuiteError(f"Invalid benchmark.json at {path}: {exc}") from exc
