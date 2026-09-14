"""HTTP adapter for the Clio Server benchmark path."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from clio_benchmark.errors import ClioApiError
from clio_benchmark.suite import BenchmarkCase


class ClioClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def create_project(self, name: str, description: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/projects", {"name": name, "description": description})

    def register_repository(
        self, project_id: int, repository_url: str, revision: str
    ) -> dict[str, Any]:
        parsed = urlparse(repository_url)
        path_parts = [part for part in parsed.path.removesuffix(".git").split("/") if part]
        if len(path_parts) < 2:
            raise ClioApiError(f"Cannot determine repository owner and name: {repository_url}")
        payload = {
            "provider": "GITHUB",
            "owner": path_parts[-2],
            "name": path_parts[-1],
            "url": repository_url,
            "defaultBranch": revision,
            "includePaths": [],
            "excludePaths": ["benchmark.json"],
            "enabled": True,
        }
        return self._request("POST", f"/api/v1/projects/{project_id}/repositories", payload)

    def wait_for_repository(
        self,
        project_id: int,
        repository_id: int,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = self._request("GET", f"/api/v1/projects/{project_id}/repositories")
            repository = next(
                (item for item in response.get("items", []) if item.get("id") == repository_id),
                None,
            )
            if repository is not None:
                status = repository.get("syncStatus")
                if status == "SYNCED":
                    return repository
                if status == "FAILED":
                    raise ClioApiError(f"Repository synchronization failed: {repository_id}")
            time.sleep(poll_interval_seconds)
        raise ClioApiError(f"Repository synchronization timed out: {repository_id}")

    def create_bug(self, project_id: int, case: BenchmarkCase) -> dict[str, Any]:
        report = case.report
        payload = {
            "source": "MANUAL",
            "title": report.title,
            "description": report.as_bug_description(),
            "error_type": "ReportedBehaviorMismatch",
            "message": report.actual_behavior,
            "stack_trace": [],
            "raw_payload": {"benchmark_case_id": case.id},
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        return self._request("POST", f"/external-api/v1/projects/{project_id}/bugs", payload)

    def wait_for_bug(
        self,
        project_id: int,
        bug_id: int,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = self._request("GET", f"/external-api/v1/projects/{project_id}/bugs?size=100")
            bug = next(
                (item for item in response.get("items", []) if item.get("id") == bug_id), None
            )
            if bug is not None and bug.get("status") in {"TRIAGED", "RESOLVED", "IGNORED"}:
                return bug
            time.sleep(poll_interval_seconds)
        raise ClioApiError(f"Bug processing timed out: {bug_id}")

    def wait_for_analysis(
        self,
        project_id: int,
        issue_id: int,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        path = f"/external-api/v1/projects/{project_id}/issues/{issue_id}/analysis-results/latest"
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                response = self._client.get(path)
            except httpx.HTTPError as exc:
                raise ClioApiError(f"Clio Server request failed: {exc}") from exc
            if response.status_code == 200:
                if not response.content.strip():
                    time.sleep(poll_interval_seconds)
                    continue
                payload = self._decode(response)
                if payload:
                    return payload
            if response.status_code != 404:
                self._raise_response(response)
            time.sleep(poll_interval_seconds)
        raise ClioApiError(f"Analysis result timed out for issue: {issue_id}")

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, json=payload)
        except httpx.HTTPError as exc:
            raise ClioApiError(f"Clio Server request failed: {exc}") from exc
        if not response.is_success:
            self._raise_response(response)
        return self._decode(response)

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ClioApiError("Clio Server returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ClioApiError("Clio Server returned an unexpected response shape")
        return payload

    @staticmethod
    def _raise_response(response: httpx.Response) -> None:
        raise ClioApiError(
            f"Clio Server returned HTTP {response.status_code}: {response.text[:1000]}"
        )
