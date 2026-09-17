"""Private benchmark answers kept outside repositories visible to Clio."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from clio_benchmark.config import StrictModel
from clio_benchmark.errors import BenchmarkError


class VerdictOracle(StrictModel):
    expected_bug_status: str | None = None
    expected_analysis_status: str


class RootCauseOracle(StrictModel):
    required_concepts: list[list[str]] = Field(min_length=1)


class CodeLocationOracle(StrictModel):
    path: str = Field(min_length=1)
    symbols: list[str] = Field(default_factory=list)


class EvidenceOracle(StrictModel):
    required_paths: list[str] = Field(default_factory=list)
    minimum_citations: int = Field(default=1, ge=0)


class ReproductionOracle(StrictModel):
    mode: Literal["plan", "executed"] = "plan"
    required_concepts: list[list[str]] = Field(default_factory=list)


class UncertaintyOracle(StrictModel):
    expected_analysis_status: str
    minimum_confidence: float | None = Field(default=None, ge=0, le=1)
    maximum_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def confidence_range_is_valid(self) -> UncertaintyOracle:
        if (
            self.minimum_confidence is not None
            and self.maximum_confidence is not None
            and self.minimum_confidence > self.maximum_confidence
        ):
            raise ValueError("minimum_confidence must not exceed maximum_confidence")
        return self


class CaseOracle(StrictModel):
    id: str = Field(min_length=1)
    verdict: VerdictOracle
    root_cause: RootCauseOracle
    code_locations: list[CodeLocationOracle] = Field(min_length=1)
    evidence: EvidenceOracle = Field(default_factory=EvidenceOracle)
    reproduction: ReproductionOracle = Field(default_factory=ReproductionOracle)
    uncertainty: UncertaintyOracle


class OracleFile(StrictModel):
    schema_version: Literal[1]
    cases: list[CaseOracle] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> OracleFile:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("oracle case ids must be unique")
        return self


def load_oracle(path: Path) -> OracleFile:
    try:
        return OracleFile.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"Oracle not found: {path}") from exc
    except ValidationError as exc:
        raise BenchmarkError(f"Invalid oracle at {path}: {exc}") from exc
