"""Typed benchmark configuration and safe serialization helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, ValidationError

from clio_benchmark.errors import ConfigurationError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepositoryConfig(StrictModel):
    repository: HttpUrl
    revision: str = Field(min_length=1)


class ClioConfig(StrictModel):
    agent: RepositoryConfig
    server: RepositoryConfig


class RuntimeConfig(StrictModel):
    startup_timeout_seconds: int = Field(default=300, gt=0)
    case_timeout_seconds: int = Field(default=1800, gt=0)
    poll_interval_seconds: float = Field(default=5, gt=0)


class EvaluationWeights(StrictModel):
    verdict: float = Field(default=20, ge=0)
    root_cause: float = Field(default=35, ge=0)
    code_location: float = Field(default=15, ge=0)
    evidence_quality: float = Field(default=15, ge=0)
    reproduction: float = Field(default=10, ge=0)
    uncertainty: float = Field(default=5, ge=0)

    def as_dict(self) -> dict[str, float]:
        return {name: float(value) for name, value in self.model_dump().items()}


class EvaluationConfig(StrictModel):
    pass_threshold: float = Field(default=70, ge=0, le=100)
    weights: EvaluationWeights = Field(default_factory=EvaluationWeights)


class ServiceValues(StrictModel):
    agent: dict[str, str] = Field(default_factory=dict)
    server: dict[str, str] = Field(default_factory=dict)


class ServiceSecrets(StrictModel):
    agent: dict[str, SecretStr] = Field(default_factory=dict)
    server: dict[str, SecretStr] = Field(default_factory=dict)


class SuiteConfig(StrictModel):
    name: str = Field(min_length=1)
    repository: HttpUrl
    revision: str = Field(default="main", min_length=1)


class BenchmarkConfig(StrictModel):
    schema_version: int = Field(default=1, ge=1)
    clio: ClioConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    environment: ServiceValues = Field(default_factory=ServiceValues)
    secrets: ServiceSecrets = Field(default_factory=ServiceSecrets)
    suites: list[SuiteConfig] = Field(default_factory=list)

    def redacted_snapshot(self) -> dict[str, Any]:
        """Return reproducibility metadata without secret values."""
        return {
            "schema_version": self.schema_version,
            "clio": {
                "agent": _repository_snapshot(self.clio.agent),
                "server": _repository_snapshot(self.clio.server),
            },
            "runtime": self.runtime.model_dump(mode="json"),
            "evaluation": self.evaluation.model_dump(mode="json"),
            "environment": self.environment.model_dump(mode="json"),
            "secret_names": {
                "agent": sorted(self.secrets.agent),
                "server": sorted(self.secrets.server),
            },
            "suites": [
                {
                    "name": suite.name,
                    "repository": str(suite.repository),
                    "revision": suite.revision,
                }
                for suite in self.suites
            ],
        }


def load_config(path: Path) -> BenchmarkConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc

    if raw is None:
        raise ConfigurationError(f"Configuration file is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigurationError("Configuration root must be a mapping")

    try:
        return BenchmarkConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(str(exc)) from exc


def _repository_snapshot(config: RepositoryConfig) -> dict[str, str]:
    return {"repository": str(config.repository), "revision": config.revision}
