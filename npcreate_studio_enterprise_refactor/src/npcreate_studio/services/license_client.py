from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel

from ..domain.licenses import ActivationResult, DeviceIdentity, LicenseStatus, NewsItem


class ActivationResponse(BaseModel):
    license_id: str
    status: str
    expires_at: datetime
    device_id: str
    activation_token: str
    refresh_token: str | None = None
    features: list[str] = []
    message: str = ""


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True)
class LicenseClient:
    base_url: str
    app_version: str
    timeout_seconds: float = 15.0

    def activate(self, license_key: str, identity: DeviceIdentity) -> ActivationResult:
        payload: dict[str, Any] = {
            "license_key": license_key.strip(),
            "device_type": identity.device_type.value,
            "device_fingerprint": identity.fingerprint_hash,
            "device_label": identity.label,
            "device_metadata": identity.raw_metadata,
            "app_version": self.app_version,
        }
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            r = client.post("/api/v1/licenses/activate", json=payload)
            r.raise_for_status()
            data = ActivationResponse.model_validate(r.json())
        return ActivationResult(
            license_id=data.license_id,
            status=LicenseStatus(data.status),
            expires_at=data.expires_at,
            device_id=data.device_id,
            activation_token=data.activation_token,
            refresh_token=data.refresh_token,
            features=tuple(data.features),
            message=data.message,
        )

    def refresh(self, refresh_token: str) -> RefreshResponse:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
            r.raise_for_status()
            return RefreshResponse.model_validate(r.json())

    def heartbeat(self, activation_token: str, *, app_version: str | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {activation_token}"}
        payload = {"app_version": app_version or self.app_version}
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            r = client.post("/api/v1/licenses/heartbeat", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()

    def fetch_news(self, activation_token: str) -> list[NewsItem]:
        headers = {"Authorization": f"Bearer {activation_token}"}
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            r = client.get("/api/v1/news", headers=headers)
            r.raise_for_status()
            rows = r.json().get("items", [])
        return [
            NewsItem(
                news_id=str(row["news_id"]),
                title=str(row["title"]),
                body=str(row["body"]),
                severity=str(row.get("severity", "info")),
                published_at=datetime.fromisoformat(str(row["published_at"]).replace("Z", "+00:00")),
            )
            for row in rows
        ]

    def request_admin_release(self, activation_token: str, reason: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {activation_token}"}
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            r = client.post("/api/v1/devices/release-request", json={"reason": reason}, headers=headers)
            r.raise_for_status()
            return r.json()
