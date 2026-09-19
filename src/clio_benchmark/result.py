"""Stable benchmark result models independent of Clio API response shapes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CaseStatus(StrEnum):
    COMPLETED = "completed"
    CLIO_FAILED = "clio_failed"
    EVALUATION_FAILED = "evaluation_failed"
    INFRA_ERROR = "infra_error"
    TIMEOUT = "timeout"


class NormalizedLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    start_line: int | None = None
    end_line: int | None = None


class NormalizedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected: bool
    root_cause: str | None = None
    explanation: str | None = None
    solution: str | None = None
    evidence: list[str] = Field(default_factory=list)
    locations: list[NormalizedLocation] = Field(default_factory=list)


class CaseExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: CaseStatus
    duration_seconds: float = Field(ge=0)
    error: str | None = None
    normalized: NormalizedResult | None = None


def normalize_clio_result(payload: dict[str, Any] | None) -> NormalizedResult:
    """Normalize known Clio fields while retaining the raw response separately."""
    if not payload:
        return NormalizedResult(detected=False)

    verdict = _first(payload, "detected", "isBug", "is_bug", "verdict", "bugDetected")
    detected = _as_detected(verdict)
    root_cause = _as_text(_first(payload, "rootCause", "root_cause", "cause"))
    explanation = _as_text(_first(payload, "explanation", "analysisText", "summary"))
    solution = _as_text(_first(payload, "solution", "suggestedFix", "recommendation"))
    evidence_value = _first(payload, "evidence", "evidences", "citations")
    locations_value = _first(payload, "locations", "codeLocations", "sourceLocations", "location")
    locations = _normalize_locations(locations_value)

    if verdict is None:
        detected = bool(root_cause or explanation or locations)

    return NormalizedResult(
        detected=detected,
        root_cause=root_cause,
        explanation=explanation,
        solution=solution,
        evidence=_as_text_list(evidence_value),
        locations=locations,
    )


def _first(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for nested in value.values():
            found = _first(nested, *keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _first(nested, *keys)
            if found is not None:
                return found
    return None


def _as_detected(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {
            "true", "bug", "detected", "valid", "confirmed", "triaged", "resolved"
        }
    return bool(value)


def _as_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value if (text := _as_text(item))]
    return []


def _normalize_locations(value: Any) -> list[NormalizedLocation]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    locations: list[NormalizedLocation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        file = item.get("file") or item.get("filePath") or item.get("path")
        if not isinstance(file, str) or not file:
            continue
        line = item.get("line")
        start = item.get("startLine", item.get("start_line", line))
        end = item.get("endLine", item.get("end_line", start))
        locations.append(
            NormalizedLocation(
                file=file,
                start_line=start if isinstance(start, int) else None,
                end_line=end if isinstance(end, int) else None,
            )
        )
    return locations
