from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class DeviceType(StrEnum):
    PC = "pc"
    PHONE = "phone"


class LicenseStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass(frozen=True)
class VerifiedLicense:
    license_id: str
    customer_name: str
    expires_at: datetime | None
    max_devices: int
    features: tuple[str, ...]


@dataclass(frozen=True)
class DeviceIdentity:
    device_type: DeviceType
    fingerprint_hash: str
    label: str
    raw_metadata: dict[str, Any]


@dataclass(frozen=True)
class ActivationResult:
    license_id: str
    status: LicenseStatus
    expires_at: datetime
    device_id: str
    activation_token: str
    refresh_token: str | None
    features: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class NewsItem:
    news_id: str
    title: str
    body: str
    severity: str
    published_at: datetime


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    channel: str
    mandatory: bool
    download_url: str
    sha256: str
    signature: str
    release_notes: str
