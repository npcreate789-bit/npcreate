from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .security import sanitize_metadata


class DevicePolicyIn(BaseModel):
    device_type: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_\-]+$")
    max_devices: int = Field(default=1, ge=0, le=200)
    binding_mode: Literal["admin_release_only", "auto_replace_disabled"] = "admin_release_only"
    fingerprint_required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return sanitize_metadata(value)


class DevicePolicyOut(DevicePolicyIn):
    policy_id: str
    license_id: str
    created_at: datetime
    updated_at: datetime


class ActivateLicenseRequest(BaseModel):
    license_key: str = Field(min_length=8, max_length=80)
    device_type: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_\-]+$")
    device_fingerprint: str = Field(min_length=32, max_length=128)
    device_label: str = Field(default="", max_length=120)
    device_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("device_metadata")
    @classmethod
    def device_metadata_must_be_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return sanitize_metadata(value)
    app_version: str = Field(default="", max_length=40)


class ActivateLicenseResponse(BaseModel):
    license_id: str
    status: str
    expires_at: datetime
    device_id: str
    activation_token: str
    refresh_token: str | None = None
    features: list[str] = []
    message: str


class HeartbeatRequest(BaseModel):
    app_version: str = Field(default="", max_length=40)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime


class AdminCreateLicenseRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=160)
    customer_contact: str = Field(default="", max_length=160)
    months: int = Field(default=1, ge=1, le=36)
    max_pc_devices: int = Field(default=1, ge=0, le=10)
    max_phone_devices: int = Field(default=1, ge=0, le=50)
    device_policies: list[DevicePolicyIn] | None = None
    features: list[str] = Field(default_factory=lambda: ["studio", "phone_bind", "updates", "auto_billing"])
    notes: str = Field(default="", max_length=1000)

    @field_validator("device_policies")
    @classmethod
    def unique_device_types(cls, value: list[DevicePolicyIn] | None) -> list[DevicePolicyIn] | None:
        if not value:
            return value
        seen: set[str] = set()
        for item in value:
            if item.device_type in seen:
                raise ValueError(f"duplicate device_type: {item.device_type}")
            seen.add(item.device_type)
        return value


class AdminCreateLicenseResponse(BaseModel):
    license_id: str
    license_key: str
    expires_at: datetime


class AdminRenewLicenseRequest(BaseModel):
    months: int = Field(default=1, ge=1, le=36)


class AdminUpsertDevicePoliciesRequest(BaseModel):
    policies: list[DevicePolicyIn] = Field(min_length=1, max_length=20)

    @field_validator("policies")
    @classmethod
    def unique_device_types(cls, value: list[DevicePolicyIn]) -> list[DevicePolicyIn]:
        seen: set[str] = set()
        for item in value:
            if item.device_type in seen:
                raise ValueError(f"duplicate device_type: {item.device_type}")
            seen.add(item.device_type)
        return value


class ReleaseRequestCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class AdminResolveReleaseRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class LicenseSummaryOut(BaseModel):
    license_id: str
    customer_name: str
    customer_contact: str = ""
    status: str
    plan: str
    expires_at: datetime
    features: list[str] = []
    notes: str = ""


class AdminPublishNewsRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)
    severity: str = Field(default="info", pattern="^(info|success|warning|critical)$")
    audience: str = Field(default="all", max_length=80)
    expires_at: datetime | None = None


class AdminPublishUpdateRequest(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    channel: str = Field(default="stable", pattern="^(stable|beta|dev)$")
    mandatory: bool = False
    download_url: str = Field(min_length=8, max_length=2000)
    sha256: str = Field(min_length=64, max_length=64)
    signature: str | None = Field(default=None, min_length=128, max_length=128)
    release_notes: str = Field(default="", max_length=5000)


class UpdateManifestOut(BaseModel):
    version: str
    channel: str
    mandatory: bool
    download_url: str
    sha256: str
    signature: str
    release_notes: str


class AdminCreateSubscriptionRequest(BaseModel):
    license_id: str = Field(min_length=8, max_length=80)
    provider: str = Field(default="manual", min_length=2, max_length=40, pattern=r"^[a-z0-9_\-]+$")
    provider_customer_id: str = Field(default="", max_length=160)
    provider_subscription_id: str = Field(min_length=3, max_length=160)
    amount_satangs: int = Field(default=0, ge=0, le=50_000_000)
    currency: str = Field(default="THB", min_length=3, max_length=3)
    next_renewal_at: datetime | None = None


class SubscriptionOut(BaseModel):
    subscription_id: str
    license_id: str
    provider: str
    provider_subscription_id: str
    status: str
    billing_cycle: str
    amount_satangs: int
    currency: str
    next_renewal_at: datetime | None = None
    last_payment_at: datetime | None = None


class PaymentEventOut(BaseModel):
    event_id: str
    provider: str
    external_event_id: str
    event_type: str
    processing_status: str
    received_at: datetime
    processed_at: datetime | None = None
