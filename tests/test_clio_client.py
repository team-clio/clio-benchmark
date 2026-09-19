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


def test_repository_registration_excludes_fixture_and_oracle_files() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(200, json={"id": 2})

    client = ClioClient("http://clio.test")
    client._client.close()
    client._client = httpx.Client(
        base_url="http://clio.test", transport=httpx.MockTransport(handler)
    )

    client.register_repository(1, "https://github.com/team/repo.git", "abc123")

    assert captured["excludePaths"] == ["cases.json", "bugs.json"]
    client.close()
