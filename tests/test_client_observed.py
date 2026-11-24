from __future__ import annotations

from typing import Any

import httpx

from seed_audio_cli.client import BytePlusClient


def test_observed_client_reports_the_request_id_used_and_received_log_id(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    events: list[tuple[str, Any]] = []

    class Response:
        status_code = 200
        headers = {"X-Tt-Logid": "synthetic-provider-log-id"}

        def json(self) -> dict:
            return {"code": 0, "audio": "c3ludGhldGlj"}

    class FakeHttpClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> FakeHttpClient:
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, endpoint: str, *, headers: dict, json: dict) -> Response:
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["payload"] = json
            events.append(("post", None))
            return Response()

    monkeypatch.setattr(httpx, "Client", FakeHttpClient)
    client = BytePlusClient(
        "synthetic-key-do-not-report",
        endpoint="http://127.0.0.1:9/synthetic",
    )

    result = client.create_observed(
        {"model": "synthetic-model"},
        on_request_start=lambda request_id: events.append(("started", request_id)),
        on_response_received=lambda log_id: events.append(("response", log_id)),
    )

    request_id = captured["headers"]["X-Api-Request-Id"]
    assert events == [
        ("started", request_id),
        ("post", None),
        ("response", "synthetic-provider-log-id"),
    ]
    assert result.request_id == request_id
    assert result.provider_log_id == "synthetic-provider-log-id"
    assert captured["endpoint"] == "http://127.0.0.1:9/synthetic"

