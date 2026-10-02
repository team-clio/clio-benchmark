"""Agent의 벤치마크 Tool 로그를 종료 후 페이지 단위로 수집한다."""

import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clio_benchmark.errors import BenchmarkError
from clio_benchmark.manifest import RunManifest
from clio_benchmark.workspace import Workspace


class LogCollectionError(BenchmarkError):
    pass


class Boundary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=0)
    at: str
    store_id: str


class LogPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict[str, Any]]
    next_cursor: int | None = Field(default=None, ge=0)


class AgentLogClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, **params: Any) -> Any:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LogCollectionError(f"Agent Tool log request failed: {exc}") from exc

    def boundary(self) -> Boundary:
        try:
            return Boundary.model_validate(self._get("/benchmark/tool-calls/boundary"))
        except ValidationError as exc:
            raise LogCollectionError(f"Invalid Agent log boundary: {exc}") from exc

    def collect(self, manifest: RunManifest, workspace: Workspace, start: Boundary) -> None:
        count = 0
        incomplete = 0
        end: Boundary | None = None
        manifest.tool_log_status = "collecting"
        workspace.save_manifest(manifest)
        destination = workspace.runs / manifest.run_id / "tool-calls.jsonl"
        try:
            end = self.boundary()
            manifest.execution_finished_at = end.at
            if end.store_id != start.store_id or end.sequence < start.sequence:
                raise LogCollectionError("Agent Tool log store was reset during the benchmark")
            cursor = start.sequence
            with destination.open("w", encoding="utf-8") as stream:
                while cursor < end.sequence:
                    try:
                        page = LogPage.model_validate(
                            self._get(
                                "/benchmark/tool-calls",
                                after=cursor,
                                through=end.sequence,
                                limit=100,
                                store_id=start.store_id,
                            )
                        )
                    except ValidationError as exc:
                        raise LogCollectionError(f"Invalid Agent log page: {exc}") from exc
                    for record in page.items:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                        count += 1
                        incomplete += int(record.get("status") == "running")
                    if page.next_cursor is None:
                        break
                    if not cursor < page.next_cursor <= end.sequence:
                        raise LogCollectionError("Agent Tool log cursor did not advance")
                    cursor = page.next_cursor
            if count != end.sequence - start.sequence:
                raise LogCollectionError("Agent returned an incomplete Tool log range")
            manifest.tool_log_status = "completed"
        except Exception as exc:
            manifest.tool_log_status = "failed"
            manifest.tool_log_error = str(exc)
            raise LogCollectionError(f"Tool log collection failed: {exc}") from exc
        finally:
            workspace.write_run_artifact(
                manifest.run_id,
                Path("tool-call-collection.json"),
                {
                    "status": manifest.tool_log_status,
                    "start": start.model_dump(),
                    "end": end.model_dump() if end else None,
                    "call_count": count,
                    "incomplete_call_count": incomplete,
                    "partial": manifest.tool_log_status == "failed" and count > 0,
                    "error": manifest.tool_log_error,
                },
            )
            workspace.save_manifest(manifest)
            report = workspace.runs / manifest.run_id / "report.md"
            if report.exists():
                with report.open("a", encoding="utf-8") as stream:
                    stream.write(
                        f"\nTool 로그 수집: {manifest.tool_log_status}, "
                        f"{count}건 (미완료 {incomplete}건)\n"
                    )
