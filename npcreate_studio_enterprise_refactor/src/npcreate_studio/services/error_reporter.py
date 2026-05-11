from __future__ import annotations

import traceback
from typing import Any

import httpx

from ..core.settings import Settings


class ErrorReporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_payload(self, exc: BaseException, *, title: str = "Client error", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "title": title,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            "metadata": metadata or {},
            "app_version": self.settings.app_version,
        }

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.app_api_key:
            headers["X-API-Key"] = self.settings.app_api_key
        return headers

    async def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.license_server_url:
            return {"ok": False, "reason": "license_server_url not configured"}
        url = f"{self.settings.license_server_url.rstrip('/')}/api/v1/error-reports"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=self._build_headers())
            response.raise_for_status()
            return response.json()
