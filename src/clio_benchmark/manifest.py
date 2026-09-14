"""Persistent, machine-readable benchmark run records."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run_id: str
    status: RunStatus = RunStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    config: dict[str, Any]
    case_count: int = Field(default=0, ge=0)
    error: str | None = None

    def transition(self, status: RunStatus, *, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.updated_at = datetime.now(UTC)
