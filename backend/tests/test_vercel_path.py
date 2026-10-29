"""Exercise Vercel's rewritten URLs through the ASGI entrypoint."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from api.index import VercelPathMiddleware, app


def request(path: str, query_string: str = "") -> tuple[int, dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    raw_path = path.encode("utf-8")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": query_string.encode("ascii"),
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
    }

    asyncio.run(app(scope, receive, send))
    response_start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return response_start["status"], json.loads(response_body)


def test_rewritten_health_path_returns_health_response() -> None:
    status, body = request("/api/index", "__path=health")

    assert status == 200
    assert body == {"status": "ok"}


def test_rewritten_summary_path_preserves_query_parameters() -> None:
    status, body = request(
        "/api/index",
        "__path=accuracy/summary&cutoff=09:00&mode=raw",
    )

    assert status == 200
    assert body["cutoff"] == "09:00"
    assert body["mode"] == "raw"
    assert body["n_hourly_forecasts"] == 744


def test_plain_api_path_is_unchanged_without_rewrite_parameter() -> None:
    status, body = request("/api/health")

    assert status == 200
    assert body == {"status": "ok"}


def test_middleware_rewrites_path_and_removes_only_internal_query_parameter() -> None:
    received_scope: dict[str, Any] = {}
    scope = {
        "type": "http",
        "path": "/api/index",
        "raw_path": b"/api/index",
        "query_string": b"__path=accuracy/summary&cutoff=09:00&mode=raw",
    }

    async def capture_scope(
        forwarded_scope: dict[str, Any], _receive: Any, _send: Any
    ) -> None:
        received_scope.update(forwarded_scope)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: dict[str, Any]) -> None:
        return None

    asyncio.run(VercelPathMiddleware(capture_scope)(scope, receive, send))

    assert received_scope["path"] == "/api/accuracy/summary"
    assert received_scope["raw_path"] == b"/api/accuracy/summary"
    assert received_scope["query_string"] == b"cutoff=09%3A00&mode=raw"
    assert scope["path"] == "/api/index"
    assert scope["query_string"].startswith(b"__path=")


def test_unmatched_route_404_includes_received_path() -> None:
    status, body = request("/api/no-such-route")

    assert status == 404
    assert body == {"detail": "Not found", "path": "/api/no-such-route"}
