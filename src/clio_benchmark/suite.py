"""Benchmark suite checkout, input cases, and isolated ground-truth contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import AliasChoices, Field, ValidationError, model_validator

from clio_benchmark.config import StrictModel, SuiteConfig
from clio_benchmark.errors import SuiteError


class BugReport(StrictModel):
    """User-visible report submitted to Clio. It must not contain oracle data."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    steps_to_reproduce: list[str] = Field(
        min_length=1, validation_alias=AliasChoices("steps_to_reproduce", "stepsToReproduce")
    )
    expected_behavior: str = Field(
        min_length=1, validation_alias=AliasChoices("expected_behavior", "expectedBehavior")
    )
    actual_behavior: str = Field(
        min_length=1, validation_alias=AliasChoices("actual_behavior", "actualBehavior")
    )
    reproduction_command: str | None = Field(
        default=None,
        validation_alias=AliasChoices("reproduction_command", "reproductionCommand"),
    )

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


class CasesFile(StrictModel):
    schema_version: Literal[1] = Field(
        validation_alias=AliasChoices("schema_version", "schemaVersion")
    )
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_must_be_unique(self) -> CasesFile:
        _ensure_unique([case.id for case in self.cases], "case")
        return self


class SourceLocation(StrictModel):
    file: str = Field(min_length=1)
    lines: tuple[int, int]

    @model_validator(mode="after")
    def line_range_must_be_valid(self) -> SourceLocation:
        start, end = self.lines
        if start <= 0 or end < start:
            raise ValueError("location lines must be a positive [start, end] range")
        return self


class GroundTruth(StrictModel):
    """Private oracle data used only by the benchmark evaluator."""

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    description: str = Field(min_length=1)
    location: SourceLocation
    root_cause: str = Field(
        min_length=1, validation_alias=AliasChoices("root_cause", "rootCause")
    )
    category: str | None = None
    severity: str | None = None
    location_tolerance: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("location_tolerance", "locationTolerance"),
    )
    required_concepts: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("required_concepts", "requiredConcepts"),
    )


class BugsFile(StrictModel):
    schema_version: Literal[1] = Field(
        validation_alias=AliasChoices("schema_version", "schemaVersion")
    )
    bugs: list[GroundTruth] = Field(min_length=1)

    @model_validator(mode="after")
    def bug_ids_must_be_unique(self) -> BugsFile:
        _ensure_unique([bug.id for bug in self.bugs], "bug")
        return self


class PreparedSuite(StrictModel):
    config: SuiteConfig
    path: Path
    commit_sha: str
    cases: CasesFile
    ground_truth: BugsFile

    @model_validator(mode="after")
    def case_and_ground_truth_ids_must_match(self) -> PreparedSuite:
        case_ids = {case.id for case in self.cases.cases}
        truth_ids = {bug.id for bug in self.ground_truth.bugs}
        if case_ids != truth_ids:
            raise ValueError(
                "cases.json and bugs.json ids must match; "
                f"missing ground truth={sorted(case_ids - truth_ids)}, "
                f"missing cases={sorted(truth_ids - case_ids)}"
            )
        return self

    def truth_for(self, case_id: str) -> GroundTruth:
        return next(bug for bug in self.ground_truth.bugs if bug.id == case_id)


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
        try:
            return PreparedSuite(
                config=config,
                path=destination,
                commit_sha=commit_sha,
                cases=load_cases_file(destination / "cases.json"),
                ground_truth=load_bugs_file(destination / "bugs.json"),
            )
        except ValidationError as exc:
            raise SuiteError(f"Invalid suite contract at {destination}: {exc}") from exc

    @staticmethod
    def _run(*command: str, cwd: Path | None = None) -> str:
        try:
            completed = subprocess.run(
                command, cwd=cwd, check=True, capture_output=True, text=True
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = (
                exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            )
            raise SuiteError(f"Command failed ({' '.join(command)}): {detail}") from exc
        return completed.stdout


ModelT = TypeVar("ModelT", CasesFile, BugsFile)


def load_cases_file(path: Path) -> CasesFile:
    return _load_json_model(path, CasesFile, "cases.json")


def load_bugs_file(path: Path) -> BugsFile:
    return _load_json_model(path, BugsFile, "bugs.json")


def _load_json_model(path: Path, model: type[ModelT], name: str) -> ModelT:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuiteError(f"{name} not found: {path}") from exc
    except ValidationError as exc:
        raise SuiteError(f"Invalid {name} at {path}: {exc}") from exc


def _ensure_unique(ids: list[str], label: str) -> None:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} ids must be unique")
