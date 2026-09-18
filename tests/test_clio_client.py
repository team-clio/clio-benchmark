import httpx

from clio_benchmark.clio_client import ClioClient


def test_wait_for_analysis_retries_empty_success_response() -> None:
    responses = iter(
        [
            httpx.Response(200, content=b""),
            httpx.Response(200, json={"analysisResultId": 1}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = ClioClient("http://clio.test")
    client._client.close()
    client._client = httpx.Client(
        base_url="http://clio.test", transport=httpx.MockTransport(handler)
    )

    result = client.wait_for_analysis(1, 1, timeout_seconds=1, poll_interval_seconds=0)

    assert result == {"analysisResultId": 1}
    client.close()


def test_reads_workflow_result_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal-api/v1/projects/1/workflow-runs/7"
        return httpx.Response(
            200,
            json={"id": 7, "result_snapshot": {"analysis_profile": "full-clio"}},
        )

    client = ClioClient("http://clio.test")
    client._client.close()
    client._client = httpx.Client(
        base_url="http://clio.test", transport=httpx.MockTransport(handler)
    )

    result = client.get_workflow(1, 7)

    assert result["result_snapshot"]["analysis_profile"] == "full-clio"
    client.close()
