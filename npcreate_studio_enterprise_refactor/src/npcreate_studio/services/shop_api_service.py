from __future__ import annotations

import httpx


class ShopApiService:
    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str, token: str) -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            resp = client.get(f"{self.base_url}/{path.lstrip('/')}")
            resp.raise_for_status()
            return resp.json()
