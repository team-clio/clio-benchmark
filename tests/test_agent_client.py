import json

import httpx
import pytest

from clio_benchmark.agent_client import AgentLogClient, Boundary, LogCollectionError
from clio_benchmark.manifest import RunManifest
from clio_benchmark.workspace import Workspace


def collector(tmp_path, handler):
    workspace = Workspace(tmp_path)
    workspace.initialize()
    manifest = RunManifest(run_id="test", config={})
    workspace.save_manifest(manifest)
    client = AgentLogClient("http://agent")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://agent")
    return client, workspace, manifest


def test_collection_downloads_pages_and_preserves_payloads(tmp_path):
    def handler(request):
        if request.url.path.endswith("boundary"):
            return httpx.Response(200, json={"sequence": 3, "at": "end", "store_id": "test-store"})
        after = int(request.url.params["after"])
        if after == 0:
            return httpx.Response(
                200,
                json={
                    "items": [{"status": "success", "arguments": {"x": 1}, "output": "결과"}],
                    "next_cursor": 1,
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {"status": "failure", "error": {"message": "failed"}},
                    {"status": "running"},
                ],
                "next_cursor": None,
            },
        )

    client, workspace, manifest = collector(tmp_path, handler)
    client.collect(manifest, workspace, Boundary(sequence=0, at="start", store_id="test-store"))
    records = [
        json.loads(line)
        for line in (workspace.runs / "test" / "tool-calls.jsonl").read_text().splitlines()
    ]
    assert records[0]["output"] == "결과"
    assert len(records) == 3
    metadata = json.loads((workspace.runs / "test" / "tool-call-collection.json").read_text())
    assert metadata["incomplete_call_count"] == 1
    assert manifest.tool_log_status == "completed"
    assert manifest.execution_finished_at == "end"
    client.close()


def test_collection_preserves_partial_logs_on_failed_page(tmp_path):
    def handler(request):
        if request.url.path.endswith("boundary"):
            return httpx.Response(200, json={"sequence": 2, "at": "end", "store_id": "test-store"})
        if request.url.params["after"] == "0":
            return httpx.Response(200, json={"items": [{"status": "success"}], "next_cursor": 1})
        return httpx.Response(503)

    client, workspace, manifest = collector(tmp_path, handler)
    with pytest.raises(LogCollectionError):
        client.collect(manifest, workspace, Boundary(sequence=0, at="start", store_id="test-store"))
    assert manifest.tool_log_status == "failed"
    metadata = json.loads((workspace.runs / "test" / "tool-call-collection.json").read_text())
    assert metadata["partial"] is True
    assert metadata["call_count"] == 1
    assert (workspace.runs / "test" / "tool-calls.jsonl").exists()
    client.close()


def test_empty_collection_creates_empty_log_file(tmp_path):
    client, workspace, manifest = collector(
        tmp_path,
        lambda request: httpx.Response(
            200, json={"sequence": 0, "at": "end", "store_id": "test-store"}
        ),
    )
    client.collect(manifest, workspace, Boundary(sequence=0, at="start", store_id="test-store"))
    assert manifest.tool_log_status == "completed"
    assert (workspace.runs / "test" / "tool-calls.jsonl").read_text() == ""
    client.close()


def test_disabled_agent_fails_preflight():
    client = AgentLogClient("http://agent")
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(409)),
        base_url="http://agent",
    )
    with pytest.raises(LogCollectionError):
        client.boundary()
    client.close()


def test_collection_rejects_replaced_store(tmp_path):
    client, workspace, manifest = collector(
        tmp_path,
        lambda request: httpx.Response(
            200,
            json={
                "sequence": 10,
                "at": "end",
                "store_id": "replaced",
            },
        ),
    )
    with pytest.raises(LogCollectionError, match="reset"):
        client.collect(manifest, workspace, Boundary(sequence=0, at="start", store_id="original"))
    assert manifest.tool_log_status == "failed"
    client.close()
