from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from npcreate_studio.core.settings import Settings
from npcreate_studio.services.error_reporter import ErrorReporter


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "license_server_url": "http://127.0.0.1:8088",
        "app_api_key": "dev_app_api_key_please_change_123456",
    }
    base.update(overrides)
    return Settings(**base)


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_build_payload_contains_title_and_traceback() -> None:
    reporter = ErrorReporter(_settings())
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        payload = reporter.build_payload(exc, title="My title", metadata={"k": "v"})
    assert payload["title"] == "My title"
    assert payload["message"] == "boom"
    assert "RuntimeError: boom" in payload["traceback"]
    assert payload["metadata"] == {"k": "v"}
    assert payload["app_version"]


def test_submit_uses_correct_path_and_api_key_header() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True, "report_id": "err_test"})

    transport = httpx.MockTransport(handler)
    reporter = ErrorReporter(_settings())

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=transport, base_url="http://x") as client:
            response = await client.post(
                f"{reporter.settings.license_server_url.rstrip('/')}/api/v1/error-reports",
                json={"title": "t"},
                headers=reporter._build_headers(),
            )
            response.raise_for_status()
            return response.json()

    result = _run(run())
    assert result == {"ok": True, "report_id": "err_test"}
    assert captured["url"].endswith("/api/v1/error-reports")
    assert "/public/" not in captured["url"]
    assert captured["headers"].get("x-api-key") == "dev_app_api_key_please_change_123456"


def test_submit_short_circuits_without_license_server_url() -> None:
    reporter = ErrorReporter(_settings(license_server_url=None))
    result = _run(reporter.submit({"title": "t"}))
    assert result["ok"] is False
    assert "license_server_url" in result["reason"]


def test_submit_omits_header_when_api_key_missing() -> None:
    reporter = ErrorReporter(_settings(app_api_key=None))
    headers = reporter._build_headers()
    assert "X-API-Key" not in headers


@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1:8088",
    "http://127.0.0.1:8088/",
    "https://api.example.com/",
])
def test_submit_normalizes_trailing_slash(base_url: str) -> None:
    reporter = ErrorReporter(_settings(license_server_url=base_url))
    expected_url = f"{base_url.rstrip('/')}/api/v1/error-reports"
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post(expected_url, json={"title": "t"}, headers=reporter._build_headers())

    _run(run())
    assert captured["url"] == expected_url
